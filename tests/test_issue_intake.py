from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from issue_intake import canonical_issue_url, prepare_issue, read_issue


def proposal(schedule: str) -> dict:
    return {
        "title": "[event] 活动",
        "url": "https://github.com/BETA-SDC/event-proposal/issues/998",
        "body": f"### 活动名称\n活动 / Event\n\n### 时间、地点和形式\n"
                f"- 时间：{schedule}\n- 地点：云谷校区 / Yungu Campus H4-121\n\n"
                "### 关键截止时间\n2026-10-01\n",
        "comments": [],
    }


class IssueIntakeTest(unittest.TestCase):
    def test_exact_schedule_and_deadline_is_not_event_date(self) -> None:
        prepared = prepare_issue(proposal("2026-11-11 14:00–16:00"))
        self.assertEqual(prepared["candidates"]["dates"], ["2026-11-11"])
        self.assertEqual(prepared["draft"]["start"], "2026-11-11T14:00")
        self.assertEqual(prepared["draft"]["end"], "2026-11-11T16:00")
        self.assertEqual(prepared["draft"]["title"], "活动 / Event")
        self.assertNotIn("scope", prepared["draft"])

    def test_partial_provisional_year_and_multiple_dates_require_review(self) -> None:
        for schedule in (
            "11月11日下午，年份未注明",
            "2026-11-11 下午，原消息未注明年份，按当前年份暂记",
            "2026-11-11 或 2026-11-12 14:00-16:00",
            "2026-02-30 14:00-16:00",
            "2026-11-11 下午2:00-4:00",
            "2026-11-11 14:00-16:00 UTC",
            "2026-11-11 14:00-16:00 +08:00",
            "2026-11-11T01:00-08:00",
            "2026-11-11 23:00-01:00",
        ):
            with self.subTest(schedule=schedule):
                prepared = prepare_issue(proposal(schedule))
                self.assertNotIn("start", prepared["draft"])
                self.assertTrue(any(item["field"] in ("date", "year", "time", "schedule") for item in prepared["unresolved"]))

    def test_all_day_is_explicit_and_comments_block_automatic_schedule(self) -> None:
        issue = proposal("2026-11-11 全天")
        prepared = prepare_issue(issue)
        self.assertEqual(prepared["draft"]["start"], "2026-11-11")
        self.assertEqual(prepared["draft"]["duration_days"], 1)
        issue["comments"] = [{"body": "改到12日", "updatedAt": "2026-10-13T00:00:00Z"}]
        prepared = prepare_issue(issue)
        self.assertNotIn("start", prepared["draft"])
        self.assertEqual(prepared["comments"][0]["body"], "改到12日")

    def test_fenced_headings_and_other_field_dates_do_not_set_schedule(self) -> None:
        issue = proposal("")
        issue["body"] += "\n```\n### 时间\n2026-12-01 14:00-16:00\n```\n"
        issue["body"] = issue["body"].replace("云谷校区 / Yungu Campus H4-121", "2026-11-11 14:00-16:00")
        prepared = prepare_issue(issue)
        self.assertEqual(prepared["candidates"]["dates"], [])
        self.assertNotIn("start", prepared["draft"])

    def test_network_read_prefers_opencli_and_validates_url(self) -> None:
        for value in (
            "https://example.com/BETA-SDC/event-proposal/issues/58",
            "https://github.com/BETA-SDC/event-proposal/pull/58",
            "https://github.com/a/b/issues/58/extra",
            "https://user@github.com/a/b/issues/58",
        ):
            with self.assertRaises(ValueError):
                canonical_issue_url(value)
        with patch("issue_intake.shutil.which", return_value="/bin/opencli"), patch(
            "issue_intake.subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", "network unavailable"),
        ) as run:
            with self.assertRaisesRegex(ValueError, "network unavailable"):
                read_issue("https://github.com/BETA-SDC/event-proposal/issues/58")
            self.assertEqual(run.call_args.args[0][:4], ["opencli", "gh", "issue", "view"])
            self.assertEqual(run.call_count, 1)
        with patch("issue_intake.shutil.which", side_effect=lambda name: "/bin/gh" if name == "gh" else None), patch(
            "issue_intake.subprocess.run", side_effect=subprocess.TimeoutExpired(["gh"], 30),
        ):
            with self.assertRaisesRegex(ValueError, "timed out"):
                read_issue("https://github.com/BETA-SDC/event-proposal/issues/58")


if __name__ == "__main__":
    unittest.main()
