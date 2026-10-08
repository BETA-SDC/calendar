#!/usr/bin/env python3
"""AI-friendly CLI for managing one-event ICS source files."""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event, vDDDTypes

from build_feeds import (
    REPOSITORY_ROOT,
    SCOPE_LABELS,
    event_uid,
    load_source_events,
    serialize_event,
)


TIMEZONE_NAME = "Asia/Shanghai"
LOCAL_ZONE = ZoneInfo(TIMEZONE_NAME)
PRODID = "-//Apple Inc.//macOS 15.5//EN"
SLUG_RE = re.compile(r"[^a-z0-9]+")


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def require_bilingual(value: str, field: str) -> None:
    if " / " not in value:
        fail(f"{field} must use the bilingual format 中文 / English")


def parse_start(value: str) -> date | datetime:
    try:
        if "T" not in value:
            return date.fromisoformat(value)
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        fail(f"invalid date/time {value!r}; use YYYY-MM-DD or YYYY-MM-DDTHH:MM")
        raise AssertionError from exc
    return parsed.replace(tzinfo=LOCAL_ZONE) if parsed.tzinfo is None else parsed


def parse_end(value: str, start: date | datetime) -> date | datetime:
    end = parse_start(value)
    if isinstance(start, date) and not isinstance(start, datetime):
        if isinstance(end, datetime):
            fail("all-day events require a date-only --end")
    elif not isinstance(end, datetime):
        fail("timed events require a date/time --end")
    return end


