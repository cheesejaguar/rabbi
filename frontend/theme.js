(function () {
  "use strict";

  const STORAGE_KEY = "rebbe-theme";
  const MODES = ["system", "light", "dark"];
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  function storedPreference() {
    try {
      const value = window.localStorage.getItem(STORAGE_KEY);
      return MODES.includes(value) ? value : "system";
    } catch (_error) {
      return "system";
    }
  }

  function resolvedTheme(preference) {
    if (preference === "system") return media.matches ? "dark" : "light";
    return preference;
  }

  function applyTheme(preference, persist) {
    const safePreference = MODES.includes(preference) ? preference : "system";
    const resolved = resolvedTheme(safePreference);
    const root = document.documentElement;

    root.dataset.theme = resolved;
    root.dataset.themePreference = safePreference;
    root.style.colorScheme = resolved;

    if (persist) {
      try {
        window.localStorage.setItem(STORAGE_KEY, safePreference);
      } catch (_error) {
        // Theme selection still works when storage is unavailable.
      }
    }

    document.querySelectorAll("[data-theme-choice]").forEach((button) => {
      const isCurrent = button.dataset.themeChoice === safePreference;
      button.setAttribute("aria-pressed", String(isCurrent));
    });

    document.querySelectorAll("[data-theme-cycle]").forEach((button) => {
      button.dataset.mode = safePreference;
      button.setAttribute(
        "aria-label",
        `Theme: ${safePreference}. Activate to change theme.`
      );
      const label = button.querySelector("[data-theme-label]");
      if (label) label.textContent = safePreference;
    });

    window.dispatchEvent(
      new CustomEvent("rebbe-theme-change", {
        detail: { preference: safePreference, resolved },
      })
    );
  }

  function cycleTheme() {
    const current = document.documentElement.dataset.themePreference || storedPreference();
    const next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
    applyTheme(next, true);
  }

  function bindControls() {
    document.querySelectorAll("[data-theme-choice]").forEach((button) => {
      button.addEventListener("click", () => applyTheme(button.dataset.themeChoice, true));
    });
    document.querySelectorAll("[data-theme-cycle]").forEach((button) => {
      button.addEventListener("click", cycleTheme);
    });
    applyTheme(document.documentElement.dataset.themePreference || storedPreference(), false);
  }

  applyTheme(storedPreference(), false);
  document.addEventListener("DOMContentLoaded", bindControls, { once: true });
  media.addEventListener("change", () => {
    if ((document.documentElement.dataset.themePreference || "system") === "system") {
      applyTheme("system", false);
    }
  });

  window.RebbeTheme = { apply: applyTheme, cycle: cycleTheme, get: storedPreference };
})();
