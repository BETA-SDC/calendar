const test = require("node:test");
const assert = require("node:assert/strict");
const preferences = require("../web/calendar-preferences.js");

test("categories default to all four, invalid preferences are sanitized", () => {
  assert.equal(preferences.normalize(null).categories.length, 4);
  assert.deepEqual(preferences.normalize({categories: []}).categories, []);
  assert.deepEqual(preferences.normalize({categories: ["internal-planned", "bad", "internal-planned"]}).categories, ["internal-planned"]);
  assert.equal(preferences.normalize({theme: "bad", density: "bad"}).theme, "system");
});
test("checkbox filters and search intersect without hiding other selected categories", () => {
  const event = {scope: "internal", status: "planned", title: "会议 / Meeting", location: "E12"};
  assert.equal(preferences.categoryId(event), "internal-planned");
  assert.equal(preferences.matches(event, ["internal-planned", "public-planned"], "meeting e12"), true);
  assert.equal(preferences.matches(event, ["public-planned"], ""), false);
  assert.equal(preferences.matches(event, [], ""), false);
  assert.equal(preferences.matches(event, ["internal-planned"], "unmatched"), false);
});
test("system follows OS; explicit themes remain stable", () => {
  assert.equal(preferences.theme("system", true), "dark");
  assert.equal(preferences.theme("system", false), "light");
  assert.equal(preferences.theme("light", true), "light");
  assert.equal(preferences.theme("dark", false), "dark");
});
