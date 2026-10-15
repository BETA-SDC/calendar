"use strict";

(() => {
  const key = "beta-calendar-login-state";
  const incoming = new URL(document.currentScript.src).searchParams.get("state");
  let state;
  let expires;
  try {
    if (/^[a-f0-9]{64}$/.test(incoming || "")) {
      sessionStorage.setItem(key, JSON.stringify({ state: incoming, expires: Date.now() + 600000 }));
    }
    const saved = JSON.parse(sessionStorage.getItem(key) || "null");
    if (!saved || saved.expires < Date.now() || !/^[a-f0-9]{64}$/.test(saved.state)) return;
    state = saved.state;
    expires = saved.expires;
  } catch { return; }
  async function resume() {
    if (Date.now() > expires) return;
    try {
      const response = await fetch("/api/calendar/session", { cache: "no-store" });
      const body = await response.json();
      if (response.ok && body.user) {
        sessionStorage.removeItem(key);
        location.replace(`/api/calendar/auth/authorize?state=${encodeURIComponent(state)}`);
        return;
      }
    } catch {}
    if (document.visibilityState === "visible") window.setTimeout(resume, 2000);
    else document.addEventListener("visibilitychange", resume, { once: true });
  }
  resume();
})();
