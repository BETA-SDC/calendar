"use strict";

// This is a lightweight UI gate for non-sensitive events, not server authentication.
const accessPassword = "betasdc";
const accessStorageKey = "beta-calendar-unlocked";
let accessUnlocked = false;
try {
  accessUnlocked = sessionStorage.getItem(accessStorageKey) === "true";
} catch {
  // Keep the current page usable when browser storage is unavailable.
}

window.calendarAccess = {
  isUnlocked: () => accessUnlocked,
  requiresPassword: (scope, status) => scope === "internal" || status !== "planned",
};

const accessForm = document.querySelector("#access-form");
const accessFields = document.querySelector("#access-fields");
const accessInput = document.querySelector("#access-password");
const accessMessage = document.querySelector("#access-message");
const accessLock = document.querySelector("#access-lock");

function renderAccess() {
  accessFields.hidden = accessUnlocked;
  accessLock.hidden = !accessUnlocked;
  accessMessage.textContent = accessUnlocked
    ? "内部、待定及全部状态已解锁。"
    : "内部、待定及全部状态需要访问密码。";
}

function setAccess(unlocked) {
  accessUnlocked = unlocked;
  try {
    if (unlocked) sessionStorage.setItem(accessStorageKey, "true");
    else sessionStorage.removeItem(accessStorageKey);
  } catch {
    // The in-memory state still permits access on this page.
  }
  accessInput.value = "";
  accessInput.removeAttribute("aria-invalid");
  renderAccess();
  window.dispatchEvent(new Event("calendar-access-change"));
}

accessForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (accessInput.value !== accessPassword) {
    accessInput.setAttribute("aria-invalid", "true");
    accessMessage.textContent = "密码不正确。";
    accessInput.focus();
    return;
  }
  setAccess(true);
});

accessLock.addEventListener("click", () => setAccess(false));
window.addEventListener("pageshow", () => {
  try {
    const unlocked = sessionStorage.getItem(accessStorageKey) === "true";
    if (unlocked !== accessUnlocked) setAccess(unlocked);
  } catch {
    // Keep the current state if storage is unavailable.
  }
});
renderAccess();
