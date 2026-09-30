(() => {
  const { t } = window.JobfindI18n;
  const storageKey = "jobfind-theme-preference";
  const root = document.documentElement;
  let preference = "dark";
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "light" || saved === "dark") preference = saved;
  } catch (_) {
    // Storage may be unavailable in private browsing.
  }

  function applyTheme() {
    const dark = preference === "dark";
    root.dataset.theme = dark ? "dark" : "light";
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#10141d" : "#f5f8f6");
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", t(dark ? "Helles Design einschalten" : "Dunkles Design einschalten"));
      button.title = t(dark ? "Helles Design einschalten" : "Dunkles Design einschalten");
      const label = button.querySelector(".theme-label");
      if (label) label.textContent = t(dark ? "Hell" : "Dunkel");
    });
  }

  function toggleTheme() {
    preference = preference === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(storageKey, preference);
    } catch (_) { /* Keep the setting for this page. */ }
    applyTheme();
  }

  applyTheme();
  document.addEventListener("DOMContentLoaded", () => {
    applyTheme();
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", toggleTheme);
    });
  });
})();
