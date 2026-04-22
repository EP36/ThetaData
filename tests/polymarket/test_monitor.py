"""Tests for src/polymarket/monitor.py — Phase 3 position monitoring."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.polymarket.config import PolymarketConfig
from src.polymarket.monitor import (
    check_resolution,
    close_position,
    close_reason,
    compute_unrealized,
    emit_daily_summary,
    monitor_positions,
)
from src.polymarket.positions import (
    PositionRecord,
    PositionsLedger,
    make_ledger,
    new_position,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _config(**overrides) -> PolymarketConfig:
    base = dict(
        api_key="k",
        api_secret="s",
        passphrase="p",
        private_key="pk",
        scan_interval_sec=30,
        min_edge_pct=1.5,
        clob_base_url="https://clob.polymarket.com",
        kalshi_base_url="https://trading-api.kalshi.com/trade-api/v2",
        max_retries=0,
        timeout_seconds=5.0,
        take_profit_pct=15.0,
        stop_loss_pct=10.0,
        max_hold_hours=72,
        unhedged_grace_minutes=5,
        daily_loss_limit=200.0,
        poly_log_dir="",   # overridden per-test when needed
        dry_run=True,
    )
    base.update(overrides)
    if base.get("dry_run") is False:
        base.setdefault("trading_mode", "live")
        base.setdefault("trading_venue", "polymarket")
        base.setdefault("live_trading_enabled", True)
    return PolymarketConfig(**base)


def _open_position(
    *,
    side: str = "YES+NO",
    status: str = "open",
    entry_price: float = 0.50,
    size_usdc: float = 100.0,
    contracts_held: float = 100.0,
    yes_token_id: str = "yes_tok",
    no_token_id: str = "no_tok",
    opened_at: str | None = None,
) -> PositionRecord:
    p = new_position(
        market_condition_id="cond1",
        market_question="Will BTC hit 100k?",
        strategy="orderbook_spread",
        side=side,
        entry_price=entry_price,
        size_usdc=size_usdc,
        status=status,
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        contracts_held=contracts_held,
    )
    if opened_at is not None:
        object.__setattr__(p, "opened_at", opened_at) if hasattr(type(p), "__slots__") else setattr(p, "opened_at", opened_at)
        p = PositionRecord(**{**p.__dict__, "opened_at": opened_at})
    return p


# ---------------------------------------------------------------------------
# compute_unrealized
# ---------------------------------------------------------------------------

class TestComputeUnrealized:
    def test_yes_no_positive_pnl(self):
        pos = _open_position(side="YES+NO", contracts_held=100.0, size_usdc=100.0)
        pnl, pct = compute_unrealized(pos, yes_bid=0.55, no_bid=0.55)
        # current_value = 100 * (0.55 + 0.55) = 110; pnl = 10; pct = 10%
        assert abs(pnl - 10.0) < 0.001
        assert abs(pct - 10.0) < 0.001

    def test_yes_only_side(self):
        pos = _open_position(side="YES", contracts_held=200.0, size_usdc=100.0, no_token_id="")
        pnl, pct = compute_unrealized(pos, yes_bid=0.45, no_bid=0.0)
        # current_value = 200 * 0.45 = 90; pnl = -10; pct = -10%
        assert abs(pnl - (-10.0)) < 0.001
        assert abs(pct - (-10.0)) < 0.001

    def test_no_only_side(self):
        pos = _open_position(side="NO", contracts_held=200.0, size_usdc=100.0, yes_token_id="")
        pnl, pct = compute_unrealized(pos, yes_bid=0.0, no_bid=0.50)
        assert abs(pnl - 0.0) < 0.001

    def test_fallback_when_contracts_held_zero(self):
        pos = _open_position(side="YES+NO", contracts_held=0.0, entry_price=0.50, size_usdc=100.0)
        # fallback: contracts = 100 / (2 * 0.50) = 100
        pnl, pct = compute_unrealized(pos, yes_bid=0.55, no_bid=0.55)
        assert pnl > 0

    def test_zero_size_returns_zeros(self):
        pos = _open_position(size_usdc=0.0)
        assert compute_unrealized(pos, 0.5, 0.5) == (0.0, 0.0)

    def test_unknown_side_returns_zeros(self):
        pos = _open_position(side="BOTH")
        assert compute_unrealized(pos, 0.5, 0.5) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# close_reason
# ---------------------------------------------------------------------------

class TestCloseReason:
    def _cfg(self, **kw):
        return _config(**kw)

    def test_profit_target_triggers(self):
        config = self._cfg(take_profit_pct=15.0)
        pos = _open_position()
        reason = close_reason(pos, config, unrealized_pnl_pct=16.0)
        assert reason is not None
        assert "profit_target" in reason

    def test_profit_target_not_triggered_below(self):
        config = self._cfg(take_profit_pct=15.0)
        pos = _open_position()
        assert close_reason(pos, config, unrealized_pnl_pct=14.9) is None

    def test_stop_loss_triggers(self):
        config = self._cfg(stop_loss_pct=10.0)
        pos = _open_position()
        reason = close_reason(pos, config, unrealized_pnl_pct=-10.5)
        assert reason is not None
        assert "stop_loss" in reason

    def test_stop_loss_not_triggered_above(self):
        config = self._cfg(stop_loss_pct=10.0)
        pos = _open_position()
        assert close_reason(pos, config, unrealized_pnl_pct=-9.9) is None

    def test_max_hold_hours_triggers(self):
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=73)).isoformat()
        pos = _open_position(opened_at=old_time)
        config = self._cfg(max_hold_hours=72)
        reason = close_reason(pos, config, unrealized_pnl_pct=0.0)
        assert reason is not None
        assert "max_hold_hours" in reason

    def test_max_hold_hours_not_triggered_recent(self):
        fresh_time = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        pos = _open_position(opened_at=fresh_time)
        config = self._cfg(max_hold_hours=72)
        assert close_reason(pos, config, unrealized_pnl_pct=0.0) is None

    def test_unhedged_grace_triggers(self):
        old_time = (datetime.now(tz=timezone.utc) - timedelta(minutes=10)).isoformat()
        pos = _open_position(status="unhedged", opened_at=old_time)
        config = self._cfg(unhedged_grace_minutes=5)
        reason = close_reason(pos, config, unrealized_pnl_pct=0.0)
        assert reason is not None
        assert "unhedged_grace" in reason

    def test_unhedged_grace_not_triggered_early(self):
        fresh_time = (datetime.now(tz=timezone.utc) - timedelta(minutes=2)).isoformat()
        pos = _open_position(status="unhedged", opened_at=fresh_time)
        config = self._cfg(unhedged_grace_minutes=5)
        assert close_reason(pos, config, unrealized_pnl_pct=0.0) is None

    def test_no_reason_for_normal_position(self):
        fresh_time = (datetime.now(tz=timezone.utc) - timedelta(minutes=30)).isoformat()
        pos = _open_position(opened_at=fresh_time)
        config = self._cfg()
        assert close_reason(pos, config, unrealized_pnl_pct=5.0) is None


# ---------------------------------------------------------------------------
# check_resolution
# ---------------------------------------------------------------------------

class TestCheckResolution:
    def _ledger(self, tmp_path: Path, pos: PositionRecord) -> PositionsLedger:
        ledger = make_ledger(str(tmp_path / "pos.json"))
        ledger.add(pos)
        return ledger

    def test_resolved_yes_win(self, tmp_path: Path):
        pos = _open_position(side="YES+NO", contracts_held=100.0, size_usdc=90.0)
        ledger = self._ledger(tmp_path, pos)
        detail = {"resolved": True, "winning_outcome": "YES"}
        result = check_resolution(pos, detail, ledger)
        assert result is True
        records = ledger.load()
        assert records[0].status == "resolved"
        assert records[0].pnl is not None and records[0].pnl > 0

    def test_resolved_no_win(self, tmp_path: Path):
        pos = _open_position(side="YES+NO", contracts_held=100.0, size_usdc=90.0)
        ledger = self._ledger(tmp_path, pos)
        detail = {"resolved": True, "winning_outcome": "NO"}
        result = check_resolution(pos, detail, ledger)
        assert result is True
        assert ledger.load()[0].status == "resolved"

    def test_not_resolved_no_stale(self, tmp_path: Path):
        pos = _open_position()
        ledger = self._ledger(tmp_path, pos)
        future = (datetime.now(tz=timezone.utc) + timedelta(days=7)).isoformat()
        detail = {"resolved": False, "end_date_iso": future}
        result = check_resolution(pos, detail, ledger)
        assert result is False
        assert ledger.load()[0].status == "open"

    def test_stale_market_end_date_passed(self, tmp_path: Path):
        pos = _open_position()
        ledger = self._ledger(tmp_path, pos)
        past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        detail = {"resolved": False, "end_date_iso": past}
        check_resolution(pos, detail, ledger)
        assert ledger.load()[0].status == "stale"

    def test_stale_is_not_terminal_for_check_resolution(self, tmp_path: Path):
        # check_resolution returns False for stale (not terminal — needs human review)
        pos = _open_position()
        ledger = self._ledger(tmp_path, pos)
        past = (datetime.now(tz=timezone.utc) - timedelta(days=1)).isoformat()
        detail = {"resolved": False, "end_date_iso": past}
        result = check_resolution(pos, detail, ledger)
        assert result is False


# ---------------------------------------------------------------------------
# close_position (dry run)
# ---------------------------------------------------------------------------

class TestClosePositionDryRun:
    def test_dry_run_returns_true_no_api(self, tmp_path: Path):
        config = _config(dry_run=True)
        pos = _open_position()
        ledger = make_ledger(str(tmp_path / "pos.json"))
        ledger.add(pos)
        client = MagicMock()
        result = close_position(pos, config, client, ledger)
        assert result is True
        client.fetch_orderbook.assert_not_called()
        assert ledger.load()[0].status == "open"

    def test_dry_run_unhedged_position(self, tmp_path: Path):
        config = _config(dry_run=True)
        pos = _open_position(status="unhedged", side="YES", no_token_id="")
        ledger = make_ledger(str(tmp_path / "pos.json"))
        ledger.add(pos)
        client = MagicMock()
        result = close_position(pos, config, client, ledger)
        assert result is True


# ---------------------------------------------------------------------------
# close_position (live — mocked _place_order)
# ---------------------------------------------------------------------------

class TestClosePositionLive:
    def test_live_close_marks_closed(self, tmp_path: Path):
        config = _config(dry_run=False)
        pos = _open_position(side="YES+NO", contracts_held=100.0, size_usdc=90.0)
        ledger = make_ledger(str(tmp_path / "pos.json"))
        ledger.add(pos)

        client = MagicMock()
        client.fetch_orderbook.return_value = {"bids": [{"price": "0.90"}]}

        with patch("src.polymarket.monitor._place_order") as mock_place:
            mock_place.return_value = {"price": "0.90"}
            result = close_position(pos, config, client, ledger)

        assert result is True
        rec = ledger.load()[0]
        assert rec.status == "closed"
        assert rec.pnl is not None

    def test_live_close_fail_stays_closing(self, tmp_path: Path):
        config = _config(dry_run=False)
        pos = _open_position(side="YES+NO", contracts_held=100.0, size_usdc=90.0)
        ledger = make_ledger(str(tmp_path / "pos.json"))
        ledger.add(pos)

        client = MagicMock()
        client.fetch_orderbook.return_value = {"bids": [{"price": "0.90"}]}

        with patch("src.polymarket.monitor._place_order", side_effect=RuntimeError("net err")):
            result = close_position(pos, config, client, ledger)

        assert result is False
        assert ledger.load()[0].status == "closing"


# ---------------------------------------------------------------------------
# emit_daily_summary
# ---------------------------------------------------------------------------

class TestEmitDailySummary:
    def test_summary_written_to_log_file(self, tmp_path: Path):
        config = _config(poly_log_dir=str(tmp_path))
        ledger = make_ledger(str(tmp_path / "pos.json"))
        positions = [_open_position(size_usdc=200.0)]

        summary = emit_daily_summary(positions, config, ledger)

        assert "open_count" in summary
        assert summary["open_count"] == 1
        assert summary["usdc_deployed"] == 200.0

        log_files = list(tmp_path.glob("poly_*.log"))
        assert len(log_files) == 1
        line = json.loads(log_files[0].read_text().strip())
        assert line["open_count"] == 1

    def test_no_positions_summary(self, tmp_path: Path):
        config = _config(poly_log_dir=str(tmp_path))
        ledger = make_ledger(str(tmp_path / "pos.json"))
        summary = emit_daily_summary([], config, ledger)
        assert summary["open_count"] == 0
        assert summary["usdc_deployed"] == 0.0

    def test_loss_warning_near_limit(self, tmp_path: Path, caplog):
        config = _config(poly_log_dir=str(tmp_path), daily_loss_limit=100.0)
        ledger = make_ledger(str(tmp_path / "pos.json"))

        # Inject a closed position today with a large loss
        pos = _open_position(status="open")
        ledger.add(pos)
        import logging
        with patch("src.polymarket.positions.PositionsLedger.daily_pnl", return_value=-85.0):
            with caplog.at_level(logging.WARNING, logger="theta.polymarket.monitor"):
                emit_daily_summary([], config, ledger)

        assert any("within 20%" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# State transitions — valid and invalid
# ---------------------------------------------------------------------------

class TestStateTransitions:
    def _ledger(self, tmp_path: Path, pos: PositionRecord) -> PositionsLedger:
        ledger = make_ledger(str(tmp_path / "pos.json"))
        ledger.add(pos)
        return ledger

    def test_open_to_closing(self, tmp_path: Path):
        pos = _open_position(status="open")
        ledger = self._ledger(tmp_path, pos)
        ok = ledger.transition(pos.id, "closing", reason="test")
        assert ok is True
        assert ledger.load()[0].status == "closing"

    def test_open_to_resolved(self, tmp_path: Path):
        pos = _open_position(status="open")
        ledger = self._ledger(tmp_path, pos)
        ok = ledger.transition(pos.id, "resolved", reason="market_resolved")
        assert ok is True

    def test_closed_to_open_rejected(self, tmp_path: Path):
        pos = _open_position(status="open")
        ledger = self._ledger(tmp_path, pos)
        ledger.transition(pos.id, "closing", reason="test")
        ledger.transition(pos.id, "closed", reason="filled")
        ok = ledger.transition(pos.id, "open", reason="bad_reversal")
        assert ok is False
        assert ledger.load()[0].status == "closed"

    def test_resolved_to_open_rejected(self, tmp_path: Path):
        pos = _open_position(status="open")
        ledger = self._ledger(tmp_path, pos)
        ledger.transition(pos.id, "resolved", reason="market_resolved")
        ok = ledger.transition(pos.id, "open", reason="bad_reversal")
        assert ok is False

    def test_unhedged_to_closing(self, tmp_path: Path):
        pos = _open_position(status="unhedged")
        ledger = self._ledger(tmp_path, pos)
        ok = ledger.transition(pos.id, "closing", reason="grace_expired")
        assert ok is True

    def test_closing_retryable(self, tmp_path: Path):
        pos = _open_position(status="open")
        ledger = self._ledger(tmp_path, pos)
        ledger.transition(pos.id, "closing", reason="first_attempt")
        ok = ledger.transition(pos.id, "closing", reason="retry")
        assert ok is True


# ---------------------------------------------------------------------------
# monitor_positions integration
# ---------------------------------------------------------------------------

class TestMonitorPositions:
    def test_monitor_positions_dry_run_no_api_writes(self, tmp_path: Path):
        config = _config(dry_run=True, poly_log_dir=str(tmp_path))
        ledger = make_ledger(str(tmp_path / "pos.json"))
        pos = _open_position()
        ledger.add(pos)

        client = MagicMock()
        client.fetch_orderbook.return_value = {"bids": [{"price": "0.50"}]}
        client.fetch_market_detail.return_value = {"resolved": False}

        monitor_positions(config, client, ledger)

        # Dry-run: position stays open
        assert ledger.load()[0].status == "open"

    def test_monitor_positions_triggers_profit_close(self, tmp_path: Path):
        config = _config(dry_run=False, take_profit_pct=5.0, poly_log_dir=str(tmp_path))
        ledger = make_ledger(str(tmp_path / "pos.json"))
        pos = _open_position(size_usdc=90.0, contracts_held=100.0)
        ledger.add(pos)

        # Bids at 0.55 each → current_value = 100*(0.55+0.55) = 110 → pct ≈ 22%
        client = MagicMock()
        client.fetch_orderbook.return_value = {"bids": [{"price": "0.55"}]}
        client.fetch_market_detail.return_value = {"resolved": False}

        with patch("src.polymarket.monitor._place_order") as mock_place:
            mock_place.return_value = {"price": "0.55"}
            monitor_positions(config, client, ledger)

        assert ledger.load()[0].status == "closed"

    def test_monitor_positions_skips_terminal_positions(self, tmp_path: Path):
        config = _config(dry_run=True, poly_log_dir=str(tmp_path))
        ledger = make_ledger(str(tmp_path / "pos.json"))

        # Add a resolved (terminal) position
        pos = _open_position(status="open")
        ledger.add(pos)
        ledger.transition(pos.id, "resolved", reason="market_resolved")

        client = MagicMock()
        monitor_positions(config, client, ledger)

        # Resolved position stays resolved; no API calls for it
        client.fetch_orderbook.assert_not_called()
