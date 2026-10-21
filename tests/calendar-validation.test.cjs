const test = require("node:test");
const assert = require("node:assert/strict");
const { isBilingual } = require("../web/calendar-validation.js");

test("bilingual fields require Chinese before the first separator and English after it", () => {
  for (const value of ["会议 / Meeting", "H4-103 室 / Room H4-103", "中文 / English / More"]) {
    assert.equal(isBilingual(value), true, value);
  }
  for (const value of ["", "H4-103 / H4-103", "Meeting / Meeting", "中文 / 中文",
    " / English", "中文 / ", "English / 中文", "Meeting / 中文 / English", "中文/English"]) {
    assert.equal(isBilingual(value), false, value);
  }
});
