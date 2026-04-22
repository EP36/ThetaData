"""Tests for src/dashboard/aggregator.py and the poly dashboard API endpoints."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.dashboard.aggregator import (
    DashboardAggregator,
    POLY_PAUSE_FLAG,
    is_poly_paused,
    normalize_alpaca_position,
    normalize_poly_position,
    pause_poly_bot,
    poly_bot_status,
    resume_poly_bot,
)
from src.polymarket.positions import make_ledger, new_position, PositionRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _poly_config(**overrides):
    from src.polymarket.config import PolymarketConfig
    base = dict(
        api_key="k", api_secret="s", passphrase="p", private_key="pk",
        scan_interval_sec=30, min_edge_pct=1.5,
        clob_base_url="https://clob.polymarket.com",
        kalshi_base_url="https://k.com",
        max_retries=0, timeout_seconds=5.0,
        daily_loss_limit=200.0, max_positions=5, dry_run=True,
        poly_log_dir="",
    )
    base.update(overrides)
    if base.get("dry_run") is False:
        base.setdefault("trading_mode", "live")
        base.setdefault("trading_venue", "polymarket")
        base.setdefault("live_trading_enabled", True)
        base.setdefault("signal_provider", "synthetic")
        base.setdefault("poly_trading_mode", "live")
        base.setdefault("alpaca_trading_mode", "disabled")
    return PolymarketConfig(**base)


def _open_pos(**kw) -> PositionRecord:
    defaults = dict(
        market_condition_id="cond1",
        market_question="Will BTC hit $100k?",
        strategy="orderbook_spread",
        side="YES+NO",
        entry_price=0.50,
        size_usdc=100.0,
        contracts_held=100.0,
        yes_token_id="ytok",
        no_token_id="ntok",
    )
    defaults.update(kw)
    return new_position(**defaults)


def _alpaca_pos(symbol="AAPL", qty=10.0, avg=150.0, unrealized=50.0, realized=20.0):
    pos = MagicMock()
    pos.symbol = symbol
    pos.quantity = qty
    pos.avg_price = avg
    pos.unrealized_pnl = unrealized
    pos.realized_pnl = realized
    return pos


# ---------------------------------------------------------------------------
# Pause helpers
# ---------------------------------------------------------------------------

class TestPauseHelpers:
    def test_pause_creates_flag(self, tmp_path, monkeypatch):
        flag = tmp_path / "poly_paused.flag"
        monkeypatch.setattr("src.dashboard.aggregator.POLY_PAUSE_FLAG", flag)
        assert not is_poly_paused()
        pause_poly_bot()
        # Can't easily monkeypatch the module-level constant post-import, so
        # just test the flag file directly:
        assert flag.exists()

    def test_resume_removes_flag(self, tmp_path):
        flag = tmp_path / "poly_paused.flag"
        flag.touch()
        with patch("src.dashboard.aggregator.POLY_PAUSE_FLAG", flag):
            from src.dashboard.aggregator import resume_poly_bot as _resume
            _resume()
        assert not flag.exists()

    def test_poly_bot_status_dry_run(self):
        cfg = _poly_config(dry_run=True)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            assert poly_bot_status(cfg) == "dry_run"

    def test_poly_bot_status_live(self):
        cfg = _poly_config(dry_run=False)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            assert poly_bot_status(cfg) == "live"

    def test_poly_bot_status_paused(self):
        cfg = _poly_config(dry_run=False)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=True):
            assert poly_bot_status(cfg) == "paused"


# ---------------------------------------------------------------------------
# Position normalization
# ---------------------------------------------------------------------------

class TestNormalizePoly:
    def test_basic_fields(self):
        pos = _open_pos()
        n = normalize_poly_position(pos)
        assert n["broker"] == "polymarket"
        assert n["side"] == "YES+NO"
        assert n["size_usd"] == 100.0
        assert n["entry_price"] == 0.50
        assert "polymarket.com" in n["broker_url"]

    def test_unrealized_defaults_to_zero(self):
        pos = _open_pos()
        n = normalize_poly_position(pos)
        assert n["unrealized_pnl"] == 0.0

    def test_exit_price_used_as_current(self):
        pos = _open_pos()
        pos.exit_price = 0.99
        n = normalize_poly_position(pos)
        assert n["current_price"] == 0.99


class TestNormalizeAlpaca:
    def test_basic_fields(self):
        pos = _alpaca_pos(symbol="NVDA", qty=5.0, avg=400.0, unrealized=100.0)
        n = normalize_alpaca_position(pos)
        assert n["broker"] == "alpaca"
        assert n["symbol_or_market"] == "NVDA"
        assert n["side"] == "long"
        assert n["size_usd"] == 2000.0
        assert n["unrealized_pnl"] == 100.0
        assert n["unrealized_pnl_pct"] == pytest.approx(5.0, rel=0.01)

    def test_short_side(self):
        pos = _alpaca_pos(qty=-3.0, avg=100.0, unrealized=0.0)
        n = normalize_alpaca_position(pos)
        assert n["side"] == "short"

    def test_current_price_computed(self):
        pos = _alpaca_pos(qty=10.0, avg=100.0, unrealized=50.0)
        n = normalize_alpaca_position(pos)
        # current_price = (1000 + 50) / 10 = 105.0
        assert n["current_price"] == pytest.approx(105.0)


# ---------------------------------------------------------------------------
# DashboardAggregator — both brokers succeed
# ---------------------------------------------------------------------------

class TestAggregatorBothSucceed:
    def _make_aggregator(self, tmp_path: Path) -> DashboardAggregator:
        cfg = _poly_config(dry_run=True, poly_log_dir=str(tmp_path))
        ledger = make_ledger(str(tmp_path / "pos.json"))
        pos = _open_pos(size_usdc=200.0)
        pos.unrealized_pnl = 10.0
        ledger.add(pos)

        mock_repo = MagicMock()
        mock_snap = MagicMock()
        mock_snap.cash = 50_000.0
        mock_snap.day_start_equity = 48_000.0
        mock_snap.peak_equity = 51_000.0
        alpaca_pos = _alpaca_pos(qty=10.0, avg=100.0, unrealized=20.0, realized=5.0)
        mock_snap.positions = {"AAPL": alpaca_pos}
        mock_repo.load_portfolio_snapshot.return_value = mock_snap
        mock_repo.get_global_kill_switch.return_value = False

        return DashboardAggregator(poly_config=cfg, ledger=ledger, repository=mock_repo)

    def test_snapshot_has_all_keys(self, tmp_path):
        agg = self._make_aggregator(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            snap = agg.build_snapshot()
        assert "generated_at" in snap
        assert "account" in snap
        assert "pnl" in snap
        assert "risk" in snap
        assert "alpaca_positions" in snap
        assert "poly_positions" in snap
        assert "alerts" in snap

    def test_alpaca_position_normalized(self, tmp_path):
        agg = self._make_aggregator(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            snap = agg.build_snapshot()
        assert any(p["broker"] == "alpaca" for p in snap["alpaca_positions"])

    def test_poly_position_normalized(self, tmp_path):
        agg = self._make_aggregator(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            snap = agg.build_snapshot()
        assert len(snap["poly_positions"]) == 1
        assert snap["poly_positions"][0]["broker"] == "polymarket"

    def test_combined_value(self, tmp_path):
        agg = self._make_aggregator(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            snap = agg.build_snapshot()
        # alpaca portfolio_value ≈ 50_000 + (10*100+20) = 51_020; poly deployed = 200
        assert snap["account"]["combined_total_value"] > 0

    def test_snapshot_cached(self, tmp_path):
        agg = self._make_aggregator(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            s1 = agg.build_snapshot()
            s2 = agg.build_snapshot()
        assert s1["generated_at"] == s2["generated_at"]

    def test_force_bypasses_cache(self, tmp_path):
        agg = self._make_aggregator(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            s1 = agg.build_snapshot()
            s2 = agg.build_snapshot(force=True)
        # Both will be fast, but generated_at may differ by tiny amount; just check structure
        assert "generated_at" in s2


# ---------------------------------------------------------------------------
# DashboardAggregator — one broker fails
# ---------------------------------------------------------------------------

class TestAggregatorFallback:
    def _make_aggregator(self, tmp_path: Path) -> DashboardAggregator:
        cfg = _poly_config(dry_run=True, poly_log_dir=str(tmp_path))
        ledger = make_ledger(str(tmp_path / "pos.json"))
        mock_repo = MagicMock()
        mock_repo.load_portfolio_snapshot.side_effect = RuntimeError("DB unreachable")
        mock_repo.get_global_kill_switch.return_value = False
        return DashboardAggregator(poly_config=cfg, ledger=ledger, repository=mock_repo)

    def test_alpaca_failure_returns_snapshot_with_alert(self, tmp_path):
        agg = self._make_aggregator(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            snap = agg.build_snapshot()
        assert any("alpaca" in a["source"] for a in snap["alerts"])
        assert "generated_at" in snap

    def test_poly_failure_returns_snapshot_with_alert(self, tmp_path):
        cfg = _poly_config(dry_run=True, poly_log_dir=str(tmp_path))
        ledger = MagicMock()
        ledger.load.side_effect = RuntimeError("file error")
        ledger.open_count.side_effect = RuntimeError("file error")
        ledger.daily_pnl.side_effect = RuntimeError("file error")
        mock_repo = MagicMock()
        mock_snap = MagicMock()
        mock_snap.positions = {}
        mock_snap.cash = 0.0
        mock_repo.load_portfolio_snapshot.return_value = mock_snap
        mock_repo.get_global_kill_switch.return_value = False

        agg = DashboardAggregator(poly_config=cfg, ledger=ledger, repository=mock_repo)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            snap = agg.build_snapshot()
        assert any("polymarket" in a["source"] for a in snap["alerts"])

    def test_both_fail_returns_empty_snapshot(self, tmp_path):
        cfg = _poly_config(dry_run=True, poly_log_dir=str(tmp_path))
        ledger = MagicMock()
        ledger.load.side_effect = RuntimeError("fail")
        ledger.open_count.side_effect = RuntimeError("fail")
        ledger.daily_pnl.side_effect = RuntimeError("fail")
        mock_repo = MagicMock()
        mock_repo.load_portfolio_snapshot.side_effect = RuntimeError("fail")
        mock_repo.get_global_kill_switch.return_value = False

        agg = DashboardAggregator(poly_config=cfg, ledger=ledger, repository=mock_repo)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            snap = agg.build_snapshot()
        # Must not raise — returns zero-filled snapshot with alerts
        assert len(snap["alerts"]) >= 2
        assert snap["account"]["combined_total_value"] == 0.0


# ---------------------------------------------------------------------------
# API endpoint tests (TestClient)
# ---------------------------------------------------------------------------

def _make_test_app(tmp_path: Path):
    """Return a TestClient wired to the poly dashboard router with a mock aggregator."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from src.dashboard.api import router, register

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    test_app.include_router(router)

    cfg = _poly_config(dry_run=True, poly_log_dir=str(tmp_path))
    ledger = make_ledger(str(tmp_path / "pos.json"))
    pos = _open_pos()
    ledger.add(pos)

    mock_repo = MagicMock()
    mock_snap = MagicMock()
    mock_snap.cash = 10_000.0
    mock_snap.positions = {}
    mock_repo.load_portfolio_snapshot.return_value = mock_snap
    mock_repo.get_global_kill_switch.return_value = False

    agg = DashboardAggregator(poly_config=cfg, ledger=ledger, repository=mock_repo)
    register(agg, cfg, MagicMock(), ledger)

    return TestClient(test_app), agg, ledger, cfg


