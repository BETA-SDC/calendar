#!/usr/bin/env python3
"""Validate source events and build aggregate calendar feeds and the Pages site."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from icalendar import Calendar


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ROOT_CATEGORIES = ("public", "internal")
SCOPE_LABELS = {"public": "公开活动", "internal": "内部事件"}
REFRESH_INTERVAL = "PT1H"
BASE_URL = "https://beta-sdc.github.io/calendar"
WEB_ASSETS = ("index.html", "styles.css", "app.js")


@dataclass(frozen=True)
class SourceEvent:
    path: Path
    scope: str
    year: str
    month: str
    event: Any
    timezones: tuple[Any, ...]


def read_event(path: Path) -> tuple[Calendar, Any]:
    calendar = Calendar.from_ical(path.read_bytes())
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    if len(events) != 1:
        raise ValueError(f"{path}: expected exactly one VEVENT, found {len(events)}")
    return calendar, events[0]


def event_uid(event: Any, path: Path) -> str:
    uid = str(event.get("UID", "")).strip()
    if not uid:
        raise ValueError(f"{path}: event is missing UID")
    return uid


def validate_event_period(event: Any, path: Path, year: str, month: str) -> None:
    start = event.decoded("DTSTART")
    event_period = f"{start.year:04d}-{start.month:02d}"
    directory_period = f"{year}-{month}"
    if event_period != directory_period:
        raise ValueError(
            f"{path}: DTSTART is in {event_period}, expected directory {directory_period}"
        )


def load_source_events(source_root: Path) -> dict[str, list[SourceEvent]]:
    by_scope: dict[str, list[SourceEvent]] = {scope: [] for scope in ROOT_CATEGORIES}
    uid_paths: dict[str, Path] = {}

    for scope in ROOT_CATEGORIES:
        scope_root = source_root / scope
        if not scope_root.exists():
            continue
        for path in sorted(scope_root.rglob("*.ics")):
            relative = path.relative_to(scope_root)
            if len(relative.parts) != 3:
                raise ValueError(f"{path}: expected {scope}/YYYY/MM/event.ics")
            year, month, _ = relative.parts
            if not (year.isdigit() and len(year) == 4 and month.isdigit() and len(month) == 2):
                raise ValueError(f"{path}: expected numeric YYYY/MM directories")
            if not 1 <= int(month) <= 12:
                raise ValueError(f"{path}: month must be between 01 and 12")

            calendar, event = read_event(path)
            validate_event_period(event, path, year, month)
            uid = event_uid(event, path)
            if uid in uid_paths:
                raise ValueError(f"duplicate UID {uid}: {uid_paths[uid]} and {path}")
            uid_paths[uid] = path

            timezones = tuple(
                component for component in calendar.walk() if component.name == "VTIMEZONE"
            )
            by_scope[scope].append(
                SourceEvent(
                    path=path,
                    scope=scope,
                    year=year,
                    month=month,
                    event=event,
                    timezones=timezones,
                )
            )

    return by_scope


def build_calendar(name: str, entries: Iterable[SourceEvent]) -> Calendar:
    entries = list(entries)
    calendar = Calendar()
    calendar.add("VERSION", "2.0")
    calendar.add("PRODID", "-//BETA-SDC//Calendar Feeds//EN")
    calendar.add("CALSCALE", "GREGORIAN")
    calendar.add("X-WR-CALNAME", name)
    calendar.add("X-WR-TIMEZONE", "Asia/Shanghai")
    calendar.add("REFRESH-INTERVAL", REFRESH_INTERVAL, parameters={"VALUE": "DURATION"})
    calendar.add("X-PUBLISHED-TTL", REFRESH_INTERVAL)

    seen_timezones: set[bytes] = set()
    for entry in entries:
        for timezone in entry.timezones:
            serialized = timezone.to_ical()
            if serialized not in seen_timezones:
                calendar.add_component(timezone)
                seen_timezones.add(serialized)

    for entry in sorted(entries, key=lambda item: str(item.event.get("DTSTART", ""))):
        calendar.add_component(entry.event)
    return calendar


def write_feed(path: Path, name: str, entries: Iterable[SourceEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_calendar(name, entries).to_ical())


def register_feed(
    output: Path,
    feeds: dict[str, dict[str, str]],
    *,
    key: str,
    title: str,
    relative_path: Path,
    calendar_name: str,
    entries: Iterable[SourceEvent],
) -> None:
    path = output / relative_path
    write_feed(path, calendar_name, entries)
    url = f"{BASE_URL}/{relative_path.as_posix()}"
    feeds[key] = {
        "title": title,
        "https": url,
        "webcal": url.replace("https://", "webcal://", 1),
    }


def group_by_year(entries: Iterable[SourceEvent]) -> dict[str, list[SourceEvent]]:
    grouped: dict[str, list[SourceEvent]] = defaultdict(list)
    for entry in entries:
        grouped[entry.year].append(entry)
    return grouped


def group_by_month(entries: Iterable[SourceEvent]) -> dict[tuple[str, str], list[SourceEvent]]:
    grouped: dict[tuple[str, str], list[SourceEvent]] = defaultdict(list)
    for entry in entries:
        grouped[(entry.year, entry.month)].append(entry)
    return grouped


def copy_web_assets(output: Path, web_root: Path) -> None:
    for filename in WEB_ASSETS:
        source = web_root / filename
        if not source.is_file():
            raise FileNotFoundError(f"missing web asset: {source}")
        shutil.copy2(source, output / filename)


def copy_source_events(
    output: Path,
    entries: Iterable[SourceEvent],
    source_root: Path,
) -> None:
    for entry in entries:
        relative_path = entry.path.relative_to(source_root)
        destination = output / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.path, destination)


def write_calendar_data(
    output: Path,
    feeds: dict[str, dict[str, str]],
    periods: Iterable[tuple[str, str]],
) -> None:
    data = {
        "feeds": feeds,
        "periods": [
            {"year": year, "month": month, "label": f"{year}-{month}"}
            for year, month in sorted(periods)
        ],
    }
    (output / "calendar-data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_site(source_root: Path, output: Path, web_root: Path | None = None) -> None:
    web_root = web_root or source_root / "web"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    by_scope = load_source_events(source_root)
    feeds: dict[str, dict[str, str]] = {}
    all_entries = [entry for scope in ROOT_CATEGORIES for entry in by_scope[scope]]

    for scope in ROOT_CATEGORIES:
        entries = by_scope[scope]
        if not entries:
            continue
        label = SCOPE_LABELS[scope]
        top_level_name = "BETA" if scope == "public" else f"BETA-SDC {scope}"
        register_feed(
            output,
            feeds,
            key=scope,
            title=f"{label}（全部）",
            relative_path=Path(f"{scope}.ics"),
            calendar_name=top_level_name,
            entries=entries,
        )

        for year, year_entries in sorted(group_by_year(entries).items()):
            register_feed(
                output,
                feeds,
                key=f"{scope}:{year}",
                title=f"{label} {year}",
                relative_path=Path(scope) / f"{year}.ics",
                calendar_name=f"BETA-SDC {scope} {year}",
                entries=year_entries,
            )
        for (year, month), month_entries in sorted(group_by_month(entries).items()):
            register_feed(
                output,
                feeds,
                key=f"{scope}:{year}-{month}",
                title=f"{label} {year}-{month}",
                relative_path=Path(scope) / year / f"{month}.ics",
                calendar_name=f"BETA-SDC {scope} {year}-{month}",
                entries=month_entries,
            )

    if all_entries:
        register_feed(
            output,
            feeds,
            key="all",
            title="全部活动",
            relative_path=Path("BETA-SDC.ics"),
            calendar_name="BETA-SDC",
            entries=all_entries,
        )
        for year, year_entries in sorted(group_by_year(all_entries).items()):
            register_feed(
                output,
                feeds,
                key=f"all:{year}",
                title=f"全部活动 {year}",
                relative_path=Path(f"{year}.ics"),
                calendar_name=f"BETA-SDC {year}",
                entries=year_entries,
            )
        for (year, month), month_entries in sorted(group_by_month(all_entries).items()):
            register_feed(
                output,
                feeds,
                key=f"all:{year}-{month}",
                title=f"全部活动 {year}-{month}",
                relative_path=Path(year) / f"{month}.ics",
                calendar_name=f"BETA-SDC {year}-{month}",
                entries=month_entries,
            )

    copy_web_assets(output, web_root)
    copy_source_events(output, all_entries, source_root)
    write_calendar_data(output, feeds, group_by_month(all_entries))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("site"))
    args = parser.parse_args()
    build_site(REPOSITORY_ROOT, args.output)


if __name__ == "__main__":
    main()
