"use strict";

const elements = {
  scope: document.querySelector("#event-scope"),
  year: document.querySelector("#event-year"),
  month: document.querySelector("#event-month"),
  status: document.querySelector("#event-status"),
  list: document.querySelector("#event-list"),
};

const dateFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "short",
});

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

let events = [];

function setOptions(select, options, selected) {
  const optionElements = options.map(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
  });
  select.replaceChildren(...optionElements);
  select.value = options.some(([value]) => value === selected) ? selected : options[0][0];
}

function eventsInScope() {
  return events.filter(
    (event) => elements.scope.value === "all" || event.scope === elements.scope.value,
  );
}

function refreshYears() {
  const years = [...new Set(eventsInScope().map((event) => event.year))].sort();
  setOptions(
    elements.year,
    [["all", "全部年份"], ...years.map((year) => [year, year])],
    elements.year.value || "all",
  );
}

function refreshMonths() {
  const months = elements.year.value === "all"
    ? []
    : [...new Set(
      eventsInScope()
        .filter((event) => event.year === elements.year.value)
        .map((event) => event.month),
    )].sort();
  setOptions(
    elements.month,
    [["all", "全年"], ...months.map((month) => [month, `${month} 月`])],
    elements.month.value || "all",
  );
}

function filteredEvents() {
  return eventsInScope().filter((event) => {
    const matchesYear = elements.year.value === "all" || event.year === elements.year.value;
    const matchesMonth = elements.month.value === "all" || event.month === elements.month.value;
    return matchesYear && matchesMonth;
  });
}

function eventTime(event) {
  if (event.allDay) return "全天";
  const start = timeFormatter.format(new Date(event.start));
  if (!event.end) return start;
  return `${start}–${timeFormatter.format(new Date(event.end))}`;
}

function createActionLink(label, event, download = false) {
  const link = document.createElement("a");
  link.className = "event-action";
  link.href = event.url;
  if (download) link.download = event.filename;
  link.textContent = label;
  return link;
}

function createCopyButton(event) {
  const button = document.createElement("button");
  button.className = "event-action event-copy";
  button.type = "button";
  button.textContent = "复制订阅链接";
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(event.url);
      elements.status.textContent = `已复制订阅链接：${event.title}`;
    } catch {
      elements.status.textContent = event.url;
    }
  });
  return button;
}

function createEventRow(event) {
  const article = document.createElement("article");
  article.className = "event-row";

  const details = document.createElement("div");
  details.className = "event-details";

  const scope = document.createElement("p");
  scope.className = "event-scope";
  scope.textContent = event.scopeLabel;

  const title = document.createElement("h4");
  title.textContent = event.title;

  const metadata = document.createElement("p");
  metadata.className = "event-metadata";
  metadata.textContent = event.location
    ? `${eventTime(event)} · ${event.location}`
    : eventTime(event);

  details.append(scope, title, metadata);

  const actions = document.createElement("div");
  actions.className = "event-actions";
  actions.append(
    createActionLink("下载 ICS", event, true),
    createActionLink("打开订阅链接", event),
    createCopyButton(event),
  );

  article.append(details, actions);
  return article;
}

function createTimeline(title, timelineEvents, descending = false) {
  const timeline = document.createElement("section");
  timeline.className = "event-timeline";

  const timelineTitle = document.createElement("h2");
  timelineTitle.textContent = title;
  timeline.append(timelineTitle);

  const groups = new Map();
  for (const event of timelineEvents) {
    if (!groups.has(event.date)) groups.set(event.date, []);
    groups.get(event.date).push(event);
  }

  const dates = [...groups.keys()].sort();
  if (descending) dates.reverse();

  for (const date of dates) {
    const section = document.createElement("section");
    section.className = "date-group";

    const heading = document.createElement("h3");
    heading.textContent = dateFormatter.format(new Date(`${date}T00:00:00+08:00`));
    section.append(heading, ...groups.get(date).map(createEventRow));
    timeline.append(section);
  }

  return timeline;
}

function renderEvents() {
  const visibleEvents = filteredEvents();
  elements.list.replaceChildren();

  if (!visibleEvents.length) {
    elements.status.textContent = "当前范围暂无活动。";
    return;
  }

  const now = new Date();
  const upcoming = visibleEvents.filter(
    (event) => new Date(event.end || event.start) >= now,
  );
  const past = visibleEvents.filter(
    (event) => new Date(event.end || event.start) < now,
  );

  if (upcoming.length) {
    elements.list.append(createTimeline("即将开始", upcoming));
  }
  if (past.length) {
    elements.list.append(createTimeline("历史活动", past, true));
  }

  elements.status.textContent = `共 ${visibleEvents.length} 个活动，按日期排列。`;
}

function refresh() {
  refreshYears();
  refreshMonths();
  renderEvents();
}

function bindEvents() {
  elements.scope.addEventListener("change", refresh);
  elements.year.addEventListener("change", () => {
    refreshMonths();
    renderEvents();
  });
  elements.month.addEventListener("change", renderEvents);
}

async function initialize() {
  bindEvents();
  try {
    const response = await fetch("events-data.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    ({ events } = await response.json());
    refresh();
  } catch (error) {
    elements.status.textContent = "活动数据加载失败，请稍后重试。";
    console.error("Failed to load event data", error);
  }
}

initialize();
