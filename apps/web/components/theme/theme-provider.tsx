"use client";

import type { ReactNode } from "react";
import { createContext, useContext, useEffect, useMemo, useState } from "react";

import {
  THEME_DARK_QUERY,
  THEME_STORAGE_KEY,
  parseThemePreference,
  resolveTheme,
  type ResolvedTheme,
  type ThemePreference
} from "@/lib/theme";

type ThemeContextValue = {
  theme: ThemePreference;
  resolvedTheme: ResolvedTheme;
  setTheme: (theme: ThemePreference) => void;
};

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

function applyResolvedTheme(theme: ThemePreference, resolvedTheme: ResolvedTheme): void {
  const root = document.documentElement;
  root.dataset.themePreference = theme;
  root.dataset.theme = resolvedTheme;
  root.classList.toggle("dark", resolvedTheme === "dark");
  root.style.colorScheme = resolvedTheme;
}

function detectSystemTheme(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia(THEME_DARK_QUERY).matches;
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemePreference>(() => {
    if (typeof document === "undefined") {
      return "system";
    }
    return parseThemePreference(document.documentElement.dataset.themePreference);
  });
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => {
    if (typeof document === "undefined") {
      return "light";
    }
    return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  });

  useEffect(() => {
    const mediaQuery =
      typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia(THEME_DARK_QUERY)
        : null;

    const applyTheme = (nextTheme: ThemePreference) => {
      const nextResolvedTheme = resolveTheme(nextTheme, detectSystemTheme());
      applyResolvedTheme(nextTheme, nextResolvedTheme);
      setResolvedTheme(nextResolvedTheme);
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
      } catch (_error) {
        // Ignore storage failures (private mode / blocked storage).
      }
    };

    applyTheme(theme);

    const handleSystemThemeChange = (event: MediaQueryListEvent) => {
      if (theme !== "system") {
        return;
      }
      const nextResolvedTheme: ResolvedTheme = event.matches ? "dark" : "light";
      applyResolvedTheme(theme, nextResolvedTheme);
      setResolvedTheme(nextResolvedTheme);
    };

    mediaQuery?.addEventListener("change", handleSystemThemeChange);
    return () => {
      mediaQuery?.removeEventListener("change", handleSystemThemeChange);
    };
  }, [theme]);

  const contextValue = useMemo(
    () => ({
      theme,
      resolvedTheme,
      setTheme
    }),
    [resolvedTheme, theme]
  );

  return <ThemeContext.Provider value={contextValue}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider.");
  }
  return context;
}
