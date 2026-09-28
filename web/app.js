"use strict";

const elements = {
  scope: document.querySelector("#scope"),
  year: document.querySelector("#year"),
  month: document.querySelector("#month"),
  period: document.querySelector("#period"),
  periodLabel: document.querySelector("#period-label"),
  guideTitle: document.querySelector("#guide-title"),
  device: document.querySelector("#device"),
  action: document.querySelector("#action"),
  copy: document.querySelector("#copy"),
  https: document.querySelector("#https"),
  download: document.querySelector("#download"),
  status: document.querySelector("#status"),
};

const isApple = /iPhone|iPad|iPod|Macintosh/.test(navigator.userAgent);
const guidanceTemplate = document.querySelector(isApple ? "#apple-guidance" : "#other-guidance");

let feeds = {};
let periods = [];

function feedKey() {
  if (elements.year.value === "all" && elements.month.value === "all") {
    return elements.scope.value;
  }
  if (elements.year.value !== "all" && elements.month.value === "all") {
    return `${elements.scope.value}:${elements.year.value}`;
  }
  return `${elements.scope.value}:${elements.year.value}-${elements.month.value}`;
}

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

function availablePeriods() {
  const prefix = elements.scope.value === "all" ? "all:" : `${elements.scope.value}:`;
  return periods.filter((item) => feeds[`${prefix}${item.year}-${item.month}`]);
}

function refreshYears() {
  const values = [...new Set(availablePeriods().map((item) => item.year))];
  setOptions(
    elements.year,
    [["all", "全部年份"], ...values.map((value) => [value, value])],
    elements.year.value || "all",
  );
}

function refreshMonths() {
  const values = elements.year.value === "all"
    ? []
    : [...new Set(
      availablePeriods()
        .filter((item) => item.year === elements.year.value)
        .map((item) => item.month),
    )];
  setOptions(
    elements.month,
    [["all", "全年"], ...values.map((value) => [value, `${value} 月`])],
    elements.month.value || "all",
  );
}

function refreshPeriod() {
  const values = availablePeriods();
  elements.period.max = Math.max(values.length - 1, 0);
  elements.period.disabled = !values.length;
  if (!values.length) {
    elements.periodLabel.textContent = "暂无事件";
    return;
  }
  const current = values.findIndex(
    (item) => item.year === elements.year.value && item.month === elements.month.value,
  );
  elements.period.value = current >= 0 ? current : 0;
  elements.periodLabel.textContent = values[elements.period.value].label;
}

function setLinkState(link, url, available) {
  link.href = available ? url : "#";
  link.setAttribute("aria-disabled", String(!available));
}

function showGuidance(available) {
  if (!available) {
    elements.device.textContent = "这个范围暂时没有日历事件。";
    return;
  }
  elements.device.replaceChildren(guidanceTemplate.content.cloneNode(true));
}

function refreshLinks() {
  const feed = feeds[feedKey()];
  const available = Boolean(feed);
  setLinkState(elements.action, isApple && available ? feed.webcal : "#", available);
  setLinkState(elements.https, available ? feed.https : "#", available);
  setLinkState(elements.download, available ? feed.https : "#", available);
  elements.download.download = elements.scope.value === "public" ? "BETA.ics" : "BETA-SDC.ics";
  elements.download.textContent = isApple ? "下载 ICS" : "下载 ICS 导入系统日历";
  elements.copy.disabled = !available;
  elements.action.textContent = available
    ? (isApple ? "订阅到 Apple 日历" : "复制订阅地址")
    : "暂无可订阅内容";
  elements.status.textContent = available
    ? `当前范围：${feed.title}`
    : "这个时间范围暂无事件";
  showGuidance(available);
}

function refresh() {
  refreshYears();
  refreshMonths();
  refreshPeriod();
  refreshLinks();
}

async function copySubscriptionUrl() {
  const feed = feeds[feedKey()];
  if (!feed) return;
  try {
    await navigator.clipboard.writeText(feed.https);
    elements.status.textContent = "订阅地址已复制";
  } catch {
    elements.status.textContent = feed.https;
  }
}

function bindEvents() {
  elements.scope.addEventListener("change", refresh);
  elements.year.addEventListener("change", () => {
    refreshMonths();
    refreshPeriod();
    refreshLinks();
  });
  elements.month.addEventListener("change", () => {
    refreshPeriod();
    refreshLinks();
  });
  elements.period.addEventListener("input", () => {
    const selected = availablePeriods()[elements.period.value];
    if (!selected) return;
    elements.year.value = selected.year;
    refreshMonths();
    elements.month.value = selected.month;
    elements.periodLabel.textContent = selected.label;
    refreshLinks();
  });
  elements.action.addEventListener("click", (event) => {
    if (isApple) return;
    event.preventDefault();
    copySubscriptionUrl();
  });
  elements.copy.addEventListener("click", copySubscriptionUrl);
}

async function initialize() {
  elements.guideTitle.textContent = isApple ? " Apple 订阅说明" : "订阅说明";
  bindEvents();
  try {
    const response = await fetch("calendar-data.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    ({ feeds, periods } = await response.json());
    refresh();
  } catch (error) {
    elements.status.textContent = "日历数据加载失败，请稍后重试。";
    elements.device.textContent = "无法读取订阅信息。";
    console.error("Failed to load calendar data", error);
  }
}

initialize();
