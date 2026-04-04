"""Contract tests for frontend settings/auth/theme wiring."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_settings_navigation_replaces_top_nav_theme_control() -> None:
    nav_source = _read("apps/web/components/navigation/top-nav.tsx")
    assert '{ href: "/settings", label: "Settings" }' in nav_source
    assert "ThemeToggle" not in nav_source


def test_settings_route_is_protected_by_auth_shell() -> None:
    route_source = _read("apps/web/lib/auth/routes.ts")
    assert '"/login"' in route_source
    assert '"/"' in route_source
    assert '"/settings"' not in route_source


def test_theme_preference_persistence_contract_exists() -> None:
    theme_source = _read("apps/web/lib/theme.ts")
    assert "trauto-theme-preference" in theme_source
    assert "localStorage.getItem(storageKey)" in theme_source
    assert "root.dataset.themePreference = preference" in theme_source
    assert 'root.classList.toggle("dark", resolved === "dark")' in theme_source


def test_settings_page_uses_theme_and_password_change_api() -> None:
    settings_source = _read("apps/web/app/settings/page.tsx")
    assert "useTheme" in settings_source
    assert "changePassword" in settings_source
    assert "Current Password" in settings_source
    assert "Update Password" in settings_source
