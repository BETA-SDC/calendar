from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CLI = REPOSITORY_ROOT / "scripts" / "calendar_cli.py"


class CalendarCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        for directory in ("public", "internal", "web"):
            shutil.copytree(REPOSITORY_ROOT / directory, self.root / directory)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_cli(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                "--root",
                str(self.root),
                *arguments,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def add_event(self, *arguments: str) -> dict:
        return json.loads(self.run_cli(
            "add", "-s", "public",
            "--start", "2026-12-01T19:00", "--end", "2026-12-01T21:00",
            "--title", "测试活动 / Test Event", *arguments, "-j",
        ).stdout)

    def source_snapshot(self) -> dict:
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for scope in ("public", "internal")
            for path in (self.root / scope).rglob("*.ics")
        }

    def test_search_filters_projection_and_limits(self) -> None:
        added = self.add_event("--location", "测试室 / Test Room")
        found = json.loads(self.run_cli(
            "search", "TEST room", "--from", "2026-12-01", "--to", "2026-12-01",
            "--fields", "uid,title", "--limit", "1",
        ).stdout)
        self.assertEqual(found, [{"uid": added["uid"], "title": "测试活动 / Test Event"}])
        self.assertEqual(json.loads(self.run_cli("search", "不存在的标题", "-j").stdout), [])
        for arguments in (
            ("--fields", "unknown"), ("--limit", "0"),
            ("--from", "bad-date"), ("--from", "2026-12-02", "--to", "2026-12-01"),
        ):
            self.assertNotEqual(self.run_cli("list", *arguments, check=False).returncode, 0)

    def test_agenda_includes_ongoing_events_and_excludes_end_boundary(self) -> None:
        overnight = self.add_event(
            "--start", "2026-11-30T23:00", "--end", "2026-12-01T01:00",
            "--filename", "overnight",
        )
        ended = self.add_event(
            "--start", "2026-11-30T21:00", "--end", "2026-12-01T00:00",
            "--filename", "ended",
        )
        all_day = self.add_event(
            "--start", "2026-11-29", "--end", "2026-12-02", "--filename", "all-day",
        )
        future = self.add_event(
            "--start", "2026-12-02T00:00", "--end", "2026-12-02T01:00",
            "--filename", "future",
        )
        found = json.loads(self.run_cli("agenda", "--from", "2026-12-01", "--days", "1", "-j").stdout)
        self.assertCountEqual([item["uid"] for item in found], [overnight["uid"], all_day["uid"]])
        self.assertNotIn(ended["uid"], [item["uid"] for item in found])
        self.assertNotIn(future["uid"], [item["uid"] for item in found])
        utc_event = self.add_event(
            "--start", "2026-11-30T17:00:00+00:00", "--end", "2026-11-30T18:00:00+00:00",
            "--filename", "utc-event",
        )
        found = json.loads(self.run_cli("agenda", "--from", "2026-12-01", "--to", "2026-12-01", "-j").stdout)
        self.assertIn(utc_event["uid"], [item["uid"] for item in found])

    def test_inspect_reports_duplicate_uid_and_translation_needs_without_writes(self) -> None:
        added = self.add_event()
        calendar = Calendar.from_ical((self.root / added["path"]).read_bytes())
        event = calendar.walk("VEVENT")[0]
        event["SUMMARY"] = "单语标题"
        event["LOCATION"] = "H4-121"
        source = self.root / "incoming.ics"
        source.write_bytes(calendar.to_ical())
        before = self.source_snapshot()
        result = json.loads(self.run_cli("inspect", str(source), "-j").stdout)
        self.assertTrue(result["singleEvent"])
        self.assertEqual(result["events"][0]["existingPath"], added["path"])
        self.assertEqual(len(result["events"][0]["issues"]), 2)
        self.assertEqual(self.source_snapshot(), before)
        calendar.add_component(Event())
        source.write_bytes(calendar.to_ical())
        result = json.loads(self.run_cli("inspect", str(source), "-j").stdout)
        self.assertFalse(result["singleEvent"])
        self.assertIn("missing UID", result["events"][1]["issues"])
        self.assertIn("missing DTSTART", result["events"][1]["issues"])

    def test_links_match_generated_feeds(self) -> None:
        added = self.add_event("--status", "tentative")
        result = json.loads(self.run_cli("links", added["uid"], "-j").stdout)
        self.assertTrue(result["requiresKey"])
        self.run_cli("build")
        for links in result["links"].values():
            relative = links["https"].split("/calendar/", 1)[1]
            self.assertTrue((self.root / "site" / relative).is_file())
            self.assertEqual(links["webcal"], links["https"].replace("https://", "webcal://", 1))

    def test_dry_run_mutations_leave_sources_unchanged(self) -> None:
        before = self.source_snapshot()
        preview = self.add_event("--dry-run")
        self.assertTrue(preview["dryRun"])
        self.assertEqual(self.source_snapshot(), before)
        added = self.add_event()
        before = self.source_snapshot()
        for command in (
            ("update", added["uid"], "--start", "2027-01-01T19:00"),
            ("shift", added["uid"], "--days", "31"),
            ("delete", added["uid"], "--yes"),
            ("import", str(self.root / added["path"]), "-s", "public", "--replace"),
        ):
            result = json.loads(self.run_cli(*command, "--dry-run", "-j").stdout)
            self.assertTrue(result["dryRun"])
            self.assertEqual(self.source_snapshot(), before)
        source = self.root / "new.ics"
        calendar = Calendar.from_ical((self.root / added["path"]).read_bytes())
        calendar.walk("VEVENT")[0]["UID"] = "NEW-IMPORT-UID"
        source.write_bytes(calendar.to_ical())
        self.run_cli("import", str(source), "-s", "internal", "--dry-run")
        self.assertEqual(self.source_snapshot(), before)

    def test_shift_preserves_duration_uid_alarms_and_second_precision(self) -> None:
        added = self.add_event(
            "--start", "2026-12-31T23:00:30", "--end", "2027-01-01T01:00:30",
            "--alarm-minutes", "10",
        )
        before = Calendar.from_ical((self.root / added["path"]).read_bytes()).walk("VEVENT")[0]
        result = json.loads(self.run_cli("shift", added["uid"], "--days", "1", "--minutes", "-30", "-j").stdout)
        self.assertFalse((self.root / added["path"]).exists())
        after = Calendar.from_ical((self.root / result["path"]).read_bytes()).walk("VEVENT")[0]
        self.assertEqual(str(after["UID"]), added["uid"])
        self.assertEqual(after.decoded("DTSTART"), before.decoded("DTSTART") + timedelta(days=1, minutes=-30))
        self.assertEqual(after.decoded("DTEND") - after.decoded("DTSTART"), timedelta(hours=2))
        self.assertEqual(after.walk("VALARM")[0].to_ical(), before.walk("VALARM")[0].to_ical())
        self.assertEqual(int(after["SEQUENCE"]), 1)

    def test_shift_all_day_and_reject_recurring_event(self) -> None:
        added = self.add_event("--start", "2026-12-01", "--end", "2026-12-03")
        self.assertNotEqual(self.run_cli("shift", added["uid"], "--minutes", "1", check=False).returncode, 0)
        shifted = json.loads(self.run_cli("shift", added["uid"], "--days", "-1", "-j").stdout)
        self.assertEqual(shifted["event"]["start"], "2026-11-30")
        self.assertEqual(shifted["event"]["end"], "2026-12-02")
        path = self.root / shifted["path"]
        calendar = Calendar.from_ical(path.read_bytes())
        calendar.walk("VEVENT")[0].add("RRULE", {"FREQ": "WEEKLY"})
        path.write_bytes(calendar.to_ical())
        before = path.read_bytes()
        self.assertNotEqual(self.run_cli("shift", added["uid"], "--days", "1", check=False).returncode, 0)
        self.assertEqual(path.read_bytes(), before)

    def test_update_start_preserves_duration_and_rejects_invalid_range(self) -> None:
        added = self.add_event()
        result = json.loads(self.run_cli("update", added["uid"], "--start", "2026-12-02T20:00", "-j").stdout)
        self.assertEqual(result["event"]["end"], "2026-12-02T22:00:00+08:00")
        before = self.source_snapshot()
        for command in (
            ("update", added["uid"], "--end", "2026-12-02T19:00"),
            ("update", added["uid"], "--start", "2026-12-03"),
            ("add", "-s", "public", "--title", "测试 / Test", "--start", "2026-12-03", "--end", "2026-12-02"),
        ):
            result = self.run_cli(*command, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(self.source_snapshot(), before)

    def test_gnu_options_and_json_list(self) -> None:
        result = self.run_cli("list", "-s", "internal", "-j")
        events = json.loads(result.stdout)
        self.assertEqual(len(events), 5)
        self.assertTrue(all(event["scope"] == "internal" for event in events))

    def test_add_update_and_delete(self) -> None:
        added = self.run_cli(
            "add",
            "-s",
            "internal",
            "--start",
            "2026-10-15T21:30",
            "--end",
            "2026-10-15T22:30",
            "--title",
            "骨干会议 / SDC Core Team Meeting",
            "--location",
            "云谷校区 / Yungu Campus H4-103",
            "--alarm-minutes",
            "10",
            "-j",
        )
        added_data = json.loads(added.stdout)
        path = self.root / added_data["path"]
        self.assertTrue(path.is_file())

        updated = self.run_cli(
            "update",
            added_data["uid"],
            "--start",
            "2026-11-15T21:30",
            "--end",
            "2026-11-15T22:30",
            "-j",
        )
        updated_data = json.loads(updated.stdout)
        self.assertFalse(path.exists())
        moved_path = self.root / updated_data["path"]
        self.assertTrue(moved_path.is_file())
        self.assertEqual(updated_data["sequence"], 1)

        blocked_delete = self.run_cli("delete", updated_data["uid"], check=False)
        self.assertNotEqual(blocked_delete.returncode, 0)
        self.assertIn("--yes", blocked_delete.stderr)

        self.run_cli("delete", updated_data["uid"], "--yes", "-j")
        self.assertFalse(moved_path.exists())

    def test_validate_and_build(self) -> None:
        validated = json.loads(self.run_cli("validate", "-j").stdout)
        self.assertTrue(validated["valid"])
        built = json.loads(self.run_cli("build", "-j").stdout)
        self.assertEqual(built["output"], "site")
        self.assertTrue((self.root / "site" / "internal.ics").is_file())
        self.run_cli("build", "--public-only", "-j")
        self.assertFalse((self.root / "site" / "internal.ics").is_file())

    def test_tentative_event_can_be_planned_without_changing_identity(self) -> None:
        existing_tentative = json.loads(
            self.run_cli("list", "--status", "tentative", "-j").stdout
        )
        added = json.loads(self.run_cli(
            "add", "-s", "public", "--status", "tentative",
            "--start", "2026-10-20T20:00", "--end", "2026-10-20T21:00",
            "--title", "待定讲座 / Tentative Talk", "-j",
        ).stdout)
        shown = json.loads(self.run_cli("show", added["uid"], "-j").stdout)
        self.assertEqual(shown["status"], "tentative")
        self.assertTrue(shown["requiresKey"])
        tentative = json.loads(self.run_cli("list", "--status", "tentative", "-j").stdout)
        self.assertCountEqual(
            [event["uid"] for event in tentative],
            [event["uid"] for event in existing_tentative] + [added["uid"]],
        )
        self.run_cli("build", "--public-only")
        self.assertFalse((self.root / "site" / added["path"]).exists())
        self.run_cli("update", added["uid"], "--status", "planned")
        shown = json.loads(self.run_cli("show", added["uid"], "-j").stdout)
        self.assertEqual(shown["status"], "planned")
        self.assertFalse(shown["requiresKey"])
        event = Calendar.from_ical((self.root / added["path"]).read_bytes()).walk("VEVENT")[0]
        self.assertEqual(str(event["STATUS"]), "CONFIRMED")
        self.assertEqual(int(event["SEQUENCE"]), 1)
        self.assertEqual(str(event["UID"]), added["uid"])
        self.run_cli("build", "--public-only")
        self.assertTrue((self.root / "site" / added["path"]).exists())

    def test_import_preserves_or_overrides_tentative_status(self) -> None:
        added = json.loads(self.run_cli(
            "add", "-s", "internal", "--status", "tentative",
            "--start", "2026-10-20", "--end", "2026-10-21",
            "--title", "待定会议 / Tentative Meeting", "-j",
        ).stdout)
        source = self.root / "external.ics"
        shutil.copy2(self.root / added["path"], source)
        self.run_cli("delete", added["uid"], "--yes")
        self.run_cli("import", str(source), "-s", "internal")
        shown = json.loads(self.run_cli("show", added["uid"], "-j").stdout)
        self.assertEqual(shown["status"], "tentative")
        self.run_cli("import", str(source), "-s", "internal", "--replace", "--status", "planned")
        shown = json.loads(self.run_cli("show", added["uid"], "-j").stdout)
        self.assertEqual(shown["status"], "planned")
        self.assertTrue(shown["requiresKey"])

    def test_import_preserves_event_properties(self) -> None:
        source = self.root / "incoming.ics"
        calendar = Calendar()
        calendar.add("VERSION", "2.0")
        event = Event()
        event.add("UID", "IMPORT-TEST-UID")
        event.add("SUMMARY", "骨干会议")
        event.add("DTSTART", datetime(2026, 10, 20, 21, 30, tzinfo=ZoneInfo("Asia/Shanghai")))
        event.add("DTEND", datetime(2026, 10, 20, 22, 30, tzinfo=ZoneInfo("Asia/Shanghai")))
        event.add("LOCATION", "H4-103")
        event.add("X-TEST-PROPERTY", "preserve-me")
        alarm = Alarm()
        alarm.add("ACTION", "DISPLAY")
        alarm.add("DESCRIPTION", "提醒事项")
        alarm.add("TRIGGER", timedelta(minutes=-10))
        event.add_component(alarm)
        calendar.add_component(event)
        source.write_bytes(calendar.to_ical())

        result = self.run_cli(
            "import",
            str(source),
            "-s",
            "internal",
            "--title",
            "骨干会议 / SDC Core Team Meeting",
            "--location",
            "云谷校区 / Yungu Campus H4-103",
            "-j",
        )
        imported = json.loads(result.stdout)
        target = self.root / imported["path"]
        parsed = Calendar.from_ical(target.read_bytes())
        imported_event = parsed.walk("VEVENT")[0]
        self.assertEqual(str(imported_event["UID"]), "IMPORT-TEST-UID")
        self.assertEqual(str(imported_event["X-TEST-PROPERTY"]), "preserve-me")
        self.assertEqual(str(imported_event["SUMMARY"]), "骨干会议 / SDC Core Team Meeting")
        self.assertEqual(str(imported_event["LOCATION"]), "云谷校区 / Yungu Campus H4-103")
        self.assertEqual(
            str(imported_event.walk("VALARM")[0]["DESCRIPTION"]),
            "提醒事项 / Reminder",
        )


if __name__ == "__main__":
    unittest.main()
