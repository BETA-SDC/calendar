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
    BASE_URL,
    REPOSITORY_ROOT,
    SCOPE_LABELS,
    STATUS_LABELS,
    event_status,
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


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return parsed


def parse_date_argument(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


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
    return parsed.replace(tzinfo=LOCAL_ZONE) if parsed.tzinfo is None else parsed.astimezone(LOCAL_ZONE)


def parse_end(value: str, start: date | datetime) -> date | datetime:
    end = parse_start(value)
    if isinstance(start, date) and not isinstance(start, datetime):
        if isinstance(end, datetime):
            fail("all-day events require a date-only --end")
    elif not isinstance(end, datetime):
        fail("timed events require a date/time --end")
    return end


def schedule_end(
    args: argparse.Namespace, start: date | datetime
) -> date | datetime | None:
    if args.end:
        return parse_end(args.end, start)
    if args.duration_minutes is not None:
        if not isinstance(start, datetime):
            fail("--duration-minutes requires a timed --start; use --days for all-day events")
        return start + timedelta(minutes=args.duration_minutes)
    if args.duration_days is not None:
        if isinstance(start, datetime):
            fail("--days requires a date-only --start; use --duration-minutes for timed events")
        return start + timedelta(days=args.duration_days)
    return None


def format_dt(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
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


def write_calendar(path: Path, calendar: Calendar, *, dry_run: bool = False) -> None:
    event = calendar.walk("VEVENT")[0]
    start = event.decoded("DTSTART")
    if event.get("DTEND"):
        end = event.decoded("DTEND")
        if isinstance(start, datetime) != isinstance(end, datetime):
            fail("DTSTART and DTEND must both be dates or both be date/times")
        if end <= start:
            fail("DTEND must be later than DTSTART")
    data = calendar.to_ical().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    lines = data.split(b"\r\n")
    if any(len(line) > 75 for line in lines):
        fail(f"generated ICS contains a line longer than 75 bytes: {path}")
    if not dry_run:
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
        "status": event_status(event),
        "statusLabel": STATUS_LABELS[event_status(event)],
        "requiresKey": scope == "internal" or event_status(event) == "tentative",
        "title": str(event.get("SUMMARY", "")).strip(),
        "location": str(event.get("LOCATION", "")).strip(),
        "description": str(event.get("DESCRIPTION", "")),
        "sourceUrl": str(event.get("URL", "")),
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


def query_events(args: argparse.Namespace) -> list[dict[str, Any]]:
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
    if args.from_date and args.to_date and args.from_date > args.to_date:
        fail("--from must not be later than --to")
    if args.command == "agenda":
        first = args.from_date or datetime.now(LOCAL_ZONE).date().isoformat()
        last = args.to_date or (date.fromisoformat(first) + timedelta(days=args.days - 1)).isoformat()
        if first > last:
            fail("--from must not be later than --to")
        window_start = datetime.combine(date.fromisoformat(first), datetime.min.time(), LOCAL_ZONE)
        window_end = datetime.combine(
            date.fromisoformat(last) + timedelta(days=1), datetime.min.time(), LOCAL_ZONE
        )
        def in_window(item: dict[str, Any]) -> bool:
            start = parse_start(item["start"])
            end = parse_start(item["end"]) if item["end"] else start
            if not isinstance(start, datetime):
                start = datetime.combine(start, datetime.min.time(), LOCAL_ZONE)
                end = datetime.combine(end, datetime.min.time(), LOCAL_ZONE)
                if not item["end"]:
                    end += timedelta(days=1)
            return start < window_end and (
                end > window_start or (end == start and start >= window_start)
            )
        events = [item for item in events if in_window(item)]
    else:
        if args.from_date:
            events = [item for item in events if item["date"] >= args.from_date]
        if args.to_date:
            events = [item for item in events if item["date"] <= args.to_date]
    if args.status != "all":
        events = [item for item in events if item["status"] == args.status]
    if args.query:
        terms = args.query.casefold().split()
        events = [
            item for item in events
            if all(term in " ".join(str(item[key]) for key in (
                "uid", "title", "location", "path"
            )).casefold() for term in terms)
        ]
    events.sort(key=lambda item: (parse_start(item["start"]).isoformat(), item["uid"]))
    if args.limit is not None:
        events = events[:args.limit]
    return events


def command_list(args: argparse.Namespace) -> None:
    events = query_events(args)
    if args.fields:
        allowed = {
            "uid", "scope", "scopeLabel", "status", "statusLabel", "requiresKey",
            "title", "location", "path", "start", "end", "allDay", "date", "year",
            "month", "url", "filename",
        }
        fields = args.fields.split(",")
        if any(field not in allowed for field in fields):
            fail("--fields contains an unknown field")
        events = [{field: item[field] for field in fields} for item in events]
        output(events, True)
    else:
        output(events, args.json)


def command_inspect(args: argparse.Namespace) -> None:
    if args.source.startswith("https://github.com/"):
        command_prepare(args)
        return
    source = Path(args.source).expanduser().resolve()
    calendar = Calendar.from_ical(source.read_bytes())
    existing = {
        event_uid(entry.event, entry.path): entry.path.relative_to(args.root.resolve()).as_posix()
        for entries in load_source_events(args.root.resolve()).values()
        for entry in entries
    }
    results = []
    for event in calendar.walk("VEVENT"):
        uid = str(event.get("UID", "")).strip()
        title = str(event.get("SUMMARY", "")).strip()
        location = str(event.get("LOCATION", "")).strip()
        start = event.decoded("DTSTART") if event.get("DTSTART") else None
        end = event.decoded("DTEND") if event.get("DTEND") else None
        issues = []
        if not uid:
            issues.append("missing UID")
        if not start:
            issues.append("missing DTSTART")
        if " / " not in title:
            issues.append("SUMMARY needs bilingual --title")
        if location and " / " not in location:
            issues.append("LOCATION needs bilingual --location")
        if start and end:
            if isinstance(start, datetime) != isinstance(end, datetime):
                issues.append("DTSTART/DTEND types differ")
            elif end <= start:
                issues.append("DTEND must be later than DTSTART")
        try:
            status = event_status(event)
        except ValueError as exc:
            status = None
            issues.append(str(exc))
        results.append({
            "uid": uid, "title": title, "location": location,
            "start": format_dt(start) if start else None,
            "end": format_dt(end) if end else None,
            "status": status, "existingPath": existing.get(uid),
            "issues": issues,
            "alarms": len(event.walk("VALARM")),
        })
    output({
        "source": str(source), "eventCount": len(results),
        "singleEvent": len(results) == 1, "events": results,
    }, args.json)


def command_prepare(args: argparse.Namespace) -> None:
    from issue_intake import canonical_issue_url, prepare_issue, read_issue

    issue = read_issue(args.source, offline=args.issue_json)
    prepared = prepare_issue(issue)
    url = prepared["source"]["url"]
    matches = []
    for entries in load_source_events(args.root.resolve()).values():
        for entry in entries:
            source_url = str(entry.event.get("URL", "")).strip()
            try:
                source_url = canonical_issue_url(source_url)[0]
            except ValueError:
                pass
            if source_url == url or event_uid(entry.event, entry.path) == prepared["draft"]["uid"]:
                event = source_event_data(entry.path, entry.event, args.root.resolve())
                matches.append({
                    key: event[key] for key in ("uid", "title", "start", "end", "scope", "status", "path")
                })
    prepared["existingEvents"] = matches
    if len(matches) == 1:
        prepared["draft"]["uid"] = matches[0]["uid"]
    if args.full_source:
        prepared["body"] = issue["body"]
    if args.output:
        target = args.output.expanduser().resolve()
        root = args.root.resolve()
        if target.suffix.lower() != ".json" or any(target.is_relative_to(root / scope) for scope in ("public", "internal", ".git")):
            fail("--output must be a JSON file outside source directories and .git")
        if target.exists():
            fail(f"output already exists: {target}")
        with target.open("x", encoding="utf-8") as stream:
            json.dump(prepared, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        prepared = prepared | {
            "inputPath": str(target),
            "draft": {key: value for key, value in prepared["draft"].items() if key != "description"},
            "existingEvents": [
                {key: value for key, value in event.items() if key != "description"}
                for event in matches
            ],
        }
    output(prepared, args.json)


def merge_creation_input(args: argparse.Namespace) -> None:
    if args.input:
        from issue_intake import read_draft

        draft = read_draft(args.input)
        endings = ("end", "duration_minutes", "duration_days")
        if any(getattr(args, key) is not None for key in endings):
            draft = {key: value for key, value in draft.items() if key not in endings}
        for key, value in draft.items():
            if getattr(args, key) is None:
                setattr(args, key, value)
    for key in ("scope", "title", "start"):
        if not getattr(args, key):
            fail(f"provide --{key} or a resolved field in --input")
    if args.scope not in ("public", "internal"):
        fail("--scope must be public or internal")
    if sum(getattr(args, key) is not None for key in ("end", "duration_minutes", "duration_days")) != 1:
        fail("provide exactly one of --end, --duration-minutes or --days (including --input)")


def command_links(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    path, _, event = resolve_event(args.identifier, root)
    scope = path.relative_to(root).parts[0]
    status = event_status(event)
    start = event.decoded("DTSTART")
    paths = {
        "event": path.relative_to(root).as_posix(),
        "scope": f"{scope}.ics",
        "status": f"status/{status}/{scope}.ics",
        "month": f"status/{status}/{scope}/{start.year:04d}/{start.month:02d}.ics",
    }
    output({
        "uid": event_uid(event, path),
        "requiresKey": scope == "internal" or status == "tentative",
        "links": {
            name: {"https": f"{BASE_URL}/{relative}", "webcal": f"{BASE_URL}/{relative}".replace("https://", "webcal://", 1)}
            for name, relative in paths.items()
        },
    }, args.json)


def command_shift(args: argparse.Namespace) -> None:
    _, _, event = resolve_event(args.identifier, args.root.resolve())
    start = event.decoded("DTSTART")
    if any(event.get(key) for key in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
        fail("shift does not support recurring events; use explicit update fields")
    if not args.days and not args.minutes:
        fail("shift requires nonzero --days or --minutes")
    if not isinstance(start, datetime) and args.minutes:
        fail("all-day events can only be shifted by whole days")
    if not event.get("DTEND"):
        fail("shift requires an explicit DTEND")
    delta = timedelta(days=args.days, minutes=args.minutes)
    updated = argparse.Namespace(
        root=args.root, identifier=args.identifier, json=args.json, dry_run=args.dry_run,
        command="shift",
        start=format_dt(start + delta), end=format_dt(event.decoded("DTEND") + delta),
        title=None, location=None, status=None, alarm_minutes=None, clear_alarms=False,
        duration_minutes=None, duration_days=None,
        description=None, url=None,
    )
    command_update(updated)


def command_show(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    path, _, event = resolve_event(args.identifier, root)
    output(source_event_data(path, event, root), args.json)


def command_add(args: argparse.Namespace) -> None:
    merge_creation_input(args)
    require_bilingual(args.title, "--title")
    if args.location:
        require_bilingual(args.location, "--location")
    start = parse_start(args.start)
    end = schedule_end(args, start)
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
    event.add("STATUS", "TENTATIVE" if args.status == "tentative" else "CONFIRMED")
    if args.location:
        event.add("LOCATION", args.location)
    if args.description is not None:
        event.add("DESCRIPTION", args.description)
    if args.url is not None:
        event.add("URL", args.url)
    if args.alarm_minutes is not None:
        add_alarm(event, args.alarm_minutes)
    calendar.add_component(event)
    stem = validate_filename_stem(args.filename) if args.filename else slug_from_title(args.title)
    path = event_path(args.scope, start, stem, root)
    if path.exists():
        fail(f"target file already exists: {path.relative_to(root)}")
    write_calendar(path, calendar, dry_run=args.dry_run)
    output({"action": args.command, "path": path.relative_to(root).as_posix(), "uid": uid,
            "dryRun": args.dry_run, "event": source_event_data(path, event, root)}, args.json)


def command_import(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        fail(f"ICS file not found: {source}")
    calendar = Calendar.from_ical(source.read_bytes())
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    if len(events) != 1:
        fail(f"{source}: expected exactly one VEVENT, found {len(events)}")
    event = events[0]
    if args.status:
        event["STATUS"] = "TENTATIVE" if args.status == "tentative" else "CONFIRMED"
    event_status(event)
    uid = event_uid(event, source)
    existing_by_uid = {
        event_uid(entry.event, entry.path): entry.path
        for entries in load_source_events(root).values()
        for entry in entries
    }
    existing_path = existing_by_uid.get(uid)
    if existing_path and not args.replace:
        fail(
            f"UID already exists at {existing_path.relative_to(root)}; "
            "use --replace to update it"
        )

    title = args.title or str(event.get("SUMMARY", "")).strip()
    if not title:
        fail("imported event is missing SUMMARY; provide --title")
    require_bilingual(title, "--title or imported SUMMARY")
    if args.title:
        event["SUMMARY"] = args.title

    location = args.location
    if location is not None:
        require_bilingual(location, "--location")
        event["LOCATION"] = location
    elif event.get("LOCATION"):
        require_bilingual(str(event["LOCATION"]).strip(), "imported LOCATION or --location")

    for component in event.subcomponents:
        if component.name == "VALARM" and component.get("DESCRIPTION"):
            if " / " not in str(component["DESCRIPTION"]):
                component["DESCRIPTION"] = "提醒事项 / Reminder"
    if args.alarm_minutes is not None:
        remove_alarms(event)
        add_alarm(event, args.alarm_minutes)

    brand = "BETA" if args.scope == "public" else "BETA-SDC"
    calendar["X-WR-CALNAME"] = f"{brand} {SCOPE_LABELS[args.scope]}"
    if not any(component.name == "VTIMEZONE" for component in calendar.walk()):
        add_timezone(calendar)

    start = event.decoded("DTSTART")
    if existing_path:
        target = existing_path
        event["SEQUENCE"] = int(event.get("SEQUENCE", 0)) + 1
        stamp = datetime.now(timezone.utc)
        event["DTSTAMP"] = vDDDTypes(stamp)
        event["LAST-MODIFIED"] = vDDDTypes(stamp)
    else:
        stem = validate_filename_stem(args.filename) if args.filename else slug_from_title(title)
        target = event_path(args.scope, start, stem, root)
    if target.exists() and target != existing_path:
        fail(f"target file already exists: {target.relative_to(root)}")
    write_calendar(target, calendar, dry_run=args.dry_run)
    output(
        {
            "action": "replace" if existing_path else "import",
            "path": target.relative_to(root).as_posix(),
            "source": str(source),
            "uid": uid,
            "dryRun": args.dry_run,
            "event": source_event_data(target, event, root),
        },
        args.json,
    )


def command_update(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    path, calendar, event = resolve_event(args.identifier, root)
    old_start = event.decoded("DTSTART")
    changed = False
    if args.status:
        event["STATUS"] = "TENTATIVE" if args.status == "tentative" else "CONFIRMED"
        changed = True
    if args.title:
        require_bilingual(args.title, "--title")
        event["SUMMARY"] = args.title
        changed = True
    if args.location is not None:
        require_bilingual(args.location, "--location")
        event["LOCATION"] = args.location
        changed = True
    for argument, property_name in (("description", "DESCRIPTION"), ("url", "URL")):
        value = getattr(args, argument)
        if value is not None:
            event[property_name] = value
            changed = True
    if args.start:
        new_start = parse_start(args.start)
        event["DTSTART"] = vDDDTypes(new_start)
        new_end = schedule_end(args, new_start)
        if new_end is not None:
            event["DTEND"] = vDDDTypes(new_end)
        elif isinstance(old_start, datetime) != isinstance(new_start, datetime):
            fail("changing between all-day and timed events requires --end or a duration")
        elif event.get("DTEND"):
            event["DTEND"] = vDDDTypes(new_start + (event.decoded("DTEND") - old_start))
        changed = True
    else:
        new_end = schedule_end(args, old_start)
        if new_end is not None:
            event["DTEND"] = vDDDTypes(new_end)
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
    write_calendar(target, calendar, dry_run=args.dry_run)
    if target != path and not args.dry_run:
        path.unlink()
    output(
        {
            "action": "confirm" if args.command == "confirm" else "update",
            "old_path": path.relative_to(root).as_posix(),
            "path": target.relative_to(root).as_posix(),
            "uid": event_uid(event, target),
            "sequence": int(event["SEQUENCE"]),
            "dryRun": args.dry_run,
            "event": source_event_data(target, event, root),
        },
        args.json,
    )


def command_confirm(args: argparse.Namespace) -> None:
    _, _, event = resolve_event(args.identifier, args.root.resolve())
    if event_status(event) != "tentative":
        fail("confirm requires a tentative event; use update for an existing planned event")
    command_update(args)


def command_delete(args: argparse.Namespace) -> None:
    if not args.yes:
        fail("delete requires --yes")
    root = args.root.resolve()
    path, _, event = resolve_event(args.identifier, root)
    if not args.dry_run:
        path.unlink()
    output(
        {"action": "delete", "path": path.relative_to(root).as_posix(), "uid": event_uid(event, path),
         "dryRun": args.dry_run},
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
    build_site(root, root / "site", include_restricted=not args.public_only)
    output({"action": "build", "output": str((root / "site").relative_to(root))}, args.json)


def add_schedule_options(cli: argparse.ArgumentParser, *, required: bool = False) -> None:
    ending = cli.add_mutually_exclusive_group(required=required)
    ending.add_argument("--end", help="exclusive end date or end date/time")
    ending.add_argument("--duration-minutes", type=positive_integer, help="duration of a timed event")
    ending.add_argument("--days", dest="duration_days", type=positive_integer, help="duration of an all-day event")


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-j", "--json", action="store_true", help="emit machine-readable JSON")
    mutation = argparse.ArgumentParser(add_help=False, parents=[common])
    mutation.add_argument("--dry-run", action="store_true", help="validate and preview without writing files")
    filters = argparse.ArgumentParser(add_help=False, parents=[common])
    filters.add_argument("-s", "--scope", choices=("all", "public", "internal"), default="all")
    filters.add_argument("--from", dest="from_date", type=parse_date_argument)
    filters.add_argument("--to", dest="to_date", type=parse_date_argument)
    filters.add_argument("--status", choices=("all", "planned", "tentative"), default="all")
    filters.add_argument("--limit", type=positive_integer)
    filters.add_argument("--fields", help="comma-separated result fields (always emits JSON)")
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--version", action="version", version="calendar-cli 1.3")
    cli.add_argument("-v", "--verbose", action="store_true", help="enable verbose diagnostics")
    cli.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository root (default: current calendar repository)",
    )
    subparsers = cli.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", parents=[filters], help="list and filter source events")
    list_parser.add_argument("--query", help="case-insensitive keywords across title, location, UID and path")
    list_parser.set_defaults(handler=command_list)

    search_parser = subparsers.add_parser("search", parents=[filters], help="search event text")
    search_parser.add_argument("query", help="space-separated keywords; all must match")
    search_parser.set_defaults(handler=command_list)

    agenda_parser = subparsers.add_parser("agenda", parents=[filters], help="list events overlapping a date range")
    agenda_parser.add_argument("--days", type=positive_integer, default=7, help="days from --from (default: 7)")
    agenda_parser.add_argument("--query")
    agenda_parser.set_defaults(handler=command_list)

    inspect_parser = subparsers.add_parser("inspect", parents=[common], help="inspect an ICS or GitHub proposal")
    inspect_parser.add_argument("source")
    inspect_parser.set_defaults(issue_json=False, output=None, full_source=False)
    inspect_parser.set_defaults(handler=command_inspect)

    prepare_parser = subparsers.add_parser("prepare", parents=[common], help="extract a reviewable draft from a GitHub event issue")
    prepare_parser.add_argument("source", help="GitHub issue URL, or saved issue JSON with --issue-json")
    prepare_parser.add_argument("--issue-json", action="store_true", help="read saved gh issue JSON without network")
    prepare_parser.add_argument("-o", "--output", type=Path, help="save a new draft JSON for add/tentative --input")
    prepare_parser.add_argument("--full-source", action="store_true", help="include the complete issue body")
    prepare_parser.set_defaults(handler=command_prepare)

    links_parser = subparsers.add_parser("links", parents=[common], help="get event and subscription URLs")
    links_parser.add_argument("identifier", help="UID, filename, or repository-relative path")
    links_parser.set_defaults(handler=command_links)

    shift_parser = subparsers.add_parser("shift", parents=[mutation], help="shift an event while preserving its duration")
    shift_parser.add_argument("identifier")
    shift_parser.add_argument("--days", type=int, default=0)
    shift_parser.add_argument("--minutes", type=int, default=0)
    shift_parser.set_defaults(handler=command_shift)

    show_parser = subparsers.add_parser("show", parents=[common])
    show_parser.add_argument("identifier", help="UID, filename, or repository-relative path")
    show_parser.set_defaults(handler=command_show)

    for name, status in (("add", "planned"), ("tentative", "tentative")):
        add_parser = subparsers.add_parser(
            name, parents=[mutation],
            help="create a planned event" if name == "add" else "create a tentative event",
        )
        add_parser.add_argument("-s", "--scope", choices=("public", "internal"))
        if name == "add":
            add_parser.add_argument("--status", choices=tuple(STATUS_LABELS), default=status)
        else:
            add_parser.set_defaults(status=status)
        add_parser.add_argument("--input", help="prepared or flat draft JSON; '-' reads stdin; flags override draft fields")
        add_parser.add_argument("--start")
        add_schedule_options(add_parser)
        add_parser.add_argument("--title")
        add_parser.add_argument("--location")
        add_parser.add_argument("--description", help="event notes, including unresolved details")
        add_parser.add_argument("--url", help="source issue or event URL")
        add_parser.add_argument("--alarm-minutes", type=int)
        add_parser.add_argument("--uid")
        add_parser.add_argument("-f", "--filename", help="filename stem without .ics")
        add_parser.set_defaults(handler=command_add)

    import_parser = subparsers.add_parser("import", parents=[mutation])
    import_parser.add_argument("source", help="external .ics file to normalize and import")
    import_parser.add_argument("-s", "--scope", choices=("public", "internal"), required=True)
    import_parser.add_argument("--title", help="replace a non-bilingual imported SUMMARY")
    import_parser.add_argument("--location", help="replace a non-bilingual imported LOCATION")
    import_parser.add_argument("--alarm-minutes", type=int)
    import_parser.add_argument("-f", "--filename", help="filename stem without .ics")
    import_parser.add_argument("--replace", action="store_true")
    import_parser.add_argument("--status", choices=tuple(STATUS_LABELS))
    import_parser.set_defaults(handler=command_import)

    for name in ("update", "confirm"):
        update_parser = subparsers.add_parser(
            name, parents=[mutation],
            help="update event fields" if name == "update" else "convert a tentative event to planned",
        )
        update_parser.add_argument("identifier", help="UID, filename, or repository-relative path")
        update_parser.add_argument("--start")
        add_schedule_options(update_parser)
        update_parser.add_argument("--title")
        update_parser.add_argument("--location")
        update_parser.add_argument("--description", help="replace event notes")
        update_parser.add_argument("--url", help="replace source issue or event URL")
        if name == "update":
            update_parser.add_argument("--status", choices=tuple(STATUS_LABELS))
        else:
            update_parser.set_defaults(status="planned")
        alarm_group = update_parser.add_mutually_exclusive_group()
        alarm_group.add_argument("--alarm-minutes", type=int)
        alarm_group.add_argument("--clear-alarms", action="store_true")
        update_parser.set_defaults(handler=command_update if name == "update" else command_confirm)

    delete_parser = subparsers.add_parser("delete", parents=[mutation])
    delete_parser.add_argument("identifier")
    delete_parser.add_argument("-y", "--yes", action="store_true")
    delete_parser.set_defaults(handler=command_delete)

    validate_parser = subparsers.add_parser("validate", parents=[common])
    validate_parser.set_defaults(handler=command_validate)

    build_parser = subparsers.add_parser("build", parents=[common])
    build_parser.add_argument(
        "--public-only", action="store_true",
        help="exclude internal/tentative files from generated output",
    )
    build_parser.set_defaults(handler=command_build)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.verbose:
        print(f"calendar: command={args.command} root={args.root.resolve()}", file=sys.stderr)
    if getattr(args, "alarm_minutes", None) is not None and args.alarm_minutes < 0:
        fail("--alarm-minutes must be nonnegative")
    try:
        args.handler(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        fail(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
