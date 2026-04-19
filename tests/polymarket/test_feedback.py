"""Tests for Phase 6 feedback pipeline and parameter tuner.

Covers:
  - load_feedback_records (feedback.py)
  - _compute_rule_effectiveness (tuner.py)
  - propose_tuning, check_minimum_data, write_proposal, apply_proposal,
    reject_proposal (tuner.py)
  - Dashboard tuner endpoints (api.py)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.polymarket.feedback import (
    FeedbackRecord,
    _find_closest_entry,
    _read_daily_logs,
    _signals_from_log,
    load_feedback_records,
)
from src.polymarket.tuner import (
    RULE_NOTE_TO_PARAM,
    ParamChange,
    TuningResult,
    _compute_rule_effectiveness,
    apply_proposal,
    check_minimum_data,
    propose_tuning,
    read_proposal,
    reject_proposal,
    write_proposal,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_now(offset_days: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(days=offset_days)).isoformat()


def _make_closed_position(
    tmp_path: Path,
    *,
    strategy: str = "correlated_markets",
    side: str = "YES",
    pnl: float = 5.0,
    size_usdc: float = 100.0,
    opened_days_ago: int = 5,
    closed_days_ago: int = 4,
    status: str = "closed",
    market_question: str = "Will BTC exceed $90,000 by end of year?",
) -> dict:
    """Build a raw position dict ready to be written to positions JSON."""
    opened_at = _iso_now(-opened_days_ago)
    closed_at = _iso_now(-closed_days_ago)
    return {
        "id": f"pos-{opened_at}",
        "market_condition_id": "cond1",
        "market_question": market_question,
        "strategy": strategy,
        "side": side,
        "entry_price": 0.50,
        "size_usdc": size_usdc,
        "opened_at": opened_at,
        "status": status,
        "pnl": pnl,
        "yes_token_id": "ytok",
        "no_token_id": "ntok",
        "end_date": "",
        "exit_price": 0.60,
        "closed_at": closed_at,
        "unrealized_pnl": None,
        "unrealized_pnl_pct": None,
        "contracts_held": 0.0,
    }


def _write_positions(tmp_path: Path, positions: list[dict]) -> str:
    p = tmp_path / "positions.json"
    p.write_text(json.dumps(positions), encoding="utf-8")
    return str(p)


def _write_daily_log(log_dir: Path, date_str: str, entries: list[dict]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fpath = log_dir / f"poly_{date_str}.log"
    lines = [json.dumps(e) for e in entries]
    fpath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _btc_log_entry(ts: str | None = None, price: float = 85000.0) -> dict:
    return {
        "ts": ts or _iso_now(),
        "open_count": 1,
        "usdc_deployed": 100.0,
        "unrealized_pnl": 0.0,
        "realized_pnl_today": 5.0,
        "combined_daily_pnl": 5.0,
        "daily_loss_limit": 200.0,
        "within_20pct_of_limit": False,
        "btc_signals": {
            "data_available": True,
            "price_usd": price,
            "change_24h_pct": 4.0,
            "rsi_14": 55.0,
            "macd_crossover": "none",
            "consecutive_bars": 2,
            "streak_direction": "green",
            "volume_ratio": 1.1,
            "bb_width_ratio": 1.0,
            "atr_ratio": 1.0,
        },
    }


def _make_feedback_records(
    n: int = 25,
    win_fraction: float = 0.6,
    rules: list[str] | None = None,
    days_spread: int = 12,
) -> list[FeedbackRecord]:
    """Generate N synthetic FeedbackRecord instances spread over multiple days."""
    rules = rules or []
    records = []
    for i in range(n):
        is_win = i < int(n * win_fraction)
        opened_at = _iso_now(-(days_spread - (i % days_spread)))
        records.append(
            FeedbackRecord(
                trade_id=f"t{i}",
                opened_at=opened_at,
                closed_at=opened_at,
                strategy="correlated_markets",
                direction="bullish",
                realized_pnl_pct=5.0 if is_win else -3.0,
                outcome="win" if is_win else "loss",
                signals_at_open={},
                rules_applied=list(rules),
                base_confidence=0.50,
                adjusted_confidence=0.55 if is_win else 0.45,
                edge_pct=0.0,
            )
        )
    return records


# ===========================================================================
# 1–5: load_feedback_records
# ===========================================================================

class TestLoadFeedbackRecords:
    def test_returns_records_for_closed_positions(self, tmp_path):
        pos = _make_closed_position(tmp_path, pnl=10.0, status="closed")
        positions_path = _write_positions(tmp_path, [pos])
        log_dir = tmp_path / "logs"
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_daily_log(log_dir, date_str, [_btc_log_entry()])

        records = load_feedback_records(
            days=30, positions_path=positions_path, log_dir=str(log_dir)
        )
        assert len(records) == 1
        r = records[0]
        assert r.strategy == "correlated_markets"
        assert r.outcome == "win"
        assert r.realized_pnl_pct == pytest.approx(10.0)

    def test_missing_log_dir_still_returns_records(self, tmp_path):
        # Positions are still included even without log data (empty signals).
        pos = _make_closed_position(tmp_path, pnl=5.0, status="closed")
        positions_path = _write_positions(tmp_path, [pos])
        records = load_feedback_records(
            days=30,
            positions_path=positions_path,
            log_dir=str(tmp_path / "nonexistent_logs"),
        )
        assert len(records) == 1
        assert records[0].signals_at_open == {}
        assert records[0].rules_applied == []

    def test_malformed_json_lines_skipped(self, tmp_path):
        pos = _make_closed_position(tmp_path, pnl=5.0, status="closed")
        positions_path = _write_positions(tmp_path, [pos])
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        fpath = log_dir / f"poly_{date_str}.log"
        fpath.write_text(
            'NOT_JSON\n'
            + json.dumps(_btc_log_entry()) + "\n"
            + "also bad {{\n",
            encoding="utf-8",
        )
        # Should not raise
        records = load_feedback_records(
            days=30, positions_path=positions_path, log_dir=str(log_dir)
        )
        assert isinstance(records, list)

    def test_only_includes_trades_within_n_days(self, tmp_path):
        recent = _make_closed_position(tmp_path, pnl=5.0, status="closed", closed_days_ago=5)
        old = _make_closed_position(tmp_path, pnl=5.0, status="closed", closed_days_ago=40)
        # Manually set the closed_at of old to be > 30 days ago
        old["closed_at"] = _iso_now(-40)
        old["id"] = "old-pos"
        positions_path = _write_positions(tmp_path, [recent, old])
        records = load_feedback_records(
            days=30, positions_path=positions_path, log_dir=str(tmp_path / "logs")
        )
        # Old position should be excluded
        assert all(r.trade_id != "old-pos" for r in records)

    def test_excludes_active_positions(self, tmp_path):
        closed = _make_closed_position(tmp_path, pnl=5.0, status="closed")
        active = _make_closed_position(tmp_path, pnl=0.0, status="open")
        active["id"] = "active-pos"
        active["closed_at"] = ""
        positions_path = _write_positions(tmp_path, [closed, active])
        records = load_feedback_records(
            days=30, positions_path=positions_path, log_dir=str(tmp_path / "logs")
        )
        assert all(r.trade_id != "active-pos" for r in records)

    def test_resolved_status_included(self, tmp_path):
        pos = _make_closed_position(tmp_path, pnl=20.0, status="resolved")
        positions_path = _write_positions(tmp_path, [pos])
        records = load_feedback_records(
            days=30, positions_path=positions_path, log_dir=str(tmp_path / "logs")
        )
        assert len(records) == 1
        assert records[0].outcome == "win"

    def test_missing_positions_file_returns_empty(self, tmp_path):
        records = load_feedback_records(
            days=30,
            positions_path=str(tmp_path / "nonexistent.json"),
            log_dir=str(tmp_path / "logs"),
        )
        assert records == []

    def test_btc_signals_populated_from_log(self, tmp_path):
        pos = _make_closed_position(tmp_path, pnl=5.0, status="closed", opened_days_ago=1)
        positions_path = _write_positions(tmp_path, [pos])
        log_dir = tmp_path / "logs"
        # Use today's date for the log
        date_str = datetime.fromisoformat(pos["opened_at"]).strftime("%Y-%m-%d")
        _write_daily_log(log_dir, date_str, [_btc_log_entry(price=87000.0)])
        records = load_feedback_records(
            days=30, positions_path=positions_path, log_dir=str(log_dir)
        )
        assert len(records) == 1
        assert records[0].signals_at_open.get("data_available") is True
        assert records[0].signals_at_open.get("price_usd") == pytest.approx(87000.0)


# ===========================================================================
# 6–8: _compute_rule_effectiveness
# ===========================================================================

class TestComputeRuleEffectiveness:
    def test_all_applied_winning_positive_effectiveness(self):
        applied = _make_feedback_records(n=20, win_fraction=1.0, rules=["volume_spike"])
        # baseline (no rule): all losing
        baseline = _make_feedback_records(n=20, win_fraction=0.0, rules=[])
        records = applied + baseline
        eff, count = _compute_rule_effectiveness(records, "volume_spike")
        assert eff > 0.0
        assert count == 20

    def test_applied_mostly_losing_negative_effectiveness(self):
        applied = _make_feedback_records(n=20, win_fraction=0.1, rules=["volume_spike"])
        baseline = _make_feedback_records(n=20, win_fraction=0.8, rules=[])
        records = applied + baseline
        eff, count = _compute_rule_effectiveness(records, "volume_spike")
        assert eff < 0.0

    def test_no_applied_returns_zero(self):
        records = _make_feedback_records(n=20, win_fraction=0.5, rules=[])
        eff, count = _compute_rule_effectiveness(records, "volume_spike")
        assert eff == 0.0
        assert count == 0

    def test_no_baseline_returns_zero_not_crash(self):
        # All records have the rule applied — no baseline
        records = _make_feedback_records(n=20, win_fraction=0.7, rules=["volume_spike"])
        eff, count = _compute_rule_effectiveness(records, "volume_spike")
        assert eff == 0.0
        assert count == 20


# ===========================================================================
# 9–16: propose_tuning
# ===========================================================================

class TestProposeTuning:
    def _make_records_with_effective_rule(
        self,
        rule: str,
        n_applied: int = 15,
        applied_win_frac: float = 0.90,
        n_baseline: int = 15,
        baseline_win_frac: float = 0.40,
        days_spread: int = 12,
    ) -> list[FeedbackRecord]:
        applied = _make_feedback_records(n_applied, applied_win_frac, [rule], days_spread)
        baseline = _make_feedback_records(n_baseline, baseline_win_frac, [], days_spread)
        return applied + baseline

    def test_effective_rule_increases_param(self):
        records = self._make_records_with_effective_rule("volume_spike", n_applied=15)
        result = propose_tuning(records, days=30)
        param = "volume_spike_bonus"
        change = next((c for c in result.proposed_changes if c.param == param), None)
        assert change is not None, f"Expected {param} in proposed changes"
        assert change.proposed_value > change.current_value

    def test_hurting_rule_decreases_param(self):
        records = self._make_records_with_effective_rule(
            "volume_spike",
            applied_win_frac=0.10,
            baseline_win_frac=0.80,
        )
        result = propose_tuning(records, days=30)
        param = "volume_spike_bonus"
        change = next((c for c in result.proposed_changes if c.param == param), None)
        assert change is not None, f"Expected {param} in proposed changes"
        assert change.proposed_value < change.current_value

    def test_insufficient_trade_count_in_insufficient_list(self):
        # Only 5 trades have the rule applied — below MIN_TRADES_PER_RULE (10)
        applied = _make_feedback_records(5, 0.9, ["volume_spike"], 12)
        baseline = _make_feedback_records(20, 0.4, [], 12)
        records = applied + baseline
        result = propose_tuning(records, days=30)
        assert "volume_spike_bonus" in result.insufficient_data_params

    def test_multiplier_never_exceeds_max_bound(self):
        # Even if effectiveness is extreme, multiplier should not exceed 1.50
        records = self._make_records_with_effective_rule(
            "direction_aligned_bullish", n_applied=20, applied_win_frac=1.0
        )
        result = propose_tuning(records, days=30)
        for c in result.proposed_changes:
            from src.polymarket.tuner import _MULTIPLIER_PARAMS, _MULTIPLIER_BOUNDS
            if c.param in _MULTIPLIER_PARAMS:
                assert c.proposed_value <= _MULTIPLIER_BOUNDS[1], (
                    f"{c.param} exceeded upper bound: {c.proposed_value}"
                )

    def test_multiplier_never_drops_below_min_bound(self):
        records = self._make_records_with_effective_rule(
            "direction_aligned_bullish",
            n_applied=20,
            applied_win_frac=0.0,
            baseline_win_frac=1.0,
        )
        result = propose_tuning(records, days=30)
        from src.polymarket.tuner import _MULTIPLIER_PARAMS, _MULTIPLIER_BOUNDS
        for c in result.proposed_changes:
            if c.param in _MULTIPLIER_PARAMS:
                assert c.proposed_value >= _MULTIPLIER_BOUNDS[0], (
                    f"{c.param} below lower bound: {c.proposed_value}"
                )

    def test_bonus_never_exceeds_max_bound(self):
        records = self._make_records_with_effective_rule(
            "volume_spike", n_applied=20, applied_win_frac=1.0
        )
        result = propose_tuning(records, days=30)
        from src.polymarket.tuner import _BONUS_PARAMS, _BONUS_BOUNDS
        for c in result.proposed_changes:
            if c.param in _BONUS_PARAMS:
                assert c.proposed_value <= _BONUS_BOUNDS[1], (
                    f"{c.param} exceeded bonus upper bound: {c.proposed_value}"
                )

    def test_bonus_never_drops_below_zero(self):
        records = self._make_records_with_effective_rule(
            "volume_spike",
            n_applied=20,
            applied_win_frac=0.0,
            baseline_win_frac=1.0,
        )
        result = propose_tuning(records, days=30)
        from src.polymarket.tuner import _BONUS_PARAMS, _BONUS_BOUNDS
        for c in result.proposed_changes:
            if c.param in _BONUS_PARAMS:
                assert c.proposed_value >= _BONUS_BOUNDS[0], (
                    f"{c.param} went below 0: {c.proposed_value}"
                )

    def test_max_20pct_change_per_run(self):
        records = self._make_records_with_effective_rule(
            "volume_spike", n_applied=20, applied_win_frac=1.0
        )
        result = propose_tuning(records, days=30)
        from src.polymarket.tuner import _MAX_CHANGE_FRACTION
        for c in result.proposed_changes:
            max_change = c.current_value * _MAX_CHANGE_FRACTION
            actual_change = abs(c.proposed_value - c.current_value)
            # Allow small floating point tolerance
            assert actual_change <= max_change + 1e-9, (
                f"{c.param}: change {actual_change:.6f} > max {max_change:.6f}"
            )


# ===========================================================================
# 17–19: write_proposal / apply_proposal / reject_proposal
# ===========================================================================

class TestProposalIO:
    def _make_result(self) -> TuningResult:
        return TuningResult(
            generated_at=datetime.now(UTC).isoformat(),
            days_analyzed=30,
            trade_count=25,
            overall_win_rate=0.60,
            avg_pnl_pct=2.5,
            proposed_changes=[
                ParamChange(
                    param="volume_spike_bonus",
                    current_value=0.05,
                    proposed_value=0.055,
                    effectiveness=0.12,
                    applied_count=15,
                    direction="increase",
                )
            ],
            proposed_params={"volume_spike_bonus": 0.055},
            data_ok=True,
        )

    def test_write_proposal_creates_json_file(self, tmp_path):
        result = self._make_result()
        proposal_path = str(tmp_path / "proposal.json")
        write_proposal(result, proposal_path)
        assert Path(proposal_path).exists()
        data = json.loads(Path(proposal_path).read_text())
        assert data["trade_count"] == 25
        assert len(data["proposed_changes"]) == 1

    def test_write_proposal_does_not_touch_signal_params(self, tmp_path):
        from src.polymarket.signals import _DEFAULT_FILE_CONTENT
        params_path = tmp_path / "signal_params.json"
        params_path.write_text(json.dumps(_DEFAULT_FILE_CONTENT), encoding="utf-8")
        mtime_before = params_path.stat().st_mtime

        result = self._make_result()
        proposal_path = str(tmp_path / "proposal.json")
        write_proposal(result, proposal_path)

        mtime_after = params_path.stat().st_mtime
        assert mtime_before == mtime_after, "write_proposal should not touch signal_params.json"

    def test_apply_proposal_creates_backup(self, tmp_path):
        from src.polymarket.signals import _DEFAULT_FILE_CONTENT
        params_path = tmp_path / "signal_params.json"
        params_path.write_text(json.dumps(_DEFAULT_FILE_CONTENT), encoding="utf-8")
        history_dir = str(tmp_path / "history")
        proposal_path = str(tmp_path / "proposal.json")

        result = self._make_result()
        write_proposal(result, proposal_path)

        with patch("src.polymarket.signals.reload_signal_params"):
            change_log = apply_proposal(proposal_path, str(params_path), history_dir)

        backups = list(Path(history_dir).glob("signal_params_v*.json"))
        assert len(backups) == 1
        assert "volume_spike_bonus" in change_log

    def test_apply_proposal_updates_params_file(self, tmp_path):
        from src.polymarket.signals import _DEFAULT_FILE_CONTENT
        params_path = tmp_path / "signal_params.json"
        params_path.write_text(json.dumps(_DEFAULT_FILE_CONTENT), encoding="utf-8")
        history_dir = str(tmp_path / "history")
        proposal_path = str(tmp_path / "proposal.json")

        result = self._make_result()
        write_proposal(result, proposal_path)

        with patch("src.polymarket.signals.reload_signal_params"):
            apply_proposal(proposal_path, str(params_path), history_dir)

        updated = json.loads(params_path.read_text())
        assert updated["params"]["volume_spike_bonus"] == pytest.approx(0.055)
        assert updated["updated_by"] == "tuner"

    def test_apply_proposal_calls_reload(self, tmp_path):
        from src.polymarket.signals import _DEFAULT_FILE_CONTENT
        params_path = tmp_path / "signal_params.json"
        params_path.write_text(json.dumps(_DEFAULT_FILE_CONTENT), encoding="utf-8")
        proposal_path = str(tmp_path / "proposal.json")
        result = self._make_result()
        write_proposal(result, proposal_path)

        with patch("src.polymarket.signals.reload_signal_params") as mock_reload:
            apply_proposal(proposal_path, str(params_path), str(tmp_path / "hist"))
        mock_reload.assert_called_once()

    def test_reject_proposal_deletes_file(self, tmp_path):
        proposal_path = tmp_path / "proposal.json"
        proposal_path.write_text('{}')
        reject_proposal(str(proposal_path))
        assert not proposal_path.exists()

    def test_reject_proposal_no_error_if_missing(self, tmp_path):
        # Should not raise
        reject_proposal(str(tmp_path / "nonexistent.json"))


# ===========================================================================
# 20–22: check_minimum_data
# ===========================================================================

class TestCheckMinimumData:
    def test_fewer_than_20_trades_returns_false(self):
        records = _make_feedback_records(n=15, days_spread=12)
        ok, reason = check_minimum_data(records)
        assert ok is False
        assert "15" in reason
        assert "minimum 20" in reason

    def test_fewer_than_10_days_returns_false(self):
        # 20 trades but all on same day
        records = _make_feedback_records(n=20, days_spread=1)
        # Force all to same date
        for r in records:
            r.opened_at = datetime.now(UTC).isoformat()
        ok, reason = check_minimum_data(records)
        assert ok is False
        assert "calendar days" in reason

    def test_sufficient_data_returns_true(self):
        records = _make_feedback_records(n=25, days_spread=12)
        ok, reason = check_minimum_data(records)
        assert ok is True
        assert reason == ""

    def test_empty_records_returns_false(self):
        ok, reason = check_minimum_data([])
        assert ok is False
        assert "no closed trades" in reason


# ===========================================================================
# 23–25: Dashboard tuner API endpoints
# ===========================================================================

def _make_test_app(tmp_path: Path):
    """Return a TestClient wired to the poly dashboard router."""
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

    from src.polymarket.config import PolymarketConfig
    cfg = PolymarketConfig(
        api_key="k", api_secret="s", passphrase="p", private_key="pk",
        scan_interval_sec=30, min_edge_pct=1.5,
        clob_base_url="https://clob.polymarket.com",
        kalshi_base_url="https://k.com",
        max_retries=0, timeout_seconds=5.0,
        daily_loss_limit=200.0, max_positions=5, dry_run=True,
        poly_log_dir=str(tmp_path),
        positions_path=str(tmp_path / "positions.json"),
    )

    mock_repo = MagicMock()
    mock_snap = MagicMock()
    mock_snap.cash = 10_000.0
    mock_snap.positions = {}
    mock_repo.load_portfolio_snapshot.return_value = mock_snap
    mock_repo.get_global_kill_switch.return_value = False

    from src.dashboard.aggregator import DashboardAggregator
    from src.polymarket.positions import make_ledger
    ledger = make_ledger(str(tmp_path / "positions.json"))
    agg = DashboardAggregator(poly_config=cfg, ledger=ledger, repository=mock_repo)
    register(agg, cfg, MagicMock(), ledger)

    return TestClient(test_app), cfg


class TestDashboardTunerEndpoints:
    def test_status_no_proposal_pending_false(self, tmp_path, monkeypatch):
        # No proposal file exists
        import src.dashboard.api as api_module
        monkeypatch.setattr(api_module, "_tuner_proposal_path", str(tmp_path / "no_proposal.json"))
        monkeypatch.setattr(api_module, "_tuner_last_run", "")
        monkeypatch.setattr(api_module, "_tuner_last_trade_count", 0)

        client, _ = _make_test_app(tmp_path)
        with patch("src.dashboard.aggregator.is_poly_paused", return_value=False):
            r = client.get("/api/poly/tuner/status")
        assert r.status_code == 200
        data = r.json()
        assert data["proposal_pending"] is False
        assert "current_params" in data

    def test_proposal_endpoint_returns_404_when_none(self, tmp_path, monkeypatch):
        import src.dashboard.api as api_module
        monkeypatch.setattr(api_module, "_tuner_proposal_path", str(tmp_path / "no_proposal.json"))

        client, _ = _make_test_app(tmp_path)
        r = client.get("/api/poly/tuner/proposal")
        assert r.status_code == 404

    def test_apply_endpoint_returns_404_when_no_proposal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret")
        import src.dashboard.api as api_module
        monkeypatch.setattr(api_module, "_tuner_proposal_path", str(tmp_path / "no_proposal.json"))

        client, _ = _make_test_app(tmp_path)
        r = client.post(
            "/api/poly/tuner/apply",
            headers={"Authorization": "Bearer secret"},
        )
        assert r.status_code == 404

    def test_run_endpoint_requires_auth(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret")
        client, _ = _make_test_app(tmp_path)
        r = client.post("/api/poly/tuner/run")
        assert r.status_code == 401

    def test_reject_endpoint_requires_auth(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "secret")
        client, _ = _make_test_app(tmp_path)
        r = client.post("/api/poly/tuner/reject")
        assert r.status_code == 401

    def test_status_shows_proposal_pending_when_file_exists(self, tmp_path, monkeypatch):
        proposal_path = tmp_path / "proposal.json"
        proposal_path.write_text(json.dumps({
            "proposed_changes": [{"param": "volume_spike_bonus"}],
        }))
        import src.dashboard.api as api_module
        monkeypatch.setattr(api_module, "_tuner_proposal_path", str(proposal_path))

        client, _ = _make_test_app(tmp_path)
        r = client.get("/api/poly/tuner/status")
        assert r.status_code == 200
        data = r.json()
        assert data["proposal_pending"] is True
        assert data["proposal_change_count"] == 1

    def test_proposal_endpoint_returns_proposal_when_present(self, tmp_path, monkeypatch):
        proposal_data = {
            "generated_at": datetime.now(UTC).isoformat(),
            "proposed_changes": [],
            "trade_count": 30,
        }
        proposal_path = tmp_path / "proposal.json"
        proposal_path.write_text(json.dumps(proposal_data))

        import src.dashboard.api as api_module
        monkeypatch.setattr(api_module, "_tuner_proposal_path", str(proposal_path))

        client, _ = _make_test_app(tmp_path)
        r = client.get("/api/poly/tuner/proposal")
        assert r.status_code == 200
        assert r.json()["trade_count"] == 30

    def test_run_endpoint_skips_when_insufficient_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "tok")
        import src.dashboard.api as api_module
        monkeypatch.setattr(api_module, "_tuner_proposal_path", str(tmp_path / "prop.json"))

        # positions.json doesn't exist → no records → skip
        client, _ = _make_test_app(tmp_path)
        r = client.post(
            "/api/poly/tuner/run",
            headers={"Authorization": "Bearer tok"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data.get("skipped") is True

    def test_reject_endpoint_deletes_proposal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHBOARD_API_TOKEN", "tok")
        proposal_path = tmp_path / "proposal.json"
        proposal_path.write_text('{"proposed_changes": []}')

        import src.dashboard.api as api_module
        monkeypatch.setattr(api_module, "_tuner_proposal_path", str(proposal_path))

        client, _ = _make_test_app(tmp_path)
        r = client.post(
            "/api/poly/tuner/reject",
            headers={"Authorization": "Bearer tok"},
        )
        assert r.status_code == 200
        assert not proposal_path.exists()