def format_dt(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    return value.isoformat()


def source_paths(root: Path = REPOSITORY_ROOT) -> list[Path]:
    return sorted(
        path
        for scope in ("public", "internal")
        for path in (root / scope).rglob("*.ics")
    )


def resolve_event(identifier: str, root: Path = REPOSITORY_ROOT) -> tuple[Path, Calendar, Any]:
    candidates: list[Path] = []
    supplied = Path(identifier)
    if supplied.is_absolute():
        candidates.append(supplied)
    else:
        candidates.extend((root / supplied, root / supplied.with_suffix(".ics")))

    for path in candidates + source_paths(root):
        if not path.is_file():
            continue
        calendar = Calendar.from_ical(path.read_bytes())
        events = [component for component in calendar.walk() if component.name == "VEVENT"]
        if len(events) != 1:
            continue
        event = events[0]
        if (
            path == (root / supplied)
            or path == (root / supplied.with_suffix(".ics"))
            or path.name == identifier
            or event_uid(event, path) == identifier
        ):
            return path, calendar, event
    fail(f"event not found: {identifier}")
    raise AssertionError


def add_timezone(calendar: Calendar) -> None:
    timezone_component = Calendar.from_ical(
        b"""BEGIN:VTIMEZONE\r
TZID:Asia/Shanghai\r
BEGIN:STANDARD\r
DTSTART:19890917T020000\r
RRULE:FREQ=YEARLY;UNTIL=19910914T170000Z;BYMONTH=9;BYDAY=3SU\r
TZNAME:GMT+8\r
TZOFFSETFROM:+0900\r
TZOFFSETTO:+0800\r
END:STANDARD\r
BEGIN:DAYLIGHT\r
DTSTART:19910414T020000\r
RDATE:19910414T020000\r
TZNAME:GMT+8\r
TZOFFSETFROM:+0800\r
TZOFFSETTO:+0900\r
END:DAYLIGHT\r
END:VTIMEZONE\r
"""
    )
    calendar.add_component(next(component for component in timezone_component.walk() if component.name == "VTIMEZONE"))


def add_alarm(event: Event, minutes: int) -> None:
    component = Alarm()
    component.add("ACTION", "DISPLAY")
    component.add("DESCRIPTION", "提醒事项 / Reminder")
    component.add("TRIGGER", timedelta(minutes=-minutes))
    component.add("UID", str(uuid.uuid4()).upper())
    component.add("X-WR-ALARMUID", str(uuid.uuid4()).upper())
    event.add_component(component)


def remove_alarms(event: Any) -> None:
    event.subcomponents = [
        component
        for component in event.subcomponents
        if component.name != "VALARM"
    ]


def write_calendar(path: Path, calendar: Calendar) -> None:
    data = calendar.to_ical().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    lines = data.split(b"\r\n")
    if any(len(line) > 75 for line in lines):
        fail(f"generated ICS contains a line longer than 75 bytes: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def slug_from_title(title: str) -> str:
    english = title.split(" / ", 1)[-1]
    slug = SLUG_RE.sub("-", english.lower()).strip("-")
    return slug or f"event-{uuid.uuid4().hex[:8]}"


def validate_filename_stem(stem: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", stem):
        fail("--filename must contain only lowercase letters, digits, and hyphens")
    return stem


def event_path(scope: str, start: date | datetime, stem: str, root: Path) -> Path:
    if scope not in ("public", "internal"):
        fail("--scope must be public or internal")
    return (
        root
        / scope
        / f"{start.year:04d}"
        / f"{start.month:02d}"
        / f"{start.year:04d}-{start.month:02d}-{start.day:02d}-{stem}.ics"
    )


def source_event_data(path: Path, event: Any, root: Path) -> dict[str, Any]:
    start = event.decoded("DTSTART")
    end = event.decoded("DTEND") if event.get("DTEND") else None
    scope = path.relative_to(root).parts[0]
    return {
        "uid": event_uid(event, path),
        "scope": scope,
        "scopeLabel": SCOPE_LABELS[scope],
        "title": str(event.get("SUMMARY", "")).strip(),
        "location": str(event.get("LOCATION", "")).strip(),
        "path": path.relative_to(root).as_posix(),
        "start": format_dt(start),
        "end": format_dt(end) if end else None,
    }


def output(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    elif isinstance(value, list):
        for item in value:
            print(
                f"{item['uid']}\t{item['scope']}\t{item['start']}\t"
                f"{item['title']}\t{item['path']}"
            )
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def command_list(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    by_scope = load_source_events(root)
    entries = [
        entry
        for scope in ("public", "internal")
        if args.scope in ("all", scope)
        for entry in by_scope[scope]
    ]
    events = [serialize_event(entry, root) | {
        "path": entry.path.relative_to(root).as_posix()
    } for entry in entries]
    if args.from_date:
        events = [item for item in events if item["date"] >= args.from_date]
    if args.to_date:
        events = [item for item in events if item["date"] <= args.to_date]
    output(events, args.json)


def command_show(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    path, _, event = resolve_event(args.identifier, root)
    output(source_event_data(path, event, root), args.json)


def command_add(args: argparse.Namespace) -> None:
    require_bilingual(args.title, "--title")
    if args.location:
        require_bilingual(args.location, "--location")
    start = parse_start(args.start)
    end = parse_end(args.end, start)
    uid = args.uid or str(uuid.uuid4()).upper()
    root = args.root.resolve()
    existing = {event_uid(entry.event, entry.path) for entries in load_source_events(root).values() for entry in entries}
    if uid in existing:
        fail(f"UID already exists: {uid}")
    calendar = Calendar()
    calendar.add("VERSION", "2.0")
    calendar.add("PRODID", PRODID)
    calendar.add("CALSCALE", "GREGORIAN")
    brand = "BETA" if args.scope == "public" else "BETA-SDC"
    calendar.add("X-WR-CALNAME", f"{brand} {SCOPE_LABELS[args.scope]}")
    calendar.add("X-APPLE-CALENDAR-COLOR", "#65DB39" if args.scope == "internal" else "#4A90E2")
    add_timezone(calendar)
    event = Event()
    event.add("UID", uid)
    event.add("SUMMARY", args.title)
    event.add("DTSTART", start)
    event.add("DTEND", end)
    event.add("DTSTAMP", datetime.now(timezone.utc))
    event.add("LAST-MODIFIED", datetime.now(timezone.utc))
    event.add("CREATED", datetime.now(timezone.utc))
    event.add("SEQUENCE", 0)
    event.add("TRANSP", "OPAQUE")
    if args.location:
        event.add("LOCATION", args.location)
    if args.alarm_minutes is not None:
        add_alarm(event, args.alarm_minutes)
    calendar.add_component(event)
    stem = validate_filename_stem(args.filename) if args.filename else slug_from_title(args.title)
    path = event_path(args.scope, start, stem, root)
    if path.exists():
        fail(f"target file already exists: {path.relative_to(root)}")
    write_calendar(path, calendar)
    output({"action": "add", "path": path.relative_to(root).as_posix(), "uid": uid}, args.json)


def command_update(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    path, calendar, event = resolve_event(args.identifier, root)
    old_start = event.decoded("DTSTART")
    changed = False
    if args.title:
        require_bilingual(args.title, "--title")
        event["SUMMARY"] = args.title
        changed = True
    if args.location is not None:
        require_bilingual(args.location, "--location")
        event["LOCATION"] = args.location
        changed = True
    if args.start:
        new_start = parse_start(args.start)
        event["DTSTART"] = vDDDTypes(new_start)
        if args.end:
            event["DTEND"] = vDDDTypes(parse_end(args.end, new_start))
        changed = True
    elif args.end:
        current_start = old_start
        event["DTEND"] = vDDDTypes(parse_end(args.end, current_start))
        changed = True
    if args.alarm_minutes is not None:
        remove_alarms(event)
        add_alarm(event, args.alarm_minutes)
        changed = True
    if args.clear_alarms:
        remove_alarms(event)
        changed = True
    if not changed:
        fail("provide at least one field to update")
    event["SEQUENCE"] = int(event.get("SEQUENCE", 0)) + 1
    stamp = datetime.now(timezone.utc)
    event["DTSTAMP"] = vDDDTypes(stamp)
    event["LAST-MODIFIED"] = vDDDTypes(stamp)
    new_start = event.decoded("DTSTART")
    target = path
    if args.start:
        target = event_path(
            path.relative_to(root).parts[0],
            new_start,
            path.stem.split("-", 3)[-1],
            root,
        )
    if target != path and target.exists():
        fail(f"target file already exists: {target.relative_to(root)}")
    write_calendar(target, calendar)
    if target != path:
        path.unlink()
    output(
        {
            "action": "update",
            "old_path": path.relative_to(root).as_posix(),
            "path": target.relative_to(root).as_posix(),
            "uid": event_uid(event, target),
            "sequence": int(event["SEQUENCE"]),
        },
        args.json,
    )


def command_delete(args: argparse.Namespace) -> None:
    if not args.yes:
        fail("delete requires --yes")
    root = args.root.resolve()
    path, _, event = resolve_event(args.identifier, root)
    path.unlink()
    output(
        {"action": "delete", "path": path.relative_to(root).as_posix(), "uid": event_uid(event, path)},
        args.json,
    )


def command_validate(args: argparse.Namespace) -> None:
    by_scope = load_source_events(args.root.resolve())
    count = sum(len(entries) for entries in by_scope.values())
    result = {"valid": True, "events": count, "scopes": {scope: len(by_scope[scope]) for scope in ("public", "internal")}}
    output(result, args.json)


def command_build(args: argparse.Namespace) -> None:
    from build_feeds import build_site

    root = args.root.resolve()
    build_site(root, root / "site")
    output({"action": "build", "output": str((root / "site").relative_to(root))}, args.json)


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-j", "--json", action="store_true", help="emit machine-readable JSON")
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--version", action="version", version="calendar-cli 1.0")
    cli.add_argument("-v", "--verbose", action="store_true", help="enable verbose diagnostics")
    cli.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository root (default: current calendar repository)",
    )
    subparsers = cli.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", parents=[common])
    list_parser.add_argument("-s", "--scope", choices=("all", "public", "internal"), default="all")
    list_parser.add_argument("--from", dest="from_date")
    list_parser.add_argument("--to", dest="to_date")
    list_parser.set_defaults(handler=command_list)

    show_parser = subparsers.add_parser("show", parents=[common])
    show_parser.add_argument("identifier", help="UID, filename, or repository-relative path")
    show_parser.set_defaults(handler=command_show)

    add_parser = subparsers.add_parser("add", parents=[common])
    add_parser.add_argument("-s", "--scope", choices=("public", "internal"), required=True)
    add_parser.add_argument("--start", required=True)
    add_parser.add_argument("--end", required=True)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--location")
    add_parser.add_argument("--alarm-minutes", type=int)
    add_parser.add_argument("--uid")
    add_parser.add_argument("-f", "--filename", help="filename stem without .ics")
    add_parser.set_defaults(handler=command_add)

    update_parser = subparsers.add_parser("update", parents=[common])
    update_parser.add_argument("identifier")
    update_parser.add_argument("--start")
    update_parser.add_argument("--end")
    update_parser.add_argument("--title")
    update_parser.add_argument("--location")
    alarm_group = update_parser.add_mutually_exclusive_group()
    alarm_group.add_argument("--alarm-minutes", type=int)
    alarm_group.add_argument("--clear-alarms", action="store_true")
    update_parser.set_defaults(handler=command_update)

    delete_parser = subparsers.add_parser("delete", parents=[common])
    delete_parser.add_argument("identifier")
    delete_parser.add_argument("-y", "--yes", action="store_true")
    delete_parser.set_defaults(handler=command_delete)

    validate_parser = subparsers.add_parser("validate", parents=[common])
    validate_parser.set_defaults(handler=command_validate)

    build_parser = subparsers.add_parser("build", parents=[common])
    build_parser.set_defaults(handler=command_build)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.verbose:
        print(f"calendar: command={args.command} root={args.root.resolve()}", file=sys.stderr)
    args.handler(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
