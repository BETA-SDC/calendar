"use strict";

((root) => {
  async function read(response, fallback) {
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.error || fallback);
    return body;
  }
  async function session(fetcher = root.fetch) {
    const body = await read(await fetcher("/api/session", {
      credentials: "same-origin", cache: "no-store",
    }), "会话加载失败，请刷新重试。");
    if (!body || !Object.hasOwn(body, "user") || typeof body.csrf_token !== "string" || !body.csrf_token) {
      throw new Error("会话响应无效，请刷新重试。");
    }
    return body;
  }
  async function logout(fetcher = root.fetch) {
    const current = await session(fetcher);
    if (!current.user) return;
    const body = await read(await fetcher("/api/logout", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": current.csrf_token },
      body: "{}",
    }), "退出失败，请重试。");
    if (body?.user !== null || (await session(fetcher)).user) {
      throw new Error("登录会话尚未退出，请重试。");
    }
  }
  const api = { session, logout };
  root.CalendarAccount = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
