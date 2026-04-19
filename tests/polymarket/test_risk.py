"""Tests for RiskGuard — one test per check, pass and fail cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.polymarket.config import PolymarketConfig
from src.polymarket.opportunities import Opportunity
from src.polymarket.positions import PositionsLedger, new_position
from src.polymarket.risk import RiskGuard


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_config(**overrides: Any) -> PolymarketConfig:
    defaults: dict[str, Any] = {
        "api_key": "k",
        "api_secret": "s",
        "passphrase": "p",
        "private_key": "pk",
        "scan_interval_sec": 30,
        "min_edge_pct": 1.5,
        "clob_base_url": "https://clob.polymarket.com",
        "kalshi_base_url": "https://trading-api.kalshi.com/trade-api/v2",
        "max_retries": 3,
        "timeout_seconds": 15.0,
        "max_trade_usdc": 500.0,
        "max_positions": 5,
        "daily_loss_limit": 200.0,
        "dry_run": True,
        "min_volume_24h": 10_000.0,
        "positions_path": "data/polymarket_positions.json",
    }
    defaults.update(overrides)
    return PolymarketConfig(**defaults)  # type: ignore[arg-type]


def _make_opp(**overrides: Any) -> Opportunity:
    defaults: dict[str, Any] = {
        "strategy": "orderbook_spread",
        "market_question": "Will BTC hit $100k?",
        "edge_pct": 5.0,
        "action": "buy YES @ 0.40 + buy NO @ 0.40",
        "confidence": "high",
        "notes": "yes_ask=0.40 no_ask=0.40",
        "condition_id": "0xabc",
        "yes_token_id": "t-yes",
        "no_token_id": "t-no",
        "entry_price_yes": 0.40,
        "entry_price_no": 0.40,
        "volume_24h": 50_000.0,
    }
    defaults.update(overrides)
    return Opportunity(**defaults)


def _ledger(tmp_path: Path) -> PositionsLedger:
    return PositionsLedger(path=tmp_path / "positions.json")


def _guard(tmp_path: Path, **config_overrides: Any) -> RiskGuard:
    return RiskGuard(
        config=_make_config(**config_overrides),
        ledger=_ledger(tmp_path),
    )


# ---------------------------------------------------------------------------
# Check 1: pause flag
# ---------------------------------------------------------------------------

def test_risk_pause_blocks_execution(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    guard.pause()
    passed, reason = guard.check(_make_opp(), proposed_size_usdc=100.0)
    assert not passed
    assert "paused" in reason


def test_risk_pause_then_resume_allows_execution(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    guard.pause()
    guard.resume()
    passed, _ = guard.check(_make_opp(), proposed_size_usdc=100.0)
    assert passed


def test_risk_not_paused_by_default(tmp_path: Path) -> None:
    guard = _guard(tmp_path)
    assert not guard.is_paused


# ---------------------------------------------------------------------------
# Check 2: minimum edge
# ---------------------------------------------------------------------------

def test_risk_fails_when_edge_below_minimum(tmp_path: Path) -> None:
    opp = _make_opp(edge_pct=1.0)  # below default min 1.5
    passed, reason = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert not passed
    assert "edge_pct" in reason


def test_risk_passes_when_edge_at_exact_minimum(tmp_path: Path) -> None:
    opp = _make_opp(edge_pct=1.5)
    passed, _ = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert passed


def test_risk_passes_when_edge_above_minimum(tmp_path: Path) -> None:
    opp = _make_opp(edge_pct=10.0)
    passed, _ = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert passed


# ---------------------------------------------------------------------------
# Check 3: confidence threshold
# ---------------------------------------------------------------------------

def test_risk_fails_on_low_confidence(tmp_path: Path) -> None:
    opp = _make_opp(confidence="low")
    passed, reason = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert not passed
    assert "confidence" in reason


def test_risk_passes_on_medium_confidence(tmp_path: Path) -> None:
    opp = _make_opp(confidence="medium")
    passed, _ = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert passed


def test_risk_passes_on_high_confidence(tmp_path: Path) -> None:
    opp = _make_opp(confidence="high")
    passed, _ = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert passed


# ---------------------------------------------------------------------------
# Check 4: trade size cap
# ---------------------------------------------------------------------------

def test_risk_fails_when_size_exceeds_max(tmp_path: Path) -> None:
    opp = _make_opp()
    passed, reason = _guard(tmp_path, max_trade_usdc=50.0).check(opp, proposed_size_usdc=100.0)
    assert not passed
    assert "proposed_size" in reason or "size" in reason


def test_risk_passes_when_size_at_max(tmp_path: Path) -> None:
    opp = _make_opp()
    passed, _ = _guard(tmp_path, max_trade_usdc=100.0).check(opp, proposed_size_usdc=100.0)
    assert passed


def test_risk_passes_when_size_below_max(tmp_path: Path) -> None:
    opp = _make_opp()
    passed, _ = _guard(tmp_path, max_trade_usdc=500.0).check(opp, proposed_size_usdc=100.0)
    assert passed


# ---------------------------------------------------------------------------
# Check 5: open position count
# ---------------------------------------------------------------------------

def test_risk_fails_when_at_max_positions(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    for _ in range(3):
        ledger.add(new_position("0x1", "q", "orderbook_spread", "YES+NO", 0.8, 100.0, "open"))

    guard = RiskGuard(config=_make_config(max_positions=3), ledger=ledger)
    passed, reason = guard.check(_make_opp(), proposed_size_usdc=100.0)
    assert not passed
    assert "open_positions" in reason or "positions" in reason


def test_risk_passes_when_below_max_positions(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    ledger.add(new_position("0x1", "q", "orderbook_spread", "YES+NO", 0.8, 100.0, "open"))

    guard = RiskGuard(config=_make_config(max_positions=5), ledger=ledger)
    passed, _ = guard.check(_make_opp(), proposed_size_usdc=100.0)
    assert passed


# ---------------------------------------------------------------------------
# Check 6: daily loss limit
# ---------------------------------------------------------------------------

def test_risk_fails_when_daily_loss_breached(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    pos = new_position("0x1", "q", "orderbook_spread", "YES+NO", 0.8, 100.0, "open")
    ledger.add(pos)
    ledger.update_status(pos.id, "closed", pnl=-250.0)  # exceeds 200 limit

    guard = RiskGuard(config=_make_config(daily_loss_limit=200.0), ledger=ledger)
    passed, reason = guard.check(_make_opp(), proposed_size_usdc=100.0)
    assert not passed
    assert "daily_pnl" in reason or "loss" in reason


def test_risk_passes_when_daily_pnl_positive(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    pos = new_position("0x1", "q", "orderbook_spread", "YES+NO", 0.8, 100.0, "open")
    ledger.add(pos)
    ledger.update_status(pos.id, "closed", pnl=50.0)

    guard = RiskGuard(config=_make_config(daily_loss_limit=200.0), ledger=ledger)
    passed, _ = guard.check(_make_opp(), proposed_size_usdc=100.0)
    assert passed


def test_risk_passes_when_daily_pnl_within_limit(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    pos = new_position("0x1", "q", "orderbook_spread", "YES+NO", 0.8, 100.0, "open")
    ledger.add(pos)
    ledger.update_status(pos.id, "closed", pnl=-150.0)  # within 200 limit

    guard = RiskGuard(config=_make_config(daily_loss_limit=200.0), ledger=ledger)
    passed, _ = guard.check(_make_opp(), proposed_size_usdc=100.0)
    assert passed


# ---------------------------------------------------------------------------
# Check 7: market volume
# ---------------------------------------------------------------------------

def test_risk_fails_when_volume_too_low(tmp_path: Path) -> None:
    opp = _make_opp(volume_24h=5_000.0)
    passed, reason = _guard(tmp_path, min_volume_24h=10_000.0).check(opp, proposed_size_usdc=100.0)
    assert not passed
    assert "volume" in reason


def test_risk_passes_when_volume_sufficient(tmp_path: Path) -> None:
    opp = _make_opp(volume_24h=50_000.0)
    passed, _ = _guard(tmp_path, min_volume_24h=10_000.0).check(opp, proposed_size_usdc=100.0)
    assert passed


def test_risk_fails_when_volume_zero(tmp_path: Path) -> None:
    opp = _make_opp(volume_24h=0.0)
    passed, reason = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert not passed
    assert "volume" in reason


# ---------------------------------------------------------------------------
# All checks pass
# ---------------------------------------------------------------------------

def test_risk_all_checks_pass_returns_true(tmp_path: Path) -> None:
    opp = _make_opp(edge_pct=5.0, confidence="high", volume_24h=50_000.0)
    passed, reason = _guard(tmp_path).check(opp, proposed_size_usdc=100.0)
    assert passed
    assert reason == "all_checks_passed"
