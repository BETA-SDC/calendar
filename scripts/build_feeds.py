#!/usr/bin/env python3
"""Build category, yearly, monthly, and all-event ICS feeds."""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

from icalendar import Calendar


ROOT_CATEGORIES = ("public", "internal")


def read_event(path: Path) -> tuple[Calendar, object]:
    calendar = Calendar.from_ical(path.read_bytes())
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    if len(events) != 1:
        raise ValueError(f"{path}: expected exactly one VEVENT, found {len(events)}")
    return calendar, events[0]


def event_uid(event: object, path: Path) -> str:
    uid = str(event.get("UID", "")).strip()
    if not uid:
        raise ValueError(f"{path}: event is missing UID")
    return uid


def build_calendar(name: str, events: list[object], timezones: list[object]) -> Calendar:
    calendar = Calendar()
    calendar.add("VERSION", "2.0")
    calendar.add("PRODID", "-//BETA-SDC//Calendar Feeds//EN")
    calendar.add("CALSCALE", "GREGORIAN")
    calendar.add("X-WR-CALNAME", name)
    calendar.add("X-WR-TIMEZONE", "Asia/Shanghai")

    seen_timezones: set[bytes] = set()
    for timezone in timezones:
        serialized = timezone.to_ical()
        if serialized not in seen_timezones:
            calendar.add_component(timezone)
            seen_timezones.add(serialized)

    for event in sorted(events, key=lambda item: str(item.get("DTSTART", ""))):
        calendar.add_component(event)
    return calendar


def write_feed(path: Path, name: str, events: list[object], timezones: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_calendar(name, events, timezones).to_ical())


