"""Read GitHub event proposals into conservative, reviewable calendar drafts."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ISSUE_PATH = re.compile(r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)/?")
DATE_PATTERN = re.compile(r"(?<!\d)(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?(?!\d)")
TIME_RANGE = re.compile(
    r"(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)\s*(?:[-–—~～]|至|到)\s*"
    r"([01]?\d|2[0-3])[:：]([0-5]\d)(?!\d)"
)
UNKNOWN = re.compile(r"待定|暂定|待确认|未定|暂记|需.{0,6}核实|TBD|tentative", re.IGNORECASE)
SECTION_NAMES = {
    "title": ("活动名称", "Event Name"),
    "schedule": ("时间、地点和形式", "时间和地点", "时间", "Schedule"),
    "source": ("信息来源", "Source"),
}


def canonical_issue_url(value: str) -> tuple[str, str, str, str]:
    parsed = urlsplit(value)
    match = ISSUE_PATH.fullmatch(parsed.path)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or not match or parsed.username:
        raise ValueError("expected https://github.com/OWNER/REPO/issues/NUMBER")
    owner, repo, number = match.groups()
    return f"https://github.com/{owner}/{repo}/issues/{number}", owner, repo, number


def read_issue(source: str, *, offline: bool = False) -> dict[str, Any]:
    if offline:
        issue = json.loads(Path(source).expanduser().read_text(encoding="utf-8"))
    else:
        url, _, _, _ = canonical_issue_url(source)
        if shutil.which("opencli"):
            command = ["opencli", "gh"]
        elif shutil.which("gh"):
            command = ["gh"]
        else:
            raise ValueError("install opencli/gh or supply --issue-json FILE")
        command += ["issue", "view", url, "--json", "title,body,comments,url,updatedAt"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("GitHub issue read timed out after 30 seconds") from exc
        if result.returncode:
            raise ValueError(f"GitHub issue read failed: {result.stderr.strip()}")
        issue = json.loads(result.stdout)
    if not isinstance(issue, dict) or not isinstance(issue.get("body"), str):
        raise ValueError("issue JSON must contain a string body and a GitHub issue url")
    if not isinstance(issue.get("title"), str):
        raise ValueError("issue JSON must contain a string title")
    canonical_issue_url(issue.get("url", ""))
    if not isinstance(issue.get("comments", []), list) or any(
        not isinstance(comment, dict) or not isinstance(comment.get("body", ""), str)
        for comment in issue.get("comments", [])
    ):
        raise ValueError("issue comments must be an array")
    return issue


def sections_from_body(body: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = ""
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        heading = None if fenced else re.fullmatch(r"#{1,6}\s+(.+?)\s*#*\s*", line)
        if heading:
            current = heading.group(1)
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return {key: "\n".join(lines).strip() for key, lines in sections.items()}


def find_section(sections: dict[str, str], kind: str) -> str:
    return next((sections[name] for name in SECTION_NAMES[kind] if name in sections), "")


def labeled_lines(section: str, label: str) -> str:
    values = []
    collecting = False
    for line in section.splitlines():
        cleaned = line.strip().lstrip("-* ").replace("**", "")
        match = re.match(r"([^：:]+)[：:]\s*(.*)", cleaned)
        if match:
            collecting = match.group(1).strip() == label
            if collecting:
                values.append(match.group(2))
        elif collecting and cleaned:
            values.append(cleaned)
    return "\n".join(values).strip()


def prepare_issue(issue: dict[str, Any]) -> dict[str, Any]:
    url, owner, repo, number = canonical_issue_url(issue["url"])
    sections = sections_from_body(issue["body"])
    title = find_section(sections, "title") or re.sub(r"^\[event\]\s*", "", issue["title"])
    scheduling = find_section(sections, "schedule")
    schedule = labeled_lines(scheduling, "时间")
    if not schedule and not re.search(r"(?m)^\s*[-*]?\s*(?:地点|形式|嘉宾)[：:]", scheduling):
        schedule = scheduling
    location = labeled_lines(scheduling, "地点")
    original = find_section(sections, "source")
    dates = []
    for match in DATE_PATTERN.finditer(schedule):
        try:
            candidate = date(*map(int, match.groups())).isoformat()
        except ValueError:
            continue
        if candidate not in dates:
            dates.append(candidate)
    ranges = list(TIME_RANGE.finditer(schedule))
    time_of_day = next((part for part in ("上午", "下午", "晚上", "中午") if part in schedule), None)
    unresolved = []
    if not dates:
        unresolved.append({"field": "date", "reason": "No explicit valid year/month/day in the schedule."})
    elif len(dates) != 1:
        unresolved.append({"field": "date", "reason": "Multiple dates require selecting an event schedule."})
    year_uncertain = bool(re.search(r"未.{0,4}年份|年份.{0,12}(?:核实|确认|未定)|暂记", schedule + original))
    if year_uncertain:
        unresolved.append({"field": "year", "reason": "The source explicitly says the year is provisional."})
    all_day = bool(re.search(r"全天|\ball[- ]day\b", schedule, re.IGNORECASE))
    if len(ranges) != 1 and not (all_day and not ranges):
        unresolved.append({"field": "time", "reason": "No single explicit HH:MM-HH:MM range; no hours inferred."})
    if len(ranges) == 1 and time_of_day in ("下午", "晚上", "中午") and int(ranges[0].group(1)) < 12:
        unresolved.append({"field": "time", "reason": "12-hour wording needs explicit 24-hour clock values."})
    offset_suffix = (
        bool(re.search(r"[+-]\d{2}:?\d{2}", schedule[ranges[0].end():]))
        if len(ranges) == 1 else False
    )
    if offset_suffix or re.search(
        r"\b(?:UTC|GMT|AM|PM)\b|T\d{2}:\d{2}[+-]\d{2}:?\d{2}|时区",
        schedule, re.IGNORECASE,
    ):
        unresolved.append({"field": "time", "reason": "Explicit time zone/meridiem needs review; no zone inferred."})
    if UNKNOWN.search(schedule):
        unresolved.append({"field": "schedule", "reason": "Schedule text contains provisional or unresolved wording."})
    if not location or UNKNOWN.search(location):
        unresolved.append({"field": "location", "reason": "Venue is missing or provisional."})
    if " / " not in title:
        unresolved.append({"field": "title", "reason": "Supply a bilingual --title."})
    unresolved.append({"field": "scope", "reason": "Choose public or internal explicitly."})
    comments = issue.get("comments", [])
    if comments:
        unresolved.append({"field": "comments", "reason": "Review comments for changes; draft uses the issue body only."})

    uid = f"{owner.lower()}-{repo.lower()}-{number}@beta-sdc.github.io"
    draft: dict[str, Any] = {
        "uid": uid,
        "url": url,
        "filename": f"issue-{number}",
        "description": "\n\n".join(
            text for text in (title, scheduling, original) if text
        ),
    }
    if " / " in title:
        draft["title"] = title
    if location and " / " in location and not UNKNOWN.search(location):
        draft["location"] = location
    # Only a single, explicit same-day range can become a draft schedule automatically.
    schedule_unresolved = any(item["field"] in ("date", "year", "time", "schedule", "comments") for item in unresolved)
    if not schedule_unresolved:
        if all_day and not ranges:
            draft["start"] = dates[0]
            draft["duration_days"] = 1
        else:
            hour, minute, end_hour, end_minute = map(int, ranges[0].groups())
            if (end_hour, end_minute) > (hour, minute):
                draft["start"] = f"{dates[0]}T{hour:02d}:{minute:02d}"
                draft["end"] = f"{dates[0]}T{end_hour:02d}:{end_minute:02d}"
            else:
                unresolved.append({"field": "time", "reason": "Overnight or reversed range needs explicit end date."})
    return {
        "schemaVersion": 1,
        "source": {"url": url, "updatedAt": issue.get("updatedAt")},
        "evidence": {"title": title, "schedule": schedule, "location": location},
        "candidates": {"dates": dates, "timeOfDay": time_of_day},
        "unresolved": unresolved,
        "comments": [
            {"body": comment.get("body", ""), "updatedAt": comment.get("updatedAt")}
            for comment in comments
        ],
        "draft": draft,
    }


INPUT_FIELDS = {
    "scope", "title", "start", "end", "duration_minutes", "duration_days", "location",
    "description", "url", "uid", "filename", "alarm_minutes",
}
INTEGER_FIELDS = {"duration_minutes", "duration_days", "alarm_minutes"}


def read_draft(value: str) -> dict[str, Any]:
    import sys

    raw = sys.stdin.read() if value == "-" else Path(value).expanduser().read_text(encoding="utf-8")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("--input must contain a JSON object")
    if "draft" in document:
        if document.get("schemaVersion") != 1:
            raise ValueError("unsupported prepared draft schemaVersion")
        draft = document["draft"]
    else:
        draft = document
    if not isinstance(draft, dict) or set(draft) - INPUT_FIELDS:
        raise ValueError("--input draft contains unsupported fields")
    for key, field in draft.items():
        if key in INTEGER_FIELDS:
            minimum = 0 if key == "alarm_minutes" else 1
            if isinstance(field, bool) or not isinstance(field, int) or field < minimum:
                raise ValueError(f"--input {key} must be an integer >= {minimum}")
        elif not isinstance(field, str) or (key not in ("description", "location", "url") and not field.strip()):
            raise ValueError(f"--input {key} must be a nonempty string")
    return draft
