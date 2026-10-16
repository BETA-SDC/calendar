"use strict";

(() => {
  const $ = (selector) => document.querySelector(selector);
  const DateTime = luxon.DateTime;
  const zone = "Asia/Shanghai";
  const preferences = CalendarPreferences;
  let settings = preferences.normalize(null);
  try { settings = preferences.normalize(JSON.parse(localStorage.getItem("beta-calendar-preferences"))); } catch {}
  const memberCategories = [...settings.categories];
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  settings.theme = "system";
  function applyAppearance() {
    document.body.dataset.theme = preferences.theme(settings.theme, media.matches);
    document.body.dataset.density = settings.density;
  }
  function saveSettings() {
    try { localStorage.setItem("beta-calendar-preferences", JSON.stringify({
      ...settings, categories: guestMode ? memberCategories : settings.categories,
    })); } catch {}
  }
  applyAppearance();
  media.addEventListener("change", applyAppearance);
  fetch("/api/site/session", {credentials: "same-origin", cache: "no-store"})
    .then((response) => response.ok ? response.json() : null)
    .then((state) => {
      settings.theme = state?.user?.preferences?.theme || "system";
      applyAppearance();
    })
    .catch(() => {});
  const editor = $("#editor");
  const form = $("#event-form");
  const field = (name) => form.elements.namedItem(name);
  let events = [];
  let capability = { role: "viewer", canEdit: false, user: null };
  let apiMode = false;
  let guestMode = false;
  let activeCategories = preferences.categories;
  let csrf = "";
  let selected = null;
  let saving = false;
  let pendingJob = null;
  let unlocked = false;
  try { unlocked = sessionStorage.getItem("beta-calendar-unlocked") === "true"; } catch {}
  const viewNames = { timeGridDay: "日", timeGridWeek: "周", dayGridMonth: "月", quarter: "季", multiMonthYear: "年" };

  function node(tag, text, className) {
    const result = document.createElement(tag);
    result.textContent = text;
    if (className) result.className = className;
    return result;
  }
  function split(value = "") {
    const [zh, ...en] = value.split(" / ");
    return [zh, en.join(" / ")];
  }
  function dt(value) { return DateTime.fromISO(value, { zone }).setZone(zone); }
  function timeText(event) {
    if (event.allDay) {
      const last = event.end ? dt(event.end).minus({ days: 1 }).toISODate() : event.start.slice(0, 10);
      return last === event.start.slice(0, 10) ? "全天" : `全天 · 至 ${last}`;
    }
    const start = dt(event.start);
    const end = event.end ? dt(event.end) : null;
    return `${start.toFormat("HH:mm")}${end ? ` – ${end.toFormat(start.hasSame(end, "day") ? "HH:mm" : "MM-dd HH:mm")}` : ""}`;
  }
  function message(text, error = false) {
    $("#status").textContent = text;
    $("#status").classList.toggle("error", error);
  }
  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(`/api/calendar${path}`, {
        ...options,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, ...options.headers },
        cache: "no-store",
      });
    } catch { throw new Error("无法连接服务器，表单内容已保留。"); }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.error || `请求失败（${response.status}）`);
      error.status = response.status;
      throw error;
    }
    return body;
  }
  function isRestricted() {
    return settings.categories.some((id) => id !== "public-planned");
  }
  function visibleEvents() {
    const query = $("#search").value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return events.filter((event) => (unlocked || !event.requiresKey)
      && preferences.matches(event, settings.categories, query.join(" ")));
  }
  function periodEvents() {
    const start = dt(calendar.view.currentStart.toISOString());
    const end = dt(calendar.view.currentEnd.toISOString());
    return events.filter((event) => (unlocked || !event.requiresKey) && dt(event.start) < end
      && (event.end ? dt(event.end) > start : dt(event.start) >= start));
  }
  function updateCategories() {
    const available = periodEvents();
    for (const category of preferences.categories) {
      const count = available.filter((event) => preferences.categoryId(event) === category.id).length;
      $(`[data-count="${category.id}"]`).textContent = String(count);
    }
    $("#filter-summary").textContent = `已选 ${settings.categories.filter((id) => activeCategories.some((category) => category.id === id)).length} / ${activeCategories.length} 类`;
  }
  function badges(event) {
    const result = node("div", "", "badges");
    result.append(
      node("span", event.scope === "internal" ? "内部" : "公开", `badge ${event.scope}`),
      node("span", event.status === "tentative" ? "待定" : "计划", `badge ${event.status}`),
    );
    return result;
  }
  function renderAgenda() {
    const start = dt(calendar.view.currentStart.toISOString());
    const end = dt(calendar.view.currentEnd.toISOString());
    const visible = visibleEvents().filter((event) => dt(event.start) < end
      && (event.end ? dt(event.end) > start : dt(event.start) >= start))
      .sort((a, b) => a.start.localeCompare(b.start));
    $("#agenda").replaceChildren();
    $("#event-count").textContent = String(visible.length);
    for (const event of visible) {
      const button = node("button", "", `agenda-item category-${preferences.categoryId(event)}`);
      const [zh, en] = split(event.title);
      button.append(node("p", dt(event.start).setLocale("zh-CN").toFormat("M月d日 cccc"), "agenda-date"),
        node("p", zh, "agenda-title"), node("p", en, "english"),
        node("p", `${timeText(event)}${event.location ? ` · ${split(event.location)[0]}` : ""}`, "agenda-meta"), badges(event));
      button.addEventListener("click", () => openEvent(event));
      $("#agenda").append(button);
    }
    if (!visible.length) $("#agenda").append(node("p", "本期暂无活动", "empty"));
    updateCategories();
  }
  function refresh() {
    $("#access-form").hidden = apiMode || unlocked || !isRestricted();
    $("#access-lock").hidden = apiMode || !unlocked;
    for (const source of calendar.getEventSources()) source.remove();
    for (const category of preferences.categories) {
      calendar.addEventSource({
        id: category.id,
        backgroundColor: "var(--event-fill)", borderColor: "var(--category)", textColor: "var(--event-ink)",
        events: visibleEvents().filter((event) => preferences.categoryId(event) === category.id).map((event) => ({
          id: event.uid, title: event.title, start: event.start, end: event.end,
          allDay: event.allDay, extendedProps: { source: event },
          classNames: [`category-${category.id}`, `event-${event.status}`],
          editable: capability.canEdit && !event.recurring,
        })),
      });
    }
    renderAgenda();
    if (guestMode) message("游客 · 只读");
    else if (!unlocked && isRestricted()) message("只读 · 受限分类尚未解锁");
    else message(apiMode ? (capability.canEdit ? "可编辑" : "只读") : "只读");
  }

  const calendar = new FullCalendar.Calendar($("#calendar"), {
    themeSystem: "standard",
    initialView: "dayGridMonth", locale: "zh-cn", timeZone: zone, firstDay: 1,
    headerToolbar: false, height: "auto", fixedWeekCount: false,
    nowIndicator: true, scrollTime: "08:00:00", slotMinTime: "00:00:00",
    slotMaxTime: "24:00:00", slotDuration: "00:30:00", slotLabelInterval: "01:00",
    expandRows: false, allDaySlot: true,
    dayMaxEvents: 3, eventOrder: "start,title", eventDisplay: "block",
    displayEventTime: false, navLinks: true,
    views: {
      quarter: { type: "multiMonth", duration: { months: 3 }, dateAlignment: "month", dateIncrement: { months: 3 }, multiMonthMaxColumns: 3 },
      multiMonthYear: { multiMonthMaxColumns: 3 },
    },
    datesSet(info) {
      const start = dt(info.view.currentStart.toISOString());
      $("#period-title").textContent = info.view.type === "quarter"
        ? `${start.year}年 · 第${Math.ceil(start.month / 3)}季度`
        : info.view.type === "multiMonthYear" ? `${start.year}年` : info.view.title;
      for (const button of $("#views").querySelectorAll("button")) button.setAttribute("aria-pressed", String(button.dataset.view === info.view.type));
      $(".calendar-scroll").classList.toggle("week-scroll", info.view.type === "timeGridWeek");
      $("#jump-date").value = dt(calendar.getDate().toISOString()).toISODate();
      renderAgenda();
    },
    eventContent(info) {
      const source = info.event.extendedProps.source;
      const [zh, en] = split(source.title);
      const result = node("div", "", "event-content");
      result.append(node("div", timeText(source), "event-time"),
        node("div", zh, "event-title"));
      if (info.view.type !== "timeGridWeek") {
        result.append(node("div", en, "english"));
        if (source.location) result.append(node("p", split(source.location)[0], "event-location"));
        if (source.status === "tentative") result.append(node("div", "待定", "event-label"));
      }
      if (info.view.type === "timeGridDay") result.append(badges(source));
      result.title = `${source.title}\n${timeText(source)}\n${source.location}`;
      return { domNodes: [result] };
    },
    eventClick(info) { info.jsEvent.preventDefault(); openEvent(info.event.extendedProps.source); },
    dateClick(info) { if (capability.canEdit) openEvent(null, info.dateStr); else calendar.changeView("timeGridDay", info.dateStr); },
    navLinkDayClick(date) { calendar.changeView("timeGridDay", date); },
    eventDrop(info) {
      const source = info.event.extendedProps.source;
      const days = info.delta.days;
      if (info.delta.months || info.delta.years || !capability.canEdit || saving || pendingJob) { info.revert(); return; }
      if (!window.confirm(`将“${split(source.title)[0]}”改至 ${dt(source.start).plus({ days }).toISODate()}？`)) { info.revert(); return; }
      const patch = { version: source.version, start: dt(source.start).plus({ days }).toISO() };
      if (source.allDay) patch.start = dt(source.start).plus({ days }).toISODate();
      if (source.end) patch.end = source.allDay
        ? dt(source.end).plus({ days }).toISODate() : dt(source.end).plus({ days }).toISO();
      info.revert();
      publish(`/events/${encodeURIComponent(source.uid)}`, "PATCH", patch).catch((error) => message(error.message, true));
    },
  });
  for (const category of preferences.categories) {
    const label = node("label", "", `category-option category-${category.id}`);
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = category.id;
    checkbox.checked = settings.categories.includes(category.id);
    checkbox.addEventListener("change", () => {
      settings.categories = [...$("#category-list").querySelectorAll("input:checked")].map((input) => input.value);
      saveSettings();
      refresh();
    });
    const count = node("span", "0", "category-count");
    count.dataset.count = category.id;
    count.setAttribute("aria-hidden", "true");
    label.append(checkbox, node("span", category.label, "category-label"), count);
    $("#category-list").append(label);
  }
  $("#density").value = settings.density;
  for (const key of ["density"]) $(`#${key}`).addEventListener("change", () => {
    settings[key] = $(`#${key}`).value;
    saveSettings();
    applyAppearance();
    calendar.updateSize();
  });
  $("#categories-all").addEventListener("click", () => {
    settings.categories = activeCategories.map((category) => category.id);
    for (const input of $("#category-list").querySelectorAll("input")) input.checked = settings.categories.includes(input.value);
    saveSettings();
    refresh();
  });
  $("#jump-date").addEventListener("change", () => {
    if (!$("#jump-date").value) return;
    let date = dt($("#jump-date").value);
    if (calendar.view.type === "quarter") date = date.startOf("quarter");
    calendar.gotoDate(date.toISODate());
  });
  calendar.render();

  function changeView(view) {
    let date = dt(calendar.getDate().toISOString());
    if (view === "quarter") date = date.startOf("quarter");
    calendar.changeView(view, date.toISODate());
  }
  $("#views").addEventListener("click", (event) => {
    const view = event.target.closest("[data-view]")?.dataset.view;
    if (viewNames[view]) changeView(view);
  });
  $("#prev").addEventListener("click", () => calendar.prev());
  $("#next").addEventListener("click", () => calendar.next());
  $("#today").addEventListener("click", () => {
    calendar.gotoDate(DateTime.now().setZone(zone).startOf(calendar.view.type === "quarter" ? "quarter" : "day").toISODate());
  });
  $("#search").addEventListener("input", refresh);
  $("#access-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (apiMode) return;
    if ($("#access-password").value !== "betasdc") { message("密码不正确。", true); return; }
    unlocked = true;
    try { sessionStorage.setItem("beta-calendar-unlocked", "true"); } catch {}
    $("#access-password").value = "";
    refresh();
  });
  $("#access-lock").addEventListener("click", () => {
    unlocked = false;
    try { sessionStorage.removeItem("beta-calendar-unlocked"); } catch {}
    refresh();
  });

  function showDetail(event) {
    $("#detail").replaceChildren();
    const [zh, en] = split(event.title);
    $("#detail").append(node("h3", zh, "detail-title"), node("p", en, "english"), badges(event));
    for (const [label, value] of [
      ["时间", `${dt(event.start).toFormat("yyyy-MM-dd")} · ${timeText(event)}`],
      ["地点", event.location], ["说明", event.description],
      ["提醒", event.alarms?.length ? event.alarms.join("、") : ""],
    ]) {
      if (!value) continue;
      const row = node("div", "", "detail-row");
      row.append(node("span", label, "detail-label"), node("span", value));
      $("#detail").append(row);
    }
    for (const [label, url] of [["来源链接", event.sourceUrl], ["下载 ICS", event.url]]) {
      if (!url || !/^https?:\/\//i.test(url)) continue;
      const row = node("div", "", "detail-row");
      const link = node("a", label);
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      row.append(link);
      $("#detail").append(row);
    }
    if (event.recurring) $("#detail").append(node("p", "重复活动请通过日历 CLI 维护。", "detail-row"));
  }
  function openEvent(event, date) {
    if (saving || pendingJob) return;
    selected = event;
    form.reset();
    $("#form-error").textContent = "";
    $("#fields").hidden = true;
    $("#fields").disabled = true;
    $("#detail").hidden = !event;
    $("#save").hidden = true;
    $("#delete").hidden = !event || !capability.canEdit;
    $("#edit").hidden = !event || !capability.canEdit || event.recurring;
    $("#editor-title").textContent = event ? "活动详情" : "新增活动";
    if (event) showDetail(event);
    if (!editor.open) editor.showModal();
    if (!event) startEditing(date);
    lucide.createIcons();
  }
  function updateDateInputs() {
    for (const name of ["start", "end"]) {
      const input = field(name);
      const value = input.value;
      input.type = field("allDay").checked ? "date" : "datetime-local";
      input.value = field("allDay").checked ? value.slice(0, 10) : `${value.slice(0, 10)}T${name === "start" ? "09:00" : "10:00"}`;
    }
    $("#end-note").textContent = field("allDay").checked ? "结束日期不包含当天" : "北京时间";
  }
  function startEditing(date) {
    const event = selected;
    $("#detail").hidden = true;
    $("#fields").hidden = false;
    $("#fields").disabled = false;
    $("#save").hidden = false;
    $("#edit").hidden = true;
    const [titleZh, titleEn] = split(event?.title);
    const [locationZh, locationEn] = split(event?.location);
    for (const [name, value] of Object.entries({
      titleZh, titleEn, locationZh, locationEn, description: event?.description || "",
      sourceUrl: event?.sourceUrl || "",
      scope: event?.scope || (settings.categories.length === 1 ? settings.categories[0].split("-")[0] : "internal"),
      status: event?.status || (settings.categories.length === 1 ? settings.categories[0].split("-")[1] : "planned"),
    })) field(name).value = value;
    field("allDay").checked = event?.allDay ?? true;
    updateDateInputs();
    const start = event?.start || date || DateTime.now().setZone(zone).toISODate();
    field("start").value = field("allDay").checked ? start.slice(0, 10) : dt(start).toFormat("yyyy-MM-dd'T'HH:mm");
    const end = event?.end || dt(start).plus(field("allDay").checked ? { days: 1 } : { hours: 1 }).toISO();
    field("end").value = field("allDay").checked ? end.slice(0, 10) : dt(end).toFormat("yyyy-MM-dd'T'HH:mm");
    field("alarmMode").value = event ? "keep" : "clear";
    $("#alarm-value").hidden = true;
    field("titleZh").focus();
  }
  field("allDay").addEventListener("change", updateDateInputs);
  field("alarmMode").addEventListener("change", () => { $("#alarm-value").hidden = field("alarmMode").value !== "set"; });
  $("#create").addEventListener("click", () => openEvent(null));
  $("#edit").addEventListener("click", () => startEditing());
  $("#editor-close").addEventListener("click", () => { if (!saving) editor.close(); });
  editor.addEventListener("cancel", (event) => { if (saving) event.preventDefault(); });

  async function reload() {
    events = apiMode ? (await request("/events")).events
      : (await (await fetch("events-data.json", { cache: "no-store" })).json()).events;
    refresh();
  }
  async function publish(path, method, payload) {
    if (saving || pendingJob) throw new Error("上一项更改仍在发布，请先检查发布状态。");
    saving = true;
    for (const button of editor.querySelectorAll("button")) button.disabled = true;
    $("#form-error").textContent = "正在校验并发布…";
    message("正在校验并发布…");
    let job;
    try {
      pendingJob = crypto.randomUUID().replaceAll("-", "");
      try { localStorage.setItem(`beta-calendar-job-${capability.user.id}`, pendingJob); } catch {}
      job = await request(path, { method, body: JSON.stringify(payload), headers: { "Idempotency-Key": pendingJob } });
      // Keep a single job id: a slow publication must never be submitted twice.
      let result;
      for (let attempt = 0; attempt < 180; attempt++) {
        result = await request(`/jobs/${job.id}`);
        if (result.state === "succeeded") {
          clearPending();
          editor.close();
          await reload();
          message(`已保存并发布 · ${result.commit.slice(0, 8)}`);
          return;
        }
        if (result.state === "failed") { clearPending(); throw new Error(result.error); }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      throw new Error(`发布仍在处理中（${job.id}），请刷新查看结果，勿重复提交。`);
    } catch (error) {
      if (!job && error.status && error.status < 500) clearPending();
      $("#form-error").textContent = error.message;
      throw error;
    } finally {
      saving = false;
      for (const button of editor.querySelectorAll("button")) button.disabled = false;
      $("#save").disabled = Boolean(pendingJob);
      $("#resume").hidden = !pendingJob;
    }
  }
  function clearPending() {
    pendingJob = null;
    $("#resume").hidden = true;
    $("#save").disabled = false;
    try { localStorage.removeItem(`beta-calendar-job-${capability.user.id}`); } catch {}
  }
  $("#resume").addEventListener("click", async () => {
    if (!pendingJob || saving) return;
    try {
      const job = await request(`/jobs/${pendingJob}`);
      if (job.state === "succeeded") {
        clearPending();
        editor.close();
        await reload();
        message(`已保存并发布 · ${job.commit.slice(0, 8)}`);
      } else if (job.state === "failed") {
        clearPending();
        $("#form-error").textContent = job.error;
        message(job.error, true);
      } else message("发布仍在处理中，稍后可再次检查。");
    } catch (error) {
      if (error.status === 404) {
        clearPending();
        message("服务器未收到该发布请求，可重新保存。", true);
      } else message(error.message, true);
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving || !capability.canEdit) return;
    if (Boolean(field("locationZh").value.trim()) !== Boolean(field("locationEn").value.trim())) {
      $("#form-error").textContent = "地点请同时填写中文和英文，或同时留空。"; return;
    }
    const payload = {
      title: `${field("titleZh").value.trim()} / ${field("titleEn").value.trim()}`,
      location: field("locationZh").value.trim() ? `${field("locationZh").value.trim()} / ${field("locationEn").value.trim()}` : "",
      scope: field("scope").value, status: field("status").value, start: field("start").value,
      end: field("end").value, description: field("description").value, sourceUrl: field("sourceUrl").value,
      alarmMode: field("alarmMode").value,
    };
    if (payload.alarmMode === "set") payload.alarmMinutes = Number(field("alarmMinutes").value);
    if (selected) payload.version = selected.version;
    try { await publish(selected ? `/events/${encodeURIComponent(selected.uid)}` : "/events", selected ? "PATCH" : "POST", payload); }
    catch (error) { message(error.message, true); }
  });
  $("#delete").addEventListener("click", async () => {
    if (!selected || !window.confirm(`删除“${split(selected.title)[0]}”？`)) return;
    try { await publish(`/events/${encodeURIComponent(selected.uid)}`, "DELETE", { version: selected.version }); }
    catch (error) { message(error.message, true); }
  });

  async function initialize() {
    try {
      const configResponse = await fetch("calendar-config.json", { cache: "no-store" });
      if (!configResponse.ok) throw new Error("日历配置加载失败。");
      const config = await configResponse.json();
      if (config.api) {
        capability = await request("/session");
        csrf = capability.csrf_token;
        apiMode = true;
        guestMode = !capability.canViewAll;
        unlocked = Boolean(capability.canViewAll);
        if (guestMode) {
          activeCategories = preferences.categories.filter((category) => category.id === "public-planned");
          settings.categories = ["public-planned"];
          for (const input of $("#category-list").querySelectorAll("input")) {
            input.checked = input.value === "public-planned";
            input.closest("label").hidden = input.value !== "public-planned";
          }
        }
      }
      $("h1").textContent = guestMode ? "公开日历" : "成员日历";
      if ($("#account-name")) $("#account-name").textContent = capability.user?.username || (guestMode ? "游客" : "");
      if ($("#login")) {
        $("#login").hidden = !apiMode || Boolean(capability.user);
        $("#login").href = capability.loginUrl || "/login";
      }
      if ($("#logout")) $("#logout").hidden = !apiMode || !capability.user;
      $("#create").hidden = !capability.canEdit;
      if (capability.user) {
        try { pendingJob = localStorage.getItem(`beta-calendar-job-${capability.user.id}`); } catch {}
        $("#resume").hidden = !pendingJob;
      }
      await reload();
    } catch (error) { message(error.message || "日历加载失败，请刷新重试。", true); }
    lucide.createIcons();
  }
  $("#logout")?.addEventListener("click", async () => {
    if ((saving || pendingJob) && !window.confirm("有更改尚待确认发布结果。退出不会撤回已提交的更改，再次登录可查看结果。仍要退出？")) return;
    if (editor.open && !$("#fields").hidden && !saving && !pendingJob
        && !window.confirm("退出将放弃尚未保存的表单内容。仍要退出？")) return;
    $("#logout").disabled = true;
    try {
      await CalendarAccount.logout();
      try { sessionStorage.removeItem("beta-calendar-unlocked"); } catch {}
      events = [];
      for (const source of calendar.getEventSources()) source.remove();
      $("#agenda").replaceChildren();
      editor.close();
      location.replace("/login");
    } catch (error) {
      message(error.message || "无法连接服务器，退出未完成，请重试。", true);
      $("#logout").disabled = false;
    }
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && apiMode) location.reload();
  });
  document.addEventListener("beta-session", event => {
    if (apiMode && capability.user && !event.detail.user) location.reload();
  });
  initialize();
})();
