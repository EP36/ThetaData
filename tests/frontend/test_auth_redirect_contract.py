"""Contract tests for frontend auth redirect and login route handling."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_login_route_is_public_and_normalized() -> None:
    route_source = _read("apps/web/lib/auth/routes.ts")
    assert 'const AUTH_PATHS = ["/login"]' in route_source
    assert "normalizePathname(pathname: string)" in route_source
    assert "isAuthPath(pathname: string)" in route_source
    assert "if (isAuthPath(normalized))" in route_source


def test_login_next_parameter_is_sanitized_to_prevent_loops() -> None:
    route_source = _read("apps/web/lib/auth/routes.ts")
    assert "sanitizeNextPath(" in route_source
    assert "if (isAuthPath(normalizedPath))" in route_source
    assert 'const safeFallback = normalizePathname(fallback) || "/dashboard";' in route_source
    assert "candidate.startsWith(\"//\")" in route_source


def test_app_shell_treats_login_as_auth_route_and_keeps_logout_clean() -> None:
    shell_source = _read("apps/web/components/auth/app-shell.tsx")
    assert "const authPath = useMemo(() => isAuthPath(pathname), [pathname]);" in shell_source
    assert "if (authPath) {\n    return <main className=\"min-h-screen\">{children}</main>;" in shell_source
    assert "if (pathname === \"/login\")" not in shell_source
    assert 'router.replace("/login");' in shell_source


def test_login_page_uses_sanitized_next_target() -> None:
    login_source = _read("apps/web/app/login/page.tsx")
    assert 'import { sanitizeNextPath } from "@/lib/auth/routes";' in login_source
    assert 'return sanitizeNextPath(searchParams.get("next"), "/dashboard");' in login_source
    assert 'router.replace(nextPath);' in login_source


def test_protected_routes_still_redirect_with_valid_next_target() -> None:
    shell_source = _read("apps/web/components/auth/app-shell.tsx")
    route_source = _read("apps/web/lib/auth/routes.ts")
    assert "router.replace(loginPath(pathname));" in shell_source
    assert "router.replace(loginPath(pathname, reason));" in shell_source
    assert 'params.set("next", redirectTarget);' in route_source
