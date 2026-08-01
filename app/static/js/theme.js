const THEME_STORAGE_KEY = "habit-tracker.color-theme-v1";
const THEMES = new Set(["system", "light", "dark"]);

function savedTheme() {
  try {
    const theme = window.localStorage.getItem(THEME_STORAGE_KEY) || "system";
    return THEMES.has(theme) ? theme : "system";
  } catch {
    return "system";
  }
}

function applyTheme(theme) {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
    document.documentElement.style.colorScheme = "light dark";
    return;
  }
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
}

function storeTheme(theme) {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The selected theme still applies for the current page when storage is unavailable.
  }
}

const initialTheme = savedTheme();
applyTheme(initialTheme);

window.addEventListener("DOMContentLoaded", () => {
  const options = document.querySelector("[data-theme-options]");
  if (!options) {
    return;
  }
  const selected = options.querySelector(`input[value="${initialTheme}"]`);
  if (selected instanceof HTMLInputElement) {
    selected.checked = true;
  }
  options.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement) || !THEMES.has(event.target.value)) {
      return;
    }
    storeTheme(event.target.value);
    applyTheme(event.target.value);
  });
});
