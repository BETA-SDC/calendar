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
        self.assertEqual(str(public.get("X-WR-CALNAME")), "BETA")
        self.assertEqual(str(internal.get("X-WR-CALNAME")), "BETA-SDC internal")
        for calendar in (public, internal):
            self.assertEqual(str(calendar.get("REFRESH-INTERVAL")), "PT1H")
            self.assertEqual(str(calendar.get("X-PUBLISHED-TTL")), "PT1H")

    def test_web_assets_and_data_are_generated(self) -> None:
        for filename in ("index.html", "styles.css", "app.js", "calendar-data.json"):
            self.assertTrue((self.output / filename).is_file(), filename)

        data = json.loads((self.output / "calendar-data.json").read_text(encoding="utf-8"))
        self.assertEqual(data["feeds"]["public"]["title"], "公开活动（全部）")
        self.assertEqual(
            data["feeds"]["public"]["webcal"],
            "webcal://beta-sdc.github.io/calendar/public.ics",
        )
        self.assertIn(
            {"year": "2026", "month": "10", "label": "2026-10"},
            data["periods"],
        )

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
