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
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
        padding: 20px; color: #17202a; background: #eef2f6;
        font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
      main {{ width: min(100%, 620px); padding: 28px; background: #fff;
        border: 1px solid #d8e0e8; border-radius: 10px;
        box-shadow: 0 16px 40px rgb(23 32 42 / 9%); }}
      header {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }}
      h1 {{ margin: 0; font-size: 26px; letter-spacing: 0; }}
      .subtitle {{ margin: 6px 0 22px; color: #536273; }}
      .device {{ margin: 0 0 18px; padding: 10px 12px; color: #465668;
        background: #f4f7fa; border-radius: 6px; font-size: 14px; }}
      .controls {{ display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 10px; }}
      label {{ display: grid; gap: 5px; color: #536273; font-size: 13px; font-weight: 600; }}
      select {{ width: 100%; min-height: 42px; border: 1px solid #b9c5d1; border-radius: 6px;
        padding: 8px 10px; background: #fff; color: #17202a; font: inherit; }}
      .timeline {{ margin: 22px 0 20px; }}
      .timeline-head {{ display: flex; justify-content: space-between; margin-bottom: 6px;
        color: #536273; font-size: 13px; }}
      output {{ color: #17202a; font-weight: 700; }}
      input[type="range"] {{ width: 100%; accent-color: #1769aa; }}
      .primary {{ display: flex; width: 100%; min-height: 48px; align-items: center;
        justify-content: center; border: 0; border-radius: 7px; background: #1769aa;
        color: #fff; font: inherit; font-weight: 700; text-decoration: none; cursor: pointer; }}
      .primary:hover {{ background: #12558b; }}
      .primary:disabled, .primary[aria-disabled="true"] {{ opacity: .5; pointer-events: none; }}
      .secondary {{ display: flex; justify-content: center; gap: 14px; margin-top: 12px;
        color: #536273; font-size: 13px; }}
      .secondary button, .secondary a {{ border: 0; padding: 0; background: transparent;
        color: #1769aa; font: inherit; text-decoration: underline; cursor: pointer; }}
      .warning {{ margin: 18px 0 0; color: #7b5b00; font-size: 13px; }}
      @media (max-width: 560px) {{
        main {{ padding: 22px; }}
        .controls {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <header>
        <div>
          <h1>BETA-SDC 日历</h1>
          <p class="subtitle">选择范围后，一键添加订阅。</p>
        </div>
      </header>
      <p id="device" class="device"></p>
      <div class="controls">
        <label>分类
          <select id="scope">
            <option value="all">全部活动</option>
            <option value="public" selected>公开活动</option>
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
          <span>时间范围</span>
          <output id="period-label">全部时间</output>
        </div>
        <input id="period" type="range" min="0" max="0" value="0" step="1">
      </div>
      <a id="action" class="primary" href="#" aria-disabled="true">准备订阅</a>
      <div class="secondary">
        <button id="copy" type="button">复制订阅地址</button>
        <a id="https" href="#" aria-disabled="true">查看 HTTPS 地址</a>
      </div>
      <p id="status" class="warning"></p>
    </main>
    <script>
      const FEEDS = {feed_data};
      const PERIODS = {period_data};
      const scope = document.querySelector("#scope");
      const year = document.querySelector("#year");
      const month = document.querySelector("#month");
      const period = document.querySelector("#period");
      const periodLabel = document.querySelector("#period-label");
      const device = document.querySelector("#device");
      const action = document.querySelector("#action");
      const copy = document.querySelector("#copy");
      const https = document.querySelector("#https");
      const status = document.querySelector("#status");
      const isApple = /iPhone|iPad|iPod|Macintosh/.test(navigator.userAgent);

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

      function availablePeriods() {{
        const prefix = scope.value === "all" ? "all:" : `${{scope.value}}:`;
        return PERIODS.filter((item) => FEEDS[`${{prefix}}${{item.year}}-${{item.month}}`]);
      }}

      function refreshYears() {{
        const values = [...new Set(availablePeriods().map((item) => item.year))];
        setOptions(year, [["all", "全部年份"], ...values.map((value) => [value, value])], year.value || "all");
      }}

      function refreshMonths() {{
        const values = [...new Set(availablePeriods()
          .filter((item) => year.value === "all" || item.year === year.value)
          .map((item) => item.month))];
        setOptions(month, [["all", "全年"], ...values.map((value) => [value, `${{value}} 月`])], month.value || "all");
      }}

      function refreshPeriod() {{
        const values = availablePeriods();
        period.max = Math.max(values.length - 1, 0);
        period.disabled = !values.length;
        if (!values.length) {{
          periodLabel.textContent = "暂无事件";
          return;
        }}
        const current = values.findIndex((item) => item.year === year.value && item.month === month.value);
        period.value = current >= 0 ? current : 0;
        periodLabel.textContent = values[period.value].label;
      }}

      function refreshLinks() {{
        const feed = FEEDS[feedKey()];
        const available = Boolean(feed);
        const url = available ? (isApple ? feed.webcal : feed.https) : "#";
        action.href = url;
        action.setAttribute("aria-disabled", String(!available));
        https.href = available ? feed.https : "#";
        https.setAttribute("aria-disabled", String(!available));
        copy.disabled = !available;
        action.textContent = available
          ? (isApple ? "订阅到 Apple 日历" : "复制订阅地址")
          : "暂无可订阅内容";
        device.textContent = isApple
          ? "检测到 Apple 设备：点击主按钮即可订阅。"
          : "当前设备：复制地址后，在 Google Calendar、Outlook 或其他日历应用中选择“通过网址订阅”。";
        status.textContent = available ? `当前范围：${{feed.title}}` : "这个时间范围暂无事件";
      }}

      function refresh() {{
        refreshYears();
        refreshMonths();
        refreshPeriod();
        refreshLinks();
      }}

      scope.addEventListener("change", () => {{ refreshYears(); refreshMonths(); refreshPeriod(); refreshLinks(); }});
      year.addEventListener("change", () => {{ refreshMonths(); refreshPeriod(); refreshLinks(); }});
      month.addEventListener("change", () => {{ refreshPeriod(); refreshLinks(); }});
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
        try {{
          await navigator.clipboard.writeText(feed.https);
          status.textContent = "订阅地址已复制";
        }} catch {{
          status.textContent = feed.https;
        }}
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
