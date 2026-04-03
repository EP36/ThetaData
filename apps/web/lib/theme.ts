export const THEME_STORAGE_KEY = "theta-theme-preference";
export const THEME_DARK_QUERY = "(prefers-color-scheme: dark)";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const VALID_PREFERENCES: ThemePreference[] = ["light", "dark", "system"];

export function parseThemePreference(
  value: string | null | undefined
): ThemePreference {
  if (value && VALID_PREFERENCES.includes(value as ThemePreference)) {
    return value as ThemePreference;
  }
  return "system";
}

export function resolveTheme(
  preference: ThemePreference,
  prefersDark: boolean
): ResolvedTheme {
  if (preference === "system") {
    return prefersDark ? "dark" : "light";
  }
  return preference;
}

export function buildThemeInitScript(): string {
  return `(function () {
  var storageKey = "${THEME_STORAGE_KEY}";
  var query = "${THEME_DARK_QUERY}";
  var root = document.documentElement;
  var preference = "system";
  try {
    var stored = window.localStorage.getItem(storageKey);
    if (stored === "light" || stored === "dark" || stored === "system") {
      preference = stored;
    }
  } catch (_error) {}
  var prefersDark = false;
  try {
    prefersDark = window.matchMedia(query).matches;
  } catch (_error) {}
  var resolved = preference === "system" ? (prefersDark ? "dark" : "light") : preference;
  root.dataset.themePreference = preference;
  root.dataset.theme = resolved;
  root.classList.toggle("dark", resolved === "dark");
  root.style.colorScheme = resolved;
})();`;
}