def make_index(output: Path, feeds: dict[str, dict[str, str]], periods: list[tuple[str, str]]) -> None:
    feed_data = json.dumps(feeds, ensure_ascii=False, separators=(",", ":"))
    period_data = json.dumps(
        [{"year": year, "month": month, "label": f"{year}-{month}"} for year, month in periods],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    html = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>BETA-SDC 日历订阅</title>
    <style>
      :root {{ color-scheme: light; }}
      body {{ margin: 0; padding: 32px 16px; color: #17202a; background: #f5f7fa;
        font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      main {{ max-width: 760px; margin: 0 auto; padding: 28px; background: #fff;
        border: 1px solid #dfe5ec; border-radius: 8px; }}
      h1 {{ margin: 0 0 8px; }}
      .muted {{ color: #536273; }}
      .warning {{ padding: 12px; background: #fff4d6; border-left: 4px solid #d89b00; }}
      .controls {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px; margin: 24px 0 18px; }}
      label {{ display: grid; gap: 5px; font-weight: 600; }}
      select, button, a.button {{ min-height: 42px; box-sizing: border-box; border: 1px solid #b9c5d1;
        border-radius: 6px; padding: 8px 12px; background: #fff; color: #17202a;
        font: inherit; text-decoration: none; }}
      .timeline {{ margin: 18px 0 24px; }}
      .timeline-head {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 6px; }}
      input[type="range"] {{ width: 100%; accent-color: #1769aa; }}
      .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
      a.primary {{ background: #1769aa; border-color: #1769aa; color: #fff; font-weight: 600; }}
      button {{ cursor: pointer; }}
      button:disabled, a[aria-disabled="true"] {{ opacity: .5; pointer-events: none; }}
      @media (max-width: 640px) {{
        .controls {{ grid-template-columns: 1fr; }}
        main {{ padding: 22px; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <h1>BETA-SDC 日历订阅</h1>
      <p class="muted">按分类、年份和月份选择要订阅的事件范围。</p>
      <p class="warning">内部事件订阅仅适用于确实允许公开访问的内容。GitHub Pages 不提供日历级别的访问权限。</p>
      <div class="controls">
        <label>分类
          <select id="scope">
            <option value="all">全部活动</option>
            <option value="public">公开活动</option>
            <option value="internal">内部事件</option>
          </select>
        </label>
        <label>年份
          <select id="year"></select>
        </label>
        <label>月份
          <select id="month"></select>
        </label>
      </div>
      <div class="timeline">
        <div class="timeline-head">
          <strong>时间滚动</strong>
          <output id="period-label">全部时间</output>
        </div>
        <input id="period" type="range" min="0" max="0" value="0" step="1">
      </div>
      <div class="actions">
        <a id="webcal" class="button primary" href="#" aria-disabled="true">点击订阅</a>
        <a id="https" class="button" href="#" aria-disabled="true">HTTPS 地址</a>
        <button id="copy" type="button">复制 HTTPS 地址</button>
      </div>
      <p id="status" class="muted"></p>
    </main>
    <script>
      const FEEDS = {feed_data};
      const PERIODS = {period_data};
      const scope = document.querySelector("#scope");
      const year = document.querySelector("#year");
      const month = document.querySelector("#month");
      const period = document.querySelector("#period");
      const periodLabel = document.querySelector("#period-label");
      const webcal = document.querySelector("#webcal");
      const https = document.querySelector("#https");
      const copy = document.querySelector("#copy");
      const status = document.querySelector("#status");

      function feedKey() {{
        if (year.value === "all" && month.value === "all") return scope.value;
        if (year.value !== "all" && month.value === "all") return `${{scope.value}}:${{year.value}}`;
        return `${{scope.value}}:${{year.value}}-${{month.value}}`;
      }}

      function setOptions(select, options, selected) {{
        select.innerHTML = options.map(([value, label]) =>
          `<option value="${{value}}">${{label}}</option>`).join("");
        select.value = options.some(([value]) => value === selected) ? selected : options[0][0];
      }}

      function refreshYears() {{
        const values = [...new Set(availablePeriods().map((item) => item.year))];
        const selected = year.value || "all";
        setOptions(year, [["all", "全部年份"], ...values.map((value) => [value, value])], selected);
      }}

      function refreshMonths() {{
        const values = [...new Set(availablePeriods()
          .filter((item) => year.value === "all" || item.year === year.value)
          .map((item) => item.month))];
        const selected = month.value || "all";
        setOptions(month, [["all", "全年"], ...values.map((value) => [value, `${{value}} 月`])], selected);
      }}

      function availablePeriods() {{
        const prefix = scope.value === "all" ? "all:" : `${{scope.value}}:`;
        return PERIODS.filter((item) => FEEDS[`${{prefix}}${{item.year}}-${{item.month}}`]);
      }}

      function refreshPeriodSlider() {{
        const values = availablePeriods();
        period.max = Math.max(values.length - 1, 0);
        if (!values.length) {{
          period.disabled = true;
          periodLabel.textContent = "暂无事件";
          return;
        }}
        period.disabled = false;
        const current = values.findIndex((item) => item.year === year.value && item.month === month.value);
        period.value = current >= 0 ? current : 0;
        periodLabel.textContent = `${{values[period.value].label}}`;
      }}

      function refreshLinks() {{
        const feed = FEEDS[feedKey()];
        const available = Boolean(feed);
        webcal.href = available ? feed.webcal : "#";
        https.href = available ? feed.https : "#";
        webcal.setAttribute("aria-disabled", String(!available));
        https.setAttribute("aria-disabled", String(!available));
        copy.disabled = !available;
        status.textContent = available ? `当前选择：${{feed.title}}` : "这个时间范围暂无事件";
      }}

      function refresh() {{
        refreshYears();
        refreshMonths();
        refreshPeriodSlider();
        refreshLinks();
      }}

      scope.addEventListener("change", () => {{ refreshYears(); refreshMonths(); refreshPeriodSlider(); refreshLinks(); }});
      year.addEventListener("change", () => {{ refreshMonths(); refreshPeriodSlider(); refreshLinks(); }});
      month.addEventListener("change", () => {{ refreshPeriodSlider(); refreshLinks(); }});
      period.addEventListener("input", () => {{
        const selected = availablePeriods()[period.value];
        if (!selected) return;
        year.value = selected.year;
        refreshMonths();
        month.value = selected.month;
        periodLabel.textContent = selected.label;
        refreshLinks();
      }});
      copy.addEventListener("click", async () => {{
        const feed = FEEDS[feedKey()];
        if (!feed) return;
        await navigator.clipboard.writeText(feed.https);
        status.textContent = "HTTPS 地址已复制";
      }});
      refresh();
    </script>
  </body>
</html>
"""
    (output / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("site"))
    args = parser.parse_args()

    output = args.output
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    by_scope: dict[str, list[tuple[str, str, object, list[object]]]] = defaultdict(list)
    all_timezones: list[object] = []
    all_uids: set[str] = set()

    for scope in ROOT_CATEGORIES:
        scope_root = Path(scope)
        if not scope_root.exists():
            continue
        for path in sorted(scope_root.rglob("*.ics")):
            relative = path.relative_to(scope_root)
            if len(relative.parts) < 3:
                raise ValueError(f"{path}: expected {scope}/YYYY/MM/event.ics")
            year, month = relative.parts[0], relative.parts[1]
            if not (year.isdigit() and len(year) == 4 and month.isdigit() and len(month) == 2):
                raise ValueError(f"{path}: expected numeric YYYY/MM directories")

            calendar, event = read_event(path)
            uid = event_uid(event, path)
            if uid in all_uids:
                raise ValueError(f"duplicate UID {uid}: {path}")
            all_uids.add(uid)
            timezones = [component for component in calendar.walk() if component.name == "VTIMEZONE"]
            all_timezones.extend(timezones)
            by_scope[scope].append((year, month, event, timezones))

    feeds: dict[str, dict[str, str]] = {}
    all_events: list[object] = []
    all_by_period: dict[tuple[str, str], list[object]] = defaultdict(list)

    def add_feed(key: str, title: str, path: Path) -> None:
        relative_path = path.relative_to(output).as_posix()
        feeds[key] = {
            "title": title,
            "https": f"https://beta-sdc.github.io/calendar/{relative_path}",
            "webcal": f"webcal://beta-sdc.github.io/calendar/{relative_path}",
        }

    for scope in ROOT_CATEGORIES:
        entries = by_scope[scope]
        scope_events = [event for _, _, event, _ in entries]
        scope_timezones = [timezone for _, _, _, timezones in entries for timezone in timezones]
        if scope_events:
            path = output / f"{scope}.ics"
            write_feed(path, f"BETA-SDC {scope}", scope_events, scope_timezones)
            add_feed(scope, f"{scope}（全部）", path)

        by_year: dict[str, list[object]] = defaultdict(list)
        by_month: dict[tuple[str, str], list[object]] = defaultdict(list)
        for year, month, event, _ in entries:
            by_year[year].append(event)
            by_month[(year, month)].append(event)
            all_events.append(event)
            all_by_period[(year, month)].append(event)

        for year, events in sorted(by_year.items()):
            path = output / scope / f"{year}.ics"
            write_feed(path, f"BETA-SDC {scope} {year}", events, scope_timezones)
            add_feed(f"{scope}:{year}", f"{scope} {year}", path)
        for (year, month), events in sorted(by_month.items()):
            path = output / scope / year / f"{month}.ics"
            write_feed(path, f"BETA-SDC {scope} {year}-{month}", events, scope_timezones)
            add_feed(f"{scope}:{year}-{month}", f"{scope} {year}-{month}", path)

    if all_events:
        path = output / "BETA-SDC.ics"
        write_feed(path, "BETA-SDC", all_events, all_timezones)
        add_feed("all", "全部活动", path)

    by_year: dict[str, list[object]] = defaultdict(list)
    for (year, _), events in all_by_period.items():
        by_year[year].extend(events)
    for year, events in sorted(by_year.items()):
        path = output / f"{year}.ics"
        write_feed(path, f"BETA-SDC {year}", events, all_timezones)
        add_feed(f"all:{year}", f"全部 {year}", path)
    for (year, month), events in sorted(all_by_period.items()):
        path = output / year / f"{month}.ics"
        write_feed(path, f"BETA-SDC {year}-{month}", events, all_timezones)
        add_feed(f"all:{year}-{month}", f"全部 {year}-{month}", path)

    make_index(output, feeds, sorted(all_by_period))


if __name__ == "__main__":
    main()
