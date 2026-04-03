"use client";

import { useTheme } from "@/components/theme/theme-provider";
import type { ThemePreference } from "@/lib/theme";

const OPTIONS: Array<{ value: ThemePreference; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" }
];

export function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();

  return (
    <div className="theme-toggle-wrap flex items-center gap-2 rounded-full border border-[var(--line)] bg-[var(--panel-soft)] px-3 py-1.5">
      <div className="leading-tight">
        <p className="text-[10px] uppercase tracking-[0.12em] text-[var(--muted)]">Theme</p>
        <p className="text-[10px] text-[var(--muted)]">Using {resolvedTheme}</p>
      </div>
      <label className="sr-only" htmlFor="theme-select">
        Color theme
      </label>
      <select
        id="theme-select"
        value={theme}
        onChange={(event) => setTheme(event.target.value as ThemePreference)}
        className="ui-select min-w-24 rounded-full px-2 py-1 text-xs font-semibold"
      >
        {OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
