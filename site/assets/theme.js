// Dark/light/system theme toggle, shared by every page. The inline
// THEME_INIT_SCRIPT in <head> (see build_site.py) already applies any
// saved choice before first paint, so there's no flash of the wrong
// theme; this file just owns the toggle button's behavior.
(function () {
  function current() {
    return document.documentElement.getAttribute("data-theme") || "system";
  }
  function apply(theme) {
    if (theme === "dark" || theme === "light") {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }
  function next(theme) {
    if (theme === "system") return "light";
    if (theme === "light") return "dark";
    return "system";
  }
  var ICONS = { light: "☀️", dark: "🌙", system: "🖥️" };
  var LABELS = { light: "Light", dark: "Dark", system: "Auto" };
  function paint(btn, theme) {
    btn.textContent = ICONS[theme] + " " + LABELS[theme];
    btn.setAttribute("aria-label", "Color theme: " + LABELS[theme] + ". Click to change.");
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (!btn) return;
    var theme = current();
    paint(btn, theme);
    btn.addEventListener("click", function () {
      theme = next(theme);
      apply(theme);
      try { localStorage.setItem("theme", theme); } catch (e) {}
      paint(btn, theme);
    });
  });
})();
