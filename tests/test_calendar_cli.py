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

    def run_cli(
        self, *arguments: str, check: bool = True, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
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
            input=input_text,
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

    def issue_fixture(self, schedule: str, number: int = 999) -> Path:
        path = self.root / "issue.json"
        path.write_text(json.dumps({
            "title": "[event] 准备流程测试",
            "body": f"### 活动名称\n准备流程测试\n\n### 时间、地点和形式\n"
                    f"- 时间：{schedule}\n- 地点：校内，场地待确认\n",
            "url": f"https://github.com/BETA-SDC/event-proposal/issues/{number}",
            "comments": [],
        }, ensure_ascii=False), encoding="utf-8")
        return path

    def test_prepare_and_create_from_saved_draft(self) -> None:
        issue = self.issue_fixture("2026-12-15 19:00-21:00")
        target = self.root / "draft.json"
        before = self.source_snapshot()
        prepared = json.loads(self.run_cli(
            "prepare", str(issue), "--issue-json", "--output", str(target), "-j",
        ).stdout)
        self.assertEqual(self.source_snapshot(), before)
        self.assertEqual(prepared["draft"]["start"], "2026-12-15T19:00")
        self.assertNotIn("description", prepared["draft"])
        self.assertTrue(target.is_file())
        preview = json.loads(self.run_cli(
            "tentative", "--input", str(target), "-s", "public",
            "--title", "准备流程测试 / Prepared Event Test", "--dry-run", "-j",
        ).stdout)
        self.assertEqual(self.source_snapshot(), before)
        added = json.loads(self.run_cli(
            "tentative", "--input", str(target), "-s", "public",
            "--title", "准备流程测试 / Prepared Event Test", "-j",
        ).stdout)
        self.assertEqual(preview["uid"], added["uid"])
        self.assertEqual(added["event"]["sourceUrl"], "https://github.com/BETA-SDC/event-proposal/issues/999")
        self.assertIn("场地待确认", added["event"]["description"])
        self.assertEqual(added["event"]["status"], "tentative")
        self.assertEqual(added["event"]["end"], "2026-12-15T21:00:00+08:00")
        self.assertNotEqual(self.run_cli(
            "tentative", "--input", str(target), "-s", "public",
            "--title", "准备流程测试 / Prepared Event Test", check=False,
        ).returncode, 0)

    def test_prepare_requires_explicit_placeholder_for_unresolved_schedule(self) -> None:
        issue = self.issue_fixture("2026-11-11 下午，原消息未注明年份，按当前年份暂记")
        target = self.root / "draft.json"
        prepared = json.loads(self.run_cli("prepare", str(issue), "--issue-json", "-o", str(target), "-j").stdout)
        self.assertEqual(prepared["candidates"]["dates"], ["2026-11-11"])
        self.assertNotIn("start", prepared["draft"])
        self.assertIn("year", [item["field"] for item in prepared["unresolved"]])
        before = self.source_snapshot()
        result = self.run_cli(
            "tentative", "--input", str(target), "-s", "public",
            "--title", "测试 / Test", check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.source_snapshot(), before)
        preview = json.loads(self.run_cli(
            "tentative", "--input", str(target), "-s", "public", "--title", "测试 / Test",
            "--start", "2026-11-11", "--days", "1", "--dry-run", "-j",
        ).stdout)
        self.assertEqual(preview["event"]["end"], "2026-11-12")
        self.assertEqual(self.source_snapshot(), before)

    def test_prepare_recognizes_existing_source_url_and_legacy_uid(self) -> None:
        issue = self.issue_fixture("2026-11-11 下午", number=58)
        prepared = json.loads(self.run_cli("prepare", str(issue), "--issue-json", "-j").stdout)
        self.assertEqual(len(prepared["existingEvents"]), 1)
        self.assertEqual(prepared["draft"]["uid"], "event-proposal-58@beta-sdc.github.io")
        self.assertEqual(prepared["existingEvents"][0]["status"], "tentative")

    def test_creation_input_rejects_bad_fields_types_and_conflicts(self) -> None:
        target = self.root / "input.json"
        before = self.source_snapshot()
        for draft in (
            {"command": "delete"},
            {"duration_minutes": 0},
            {"alarm_minutes": -1},
            {"duration_days": True},
            {"scope": "other"},
            {"title": ["活动"]},
            {"start": "2026-12-20", "end": "2026-12-21", "duration_days": 1},
            {"schemaVersion": 99, "draft": {}},
        ):
            target.write_text(json.dumps(draft), encoding="utf-8")
            self.assertNotEqual(self.run_cli(
                "tentative", "--input", str(target), "-s", "public",
                "--title", "测试 / Test", check=False,
            ).returncode, 0)
            self.assertEqual(self.source_snapshot(), before)
        target.write_text(json.dumps({
            "scope": "public", "title": "测试 / Test", "start": "2026-12-20T19:00",
            "end": "2026-12-20T21:00",
        }), encoding="utf-8")
        preview = json.loads(self.run_cli(
            "add", "--input", str(target), "--duration-minutes", "30", "--dry-run", "-j",
        ).stdout)
        self.assertEqual(preview["event"]["end"], "2026-12-20T19:30:00+08:00")
        self.assertEqual(self.source_snapshot(), before)

    def test_creation_reads_prepared_json_from_stdin(self) -> None:
        issue = self.issue_fixture("2026-12-15 19:00-21:00")
        prepared = self.run_cli("prepare", str(issue), "--issue-json", "-j").stdout
        before = self.source_snapshot()
        preview = json.loads(self.run_cli(
            "tentative", "--input", "-", "-s", "public",
            "--title", "测试 / Test", "--dry-run", "-j", input_text=prepared,
        ).stdout)
        self.assertEqual(preview["event"]["start"], "2026-12-15T19:00:00+08:00")
        self.assertEqual(self.source_snapshot(), before)

    def test_prepare_does_not_overwrite_output_or_source_paths(self) -> None:
        issue = self.issue_fixture("2026-12-15 19:00-21:00")
        for target in (issue, self.root / "public" / "draft.json", self.root / ".git" / "draft.json"):
            self.assertNotEqual(self.run_cli(
                "prepare", str(issue), "--issue-json", "--output", str(target), check=False,
            ).returncode, 0)
        result = self.run_cli("prepare", str(issue), "--issue-json", "--full-source", "-j")
        self.assertIn("body", json.loads(result.stdout))

    def test_add_and_tentative_accept_durations(self) -> None:
        timed = json.loads(self.run_cli(
            "add", "-s", "public", "--start", "2026-12-31T23:30",
            "--duration-minutes", "90", "--title", "跨年活动 / New Year Event", "-j",
        ).stdout)
        self.assertEqual(timed["event"]["end"], "2027-01-01T01:00:00+08:00")
        self.assertEqual(timed["event"]["status"], "planned")
        all_day = json.loads(self.run_cli(
            "tentative", "-s", "internal", "--start", "2026-12-31",
            "--days", "2", "--title", "候选活动 / Candidate Event", "-j",
        ).stdout)
        self.assertEqual(all_day["action"], "tentative")
        self.assertEqual(all_day["event"]["end"], "2027-01-02")
        self.assertEqual(all_day["event"]["status"], "tentative")
        self.assertTrue(all_day["event"]["requiresKey"])
        self.run_cli("validate")

    def test_tentative_notes_and_source_survive_confirmation(self) -> None:
        notes = "仅确定下午，具体时段待确认。\n年份也需核实。 / Afternoon only; time and year to be confirmed."
        source_url = "https://github.com/BETA-SDC/event-proposal/issues/58"
        added = json.loads(self.run_cli(
            "tentative", "-s", "public", "--start", "2026-11-11", "--days", "1",
            "--title", "职业发展座谈会 / Career Development Roundtable",
            "--filename", "test-notes-and-source",
            "--description", notes, "--url", source_url, "-j",
        ).stdout)
        shown = json.loads(self.run_cli("show", added["uid"], "-j").stdout)
        self.assertEqual(shown["description"], notes)
        self.assertEqual(shown["sourceUrl"], source_url)
        confirmed = json.loads(self.run_cli(
            "confirm", added["uid"], "--start", "2026-11-11T14:00",
            "--duration-minutes", "120", "-j",
        ).stdout)
        self.assertEqual(confirmed["event"]["description"], notes)
        self.assertEqual(confirmed["event"]["sourceUrl"], source_url)
        updated = json.loads(self.run_cli(
            "update", added["uid"], "--description", "时间已确认 / Time confirmed",
            "--url", "https://example.com/event", "-j",
        ).stdout)
        self.assertEqual(updated["event"]["description"], "时间已确认 / Time confirmed")
        self.assertEqual(updated["event"]["sourceUrl"], "https://example.com/event")
        self.run_cli("validate")

    def test_add_rejects_missing_conflicting_or_wrong_duration(self) -> None:
        before = self.source_snapshot()
        for arguments in (
            (),
            ("--duration-minutes", "0"),
            ("--duration-minutes", "-10"),
            ("--duration-minutes", "30", "--end", "2026-12-01T21:00"),
            ("--days", "1"),
            ("--start", "2026-12-01", "--duration-minutes", "30"),
        ):
            result = self.run_cli(
                "add", "-s", "public", "--start", "2026-12-01T19:00",
                "--title", "测试 / Test", *arguments, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.source_snapshot(), before)

    def test_confirm_changes_schedule_and_status_in_one_revision(self) -> None:
        added = self.add_event("--status", "tentative", "--alarm-minutes", "10")
        path = self.root / added["path"]
        calendar = Calendar.from_ical(path.read_bytes())
        event = calendar.walk("VEVENT")[0]
        event.add("ATTACH", "https://example.com/agenda.pdf")
        event.add("X-TEST-PROPERTY", "preserve-me")
        path.write_bytes(calendar.to_ical())
        alarm = event.walk("VALARM")[0].to_ical()
        result = json.loads(self.run_cli(
            "confirm", added["uid"], "--start", "2027-01-05T18:30",
            "--duration-minutes", "90", "--title", "正式活动 / Scheduled Event",
            "--location", "云谷校区 / Yungu Campus H4-121", "-j",
        ).stdout)
        self.assertEqual(result["action"], "confirm")
        self.assertEqual(result["sequence"], 1)
        self.assertFalse(path.exists())
        self.assertTrue(result["path"].startswith("public/2027/01/2027-01-05-"))
        confirmed = Calendar.from_ical((self.root / result["path"]).read_bytes()).walk("VEVENT")[0]
        self.assertEqual(str(confirmed["UID"]), added["uid"])
        self.assertEqual(str(confirmed["STATUS"]), "CONFIRMED")
        self.assertEqual(str(confirmed["ATTACH"]), "https://example.com/agenda.pdf")
        self.assertEqual(str(confirmed["X-TEST-PROPERTY"]), "preserve-me")
        self.assertEqual(confirmed.walk("VALARM")[0].to_ical(), alarm)
        self.assertEqual(confirmed.decoded("CREATED"), event.decoded("CREATED"))
        self.assertGreaterEqual(confirmed.decoded("LAST-MODIFIED"), event.decoded("LAST-MODIFIED"))
        self.assertEqual(result["event"]["end"], "2027-01-05T20:00:00+08:00")
        self.assertFalse(result["event"]["requiresKey"])
        self.run_cli("build", "--public-only")
        self.assertTrue((self.root / "site" / result["path"]).is_file())
        before = self.source_snapshot()
        self.assertNotEqual(self.run_cli("confirm", added["uid"], check=False).returncode, 0)
        self.assertEqual(self.source_snapshot(), before)

    def test_confirm_preserves_scope_and_existing_times(self) -> None:
        added = self.add_event("-s", "internal", "--status", "tentative")
        result = json.loads(self.run_cli("confirm", added["uid"], "-j").stdout)
        self.assertEqual(result["event"]["scope"], "internal")
        self.assertTrue(result["event"]["requiresKey"])
        self.assertEqual(result["path"], added["path"])
        self.assertEqual(result["event"]["start"], added["event"]["start"])
        self.assertEqual(result["event"]["end"], added["event"]["end"])

    def test_confirm_dry_run_invalid_ranges_and_collisions_do_not_write(self) -> None:
        added = self.add_event("--status", "tentative")
        self.add_event("--start", "2027-01-01T19:00", "--end", "2027-01-01T21:00")
        before = self.source_snapshot()
        preview = json.loads(self.run_cli(
            "confirm", added["uid"], "--start", "2027-02-01T19:00",
            "--duration-minutes", "60", "--dry-run", "-j",
        ).stdout)
        self.assertTrue(preview["dryRun"])
        self.assertEqual(preview["event"]["status"], "planned")
        self.assertEqual(self.source_snapshot(), before)
        for arguments in (
            ("--start", "2027-01-01T19:00"),
            ("--end", "2026-12-01T18:00"),
            ("--title", "单语标题"),
            ("--days", "1"),
        ):
            self.assertNotEqual(self.run_cli("confirm", added["uid"], *arguments, check=False).returncode, 0)
            self.assertEqual(self.source_snapshot(), before)

    def test_confirm_all_day_can_become_timed_and_update_duration(self) -> None:
        added = json.loads(self.run_cli(
            "tentative", "-s", "public", "--start", "2026-12-01", "--days", "1",
            "--title", "活动 / Event", "-j",
        ).stdout)
        result = json.loads(self.run_cli(
            "confirm", added["uid"], "--start", "2026-12-02T19:00", "--duration-minutes", "120", "-j",
        ).stdout)
        self.assertEqual(result["event"]["end"], "2026-12-02T21:00:00+08:00")
        updated = json.loads(self.run_cli("update", added["uid"], "--duration-minutes", "30", "-j").stdout)
        self.assertEqual(updated["event"]["end"], "2026-12-02T19:30:00+08:00")

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
