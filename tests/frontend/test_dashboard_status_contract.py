"""Contract tests for dashboard trading-status display wiring."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_dashboard_displays_split_trading_status_fields() -> None:
    dashboard_source = _read("apps/web/app/dashboard/page.tsx")
    assert "Signal Provider" in dashboard_source
    assert "Execution Venue" in dashboard_source
    assert "Polymarket Mode" in dashboard_source
    assert "Alpaca Mode" in dashboard_source


def test_status_badge_knows_polymarket_live_label() -> None:
    badge_source = _read("apps/web/components/dashboard/status-badge.tsx")
    assert 'polymarket_live: "Polymarket Live"' in badge_source
    assert 'polymarket_dry_run: "Polymarket Dry Run"' in badge_source
    assert 'paper_only_ready: "Alpaca Paper Ready"' in badge_source
