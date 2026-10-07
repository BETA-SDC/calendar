from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from build_feeds import build_site, load_source_events  # noqa: E402


class BuildFeedsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output = Path(self.temporary_directory.name) / "site"
        build_site(REPOSITORY_ROOT, self.output)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def read_calendar(self, relative_path: str) -> Calendar:
        return Calendar.from_ical((self.output / relative_path).read_bytes())

    def write_source_event(
        self,
        root: Path,
        relative_path: str,
        uid: str,
        start: datetime,
    ) -> None:
        calendar = Calendar()
        calendar.add("VERSION", "2.0")
        event = Event()
        event.add("UID", uid)
        event.add("SUMMARY", "Test event")
        event.add("DTSTART", start)
        event.add("DTEND", start)
        calendar.add_component(event)
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(calendar.to_ical())

    def test_source_events_have_unique_uids(self) -> None:
        by_scope = load_source_events(REPOSITORY_ROOT)
        entries = [entry for scope_entries in by_scope.values() for entry in scope_entries]
        uids = [str(entry.event.get("UID")) for entry in entries]
        self.assertEqual(len(uids), len(set(uids)))
        self.assertTrue(by_scope["public"])
        self.assertTrue(by_scope["internal"])

    def test_top_level_feed_metadata(self) -> None:
        public = self.read_calendar("public.ics")
        internal = self.read_calendar("internal.ics")
        self.assertEqual(
            str(public.get("X-WR-CALNAME")), "BETA 公开活动 / Public Events"
        )
        self.assertEqual(
            str(internal.get("X-WR-CALNAME")),
            "BETA-SDC 内部事件 / Internal Events",
        )
        for calendar in (public, internal):
            self.assertEqual(str(calendar.get("REFRESH-INTERVAL")), "PT1H")
            self.assertEqual(str(calendar.get("X-PUBLISHED-TTL")), "PT1H")

    def test_web_assets_and_data_are_generated(self) -> None:
        for filename in (
            "index.html",
            "events.html",
            "styles.css",
            "app.js",
            "events.js",
            "calendar-data.json",
            "events-data.json",
        ):
            self.assertTrue((self.output / filename).is_file(), filename)

        data = json.loads((self.output / "calendar-data.json").read_text(encoding="utf-8"))
        self.assertEqual(
            data["feeds"]["public"]["title"],
            "公开活动 / Public Events（全部 / All）",
        )
        self.assertEqual(
            data["feeds"]["public"]["webcal"],
            "webcal://beta-sdc.github.io/calendar/public.ics",
        )
        self.assertIn(
            {"year": "2026", "month": "10", "label": "2026-10"},
            data["periods"],
        )
        self.assertIn(
            'href="events.html"',
            (self.output / "index.html").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'href="index.html"',
            (self.output / "events.html").read_text(encoding="utf-8"),
        )
        event_script = (self.output / "events.js").read_text(encoding="utf-8")
        for label in ("下载 ICS", "打开订阅链接", "复制订阅链接"):
            self.assertIn(label, event_script)

    def test_individual_event_data_is_sorted_and_linked(self) -> None:
        data = json.loads((self.output / "events-data.json").read_text(encoding="utf-8"))
        events = data["events"]
        self.assertEqual(
            [event["start"] for event in events],
            sorted(event["start"] for event in events),
        )
        target = next(
            event
            for event in events
            if event["uid"] == "13B7ECF2-A67B-4388-A043-1FCE2E6D578A"
        )
        self.assertEqual(target["scopeLabel"], "公开活动 / Public Events")
        self.assertEqual(target["date"], "2026-09-29")
        self.assertEqual(target["location"], "云谷校区 / Yungu Campus H4-103")
        self.assertEqual(
            target["url"],
            "https://beta-sdc.github.io/calendar/public/2026/09/"
            "2026-09-29-beta-meet-09-tibet-biodiversity-field-survey.ics",
        )

    def test_individual_event_files_are_published(self) -> None:
        relative_path = Path(
            "public/2026/09/"
            "2026-09-29-beta-meet-09-tibet-biodiversity-field-survey.ics"
        )
        self.assertEqual(
            (self.output / relative_path).read_bytes(),
            (REPOSITORY_ROOT / relative_path).read_bytes(),
        )

    def test_self_study_camp_is_published_as_public_all_day_event(self) -> None:
        uid = "AED38EB5-FB63-467D-9FBC-79AACF61A4AE"
        relative_path = Path(
            "public/2026/10/2026-10-08-self-study-check-in-camp.ics"
        )
        data = json.loads((self.output / "events-data.json").read_text(encoding="utf-8"))
        target = next(event for event in data["events"] if event["uid"] == uid)
        self.assertEqual(target["title"], "自习打卡营 / Self-Study Check-in Camp")
        self.assertEqual(target["scope"], "public")
        self.assertTrue(target["allDay"])
        self.assertEqual(target["start"], "2026-10-08")
        self.assertEqual(target["end"], "2026-11-09")
        self.assertEqual(
            target["location"],
            "西湖大学云谷校区 E14 图书馆（杭州市墩余路600号） / "
            "E14 Library, Yungu Campus, Westlake University, 600 Dunyu Road, Hangzhou",
        )
        self.assertEqual(
            (self.output / relative_path).read_bytes(),
            (REPOSITORY_ROOT / relative_path).read_bytes(),
        )
        source = Calendar.from_ical((REPOSITORY_ROOT / relative_path).read_bytes())
        source_event = source.walk("VEVENT")[0]
        for feed in ("public.ics", "public/2026/10.ics", "BETA-SDC.ics"):
            with self.subTest(feed=feed):
                event = next(
                    event
                    for event in self.read_calendar(feed).walk("VEVENT")
                    if str(event.get("UID")) == uid
                )
                self.assertEqual(event.to_ical(), source_event.to_ical())

    def assert_bilingual(self, value: str) -> None:
        self.assertIn(" / ", value)
        chinese, english = value.split(" / ", 1)
        self.assertRegex(chinese, r"[\u4e00-\u9fff]")
        self.assertRegex(english, r"[A-Za-z]")

    def test_all_published_calendars_are_bilingual(self) -> None:
        for path in self.output.rglob("*.ics"):
            with self.subTest(path=path.relative_to(self.output)):
                calendar = Calendar.from_ical(path.read_bytes())
                self.assert_bilingual(str(calendar.get("X-WR-CALNAME", "")))
                for event in calendar.walk("VEVENT"):
                    self.assert_bilingual(str(event.get("SUMMARY", "")))
                    if event.get("LOCATION"):
                        self.assert_bilingual(str(event["LOCATION"]))
                    if event.get("X-APPLE-STRUCTURED-LOCATION"):
                        self.assert_bilingual(
                            str(event["X-APPLE-STRUCTURED-LOCATION"].params["X-TITLE"])
                        )
                    for component in event.walk():
                        if component.get("DESCRIPTION"):
                            self.assert_bilingual(str(component["DESCRIPTION"]))

        data = json.loads((self.output / "calendar-data.json").read_text(encoding="utf-8"))
        for feed in data["feeds"].values():
            self.assert_bilingual(feed["title"])
        data = json.loads((self.output / "events-data.json").read_text(encoding="utf-8"))
        for event in data["events"]:
            self.assert_bilingual(event["title"])
            self.assert_bilingual(event["scopeLabel"])
            if event["location"]:
                self.assert_bilingual(event["location"])

    def test_source_ics_lines_use_crlf_and_fit_byte_limit(self) -> None:
        for scope in ("public", "internal"):
            for path in (REPOSITORY_ROOT / scope).rglob("*.ics"):
                with self.subTest(path=path.relative_to(REPOSITORY_ROOT)):
                    content = path.read_bytes()
                    self.assertTrue(content.endswith(b"\r\n"))
                    self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
                    for line in content.split(b"\r\n"):
                        self.assertLessEqual(len(line), 75)

    def test_event_properties_survive_aggregation(self) -> None:
        uid = "C8835A1E-C99B-4DE1-B5BB-67F8CCFECDA0"
        internal = self.read_calendar("internal.ics")
        event = next(
            component
            for component in internal.walk("VEVENT")
            if str(component.get("UID")) == uid
        )
        self.assertEqual(
            str(event.get("X-APPLE-STRUCTURED-LOCATION")),
            "geo:30.249889,120.253461",
        )
        self.assertEqual(
            str(event.get("X-APPLE-TRAVEL-ADVISORY-BEHAVIOR")),
            "DISABLED",
        )

    def test_rejects_event_in_wrong_period_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_source_event(
                root,
                "public/2026/09/wrong-month.ics",
                "wrong-month",
                datetime(2026, 10, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
            )
            with self.assertRaisesRegex(ValueError, "DTSTART is in 2026-10"):
                load_source_events(root)

    def test_rejects_duplicate_uid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            start = datetime(2026, 9, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
            self.write_source_event(root, "public/2026/09/first.ics", "duplicate", start)
            self.write_source_event(root, "internal/2026/09/second.ics", "duplicate", start)
            with self.assertRaisesRegex(ValueError, "duplicate UID duplicate"):
                load_source_events(root)


if __name__ == "__main__":
    unittest.main()
