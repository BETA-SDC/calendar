from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
