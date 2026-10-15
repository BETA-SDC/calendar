"use strict";

((root) => {
  const categories = [
    { id: "public-planned", label: "公开活动", scope: "public", status: "planned" },
    { id: "internal-planned", label: "内部事项", scope: "internal", status: "planned" },
    { id: "public-tentative", label: "公开待定", scope: "public", status: "tentative" },
    { id: "internal-tentative", label: "内部待定", scope: "internal", status: "tentative" },
  ];
  function normalize(value) {
    return {
      categories: Array.isArray(value?.categories)
        ? categories.filter((category) => value.categories.includes(category.id)).map((category) => category.id)
        : categories.map((category) => category.id),
      theme: ["system", "light", "dark"].includes(value?.theme) ? value.theme : "system",
      density: ["comfortable", "compact"].includes(value?.density) ? value.density : "comfortable",
    };
  }
  function categoryId(event) { return `${event.scope}-${event.status}`; }
  function matches(event, selected, query = "") {
    const text = `${event.title || ""} ${event.location || ""} ${event.description || ""}`.toLowerCase();
    return selected.includes(categoryId(event))
      && query.toLowerCase().trim().split(/\s+/).filter(Boolean).every((word) => text.includes(word));
  }
  function theme(mode, prefersDark) { return mode === "system" ? (prefersDark ? "dark" : "light") : mode; }
  const api = { categories, normalize, categoryId, matches, theme };
  root.CalendarPreferences = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