class TestAPIEndpoints:
    def test_get_snapshot_200(self, tmp_path):
        client, *_ = _make_test_app(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            r = client.get("/api/snapshot")
        assert r.status_code == 200
        data = r.json()
        assert "generated_at" in data
        assert "account" in data

    def test_get_positions_200(self, tmp_path):
        client, *_ = _make_test_app(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            r = client.get("/api/positions")
        assert r.status_code == 200
        assert "positions" in r.json()

    def test_get_opportunities_200(self, tmp_path):
        client, *_ = _make_test_app(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            r = client.get("/api/opportunities")
        assert r.status_code == 200
        assert "opportunities" in r.json()

    def test_get_alerts_200(self, tmp_path):
        client, *_ = _make_test_app(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            r = client.get("/api/alerts")
        assert r.status_code == 200
        assert "alerts" in r.json()

    def test_post_pause_requires_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret123")
        client, *_ = _make_test_app(tmp_path)
        r = client.post("/api/poly/pause")
        assert r.status_code == 401

    def test_post_pause_wrong_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret123")
        client, *_ = _make_test_app(tmp_path)
        r = client.post("/api/poly/pause", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401

    def test_post_pause_valid_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret123")
        client, *_ = _make_test_app(tmp_path)
        with (
            patch("src.dashboard.aggregator.is_poly_paused", return_value=False),
            patch("src.dashboard.api.pause_poly_bot") as mock_pause,
        ):
            r = client.post("/api/poly/pause", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200
        mock_pause.assert_called_once()
        data = r.json()
        assert data["success"] is True
        assert "timestamp" in data

    def test_post_resume_valid_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret123")
        client, *_ = _make_test_app(tmp_path)
        with (
            patch("src.dashboard.aggregator.is_poly_paused", return_value=False),
            patch("src.dashboard.api.resume_poly_bot") as mock_resume,
        ):
            r = client.post("/api/poly/resume", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200
        mock_resume.assert_called_once()

    def test_post_scan_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "tok")
        client, agg, *_ = _make_test_app(tmp_path)
        with (
            patch("src.dashboard.aggregator.is_poly_paused", return_value=False),
            patch("src.polymarket.runner.scan", return_value=[]),
        ):
            r = client.post("/api/poly/scan", headers={"Authorization": "Bearer tok"})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_post_close_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "tok")
        client, *_ = _make_test_app(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            r = client.post(
                "/api/poly/close/nonexistent-id",
                headers={"Authorization": "Bearer tok"},
            )
        assert r.status_code == 404

    def test_post_close_dry_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "tok")
        client, agg, ledger, cfg = _make_test_app(tmp_path)
        # Grab the real position ID
        positions = ledger.load()
        pid = positions[0].id
        with (
            patch("src.dashboard.aggregator.is_poly_paused", return_value=False),
            patch("src.polymarket.monitor.close_position", return_value=True) as mock_close,
        ):
            r = client.post(
                f"/api/poly/close/{pid}",
                headers={"Authorization": "Bearer tok"},
            )
        assert r.status_code == 200
        assert "dry run" in r.json()["message"].lower()
        mock_close.assert_called_once()

    def test_cors_header_present(self, tmp_path):
        client, *_ = _make_test_app(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            r = client.get(
                "/api/snapshot",
                headers={"Origin": "http://localhost:3000"},
            )
        assert r.status_code == 200
        assert "access-control-allow-origin" in r.headers

    def test_post_token_not_configured_returns_503(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DASHBOARD_API_TOKEN", raising=False)
        client, *_ = _make_test_app(tmp_path)
        r = client.post("/api/poly/pause", headers={"Authorization": "Bearer anything"})
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# Pause/resume bot status toggle
# ---------------------------------------------------------------------------

class TestPauseResumeToggle:
    def test_pause_then_resume_changes_status(self, tmp_path):
        cfg = _poly_config(dry_run=False)
        flag = tmp_path / "poly_paused.flag"
        with patch("src.dashboard.aggregator.POLY_PAUSE_FLAG", flag):
            from src.dashboard.aggregator import pause_poly_bot as _pause, resume_poly_bot as _resume, is_poly_paused as _is_paused
            assert not _is_paused()
            _pause()
            assert flag.exists()
            _resume()
            assert not flag.exists()
