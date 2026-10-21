"use strict";

((root) => {
  function isBilingual(value) {
    const separator = value.indexOf(" / ");
    return separator >= 0 && /[\u4e00-\u9fff]/.test(value.slice(0, separator))
      && /[A-Za-z]/.test(value.slice(separator + 3));
  }
  const api = { isBilingual };
  root.CalendarValidation = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
