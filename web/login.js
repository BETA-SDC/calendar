"use strict";
(() => {
  const form = document.querySelector("#login-form");
  const error = document.querySelector("#login-error");
  const submit = document.querySelector("#login-submit");
  let csrf = "";
  async function session() {
    const body = await CalendarAccount.session();
    csrf = body.csrf_token;
    if (body.user) location.replace("/calendar/");
  }
  session().catch((failure) => { error.textContent = failure.message; });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    error.textContent = "";
    try {
      if (!csrf) await session();
      const response = await fetch("/api/login", {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ identifier: form.elements.identifier.value.trim(),
          password: form.elements.password.value }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "登录失败，请重试。");
      form.elements.password.value = "";
      location.replace("/calendar/");
    } catch (failure) {
      error.textContent = failure.message || "无法连接服务器，请稍后重试。";
    } finally { submit.disabled = false; }
  });
})();
