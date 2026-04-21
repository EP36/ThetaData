"""Tests for Phase 7 AI analyst, safety validator, DB layer, and loop logic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_fills(n: int = 25) -> list[dict]:
    """Build synthetic fill records (alternating buy/sell per symbol)."""
    fills = []
    for i in range(n):
        side = "buy" if i % 2 == 0 else "sell"
        fills.append({
            "fill_id": f"f{i}",
            "order_id": f"o{i}",
            "symbol": f"SYM{i // 2}",
            "side": side,
            "quantity": 10.0,
            "price": 0.50 + (0.05 if side == "sell" else 0.0),  # profit on sells
            "notional": 5.0 + (0.50 if side == "sell" else 0.0),
            "timestamp": "2024-01-10T12:00:00+00:00",
        })
    return fills


_DEFAULT_PARAMS: dict = {
    "direction_bullish_up_multiplier": 1.20,
    "direction_bullish_down_multiplier": 0.70,
    "direction_bearish_down_multiplier": 1.20,
    "direction_bearish_up_multiplier": 0.70,
    "rsi_overbought_multiplier": 0.85,
    "rsi_oversold_multiplier": 0.85,
    "macd_crossover_bonus": 0.05,
    "streak_bonus": 0.03,
    "volume_spike_bonus": 0.05,
    "volume_low_multiplier": 0.80,
    "proximity_close_multiplier": 0.75,
    "proximity_far_bonus": 0.08,
    "volatility_high_multiplier": 0.85,
    "atr_high_multiplier": 0.85,
}


# ---------------------------------------------------------------------------
# analyst.py — AIAnalysis dataclass + _summarize_fills
# ---------------------------------------------------------------------------

class TestAnalystInternals:
    def test_summarize_fills_calculates_win_rate(self):
        from trauto.ai.analyst import _summarize_fills
        fills = _make_fills(20)
        summary = _summarize_fills(fills)
        assert summary["total_fills"] == 20
        assert summary["closed_trades"] == 10
        assert summary["wins"] == 10  # every sell is profitable
        assert summary["win_rate"] == pytest.approx(1.0)

    def test_summarize_fills_empty(self):
        from trauto.ai.analyst import _summarize_fills
        summary = _summarize_fills([])
        assert summary["total_fills"] == 0
        assert summary["closed_trades"] == 0
        assert summary["win_rate"] == 0.0

    def test_parse_response_valid_json(self):
        from trauto.ai.analyst import _parse_response
        raw = json.dumps({
            "proposed_params": {"direction_bullish_up_multiplier": 1.25},
            "reasoning": "It works",
            "confidence": 0.80,
            "key_findings": ["finding1"],
            "warnings": [],
            "win_rate": 0.65,
            "avg_pnl_pct": 3.5,
        })
        summary = {"closed_trades": 25, "win_rate": 0.65, "avg_pnl_pct": 3.5}
        result = _parse_response(raw, dict(_DEFAULT_PARAMS), summary, 500, 1200)
        assert result is not None
        assert result.confidence == pytest.approx(0.80)
        assert result.proposed_params["direction_bullish_up_multiplier"] == pytest.approx(1.25)
        assert result.reasoning == "It works"

    def test_parse_response_strips_markdown_fences(self):
        from trauto.ai.analyst import _parse_response
        inner = {"proposed_params": {}, "reasoning": "ok", "confidence": 0.7,
                 "key_findings": [], "warnings": [], "win_rate": 0.5, "avg_pnl_pct": 1.0}
        raw = "```json\n" + json.dumps(inner) + "\n```"
        summary = {"closed_trades": 25, "win_rate": 0.5, "avg_pnl_pct": 1.0}
        result = _parse_response(raw, dict(_DEFAULT_PARAMS), summary, 100, 500)
        assert result is not None

    def test_parse_response_invalid_json_returns_none(self):
        from trauto.ai.analyst import _parse_response
        summary = {"closed_trades": 25, "win_rate": 0.5, "avg_pnl_pct": 1.0}
        result = _parse_response("not json {{{", dict(_DEFAULT_PARAMS), summary, 0, 0)
        assert result is None

    def test_parse_response_ignores_unknown_params(self):
        from trauto.ai.analyst import _parse_response
        raw = json.dumps({
            "proposed_params": {"unknown_param": 999.0, "direction_bullish_up_multiplier": 1.1},
            "reasoning": "r", "confidence": 0.7,
            "key_findings": [], "warnings": [], "win_rate": 0.5, "avg_pnl_pct": 0.0,
        })
        summary = {"closed_trades": 25, "win_rate": 0.5, "avg_pnl_pct": 0.0}
        result = _parse_response(raw, dict(_DEFAULT_PARAMS), summary, 0, 0)
        assert result is not None
        assert "unknown_param" not in result.proposed_params

    def test_analyze_skips_when_no_api_key(self):
        from trauto.ai.analyst import analyze
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            result = analyze(_make_fills(30), dict(_DEFAULT_PARAMS), None)
        assert result is None

    def test_analyze_skips_when_no_fills(self):
        from trauto.ai.analyst import analyze
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            result = analyze([], dict(_DEFAULT_PARAMS), None)
        assert result is None

    def test_analyze_returns_analysis_with_mock_api(self):
        from trauto.ai.analyst import analyze
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps({
            "proposed_params": {"direction_bullish_up_multiplier": 1.22},
            "reasoning": "Momentum works",
            "confidence": 0.85,
            "key_findings": ["Bulls are strong"],
            "warnings": [],
            "win_rate": 0.66,
            "avg_pnl_pct": 4.1,
        }))]
        mock_response.usage = MagicMock(input_tokens=200, output_tokens=150)

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic", return_value=mock_client):
                result = analyze(_make_fills(30), dict(_DEFAULT_PARAMS), None)

        assert result is not None
        assert result.confidence == pytest.approx(0.85)
        assert result.tokens_used == 350

    def test_generate_commentary_returns_empty_when_no_key(self):
        from trauto.ai.analyst import generate_commentary
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": ""}):
            result = generate_commentary({}, None)
        assert result == ""

    def test_generate_commentary_returns_text_with_mock(self):
        from trauto.ai.analyst import generate_commentary
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Portfolio is performing well. Consider reducing exposure.")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            with patch("anthropic.Anthropic", return_value=mock_client):
                result = generate_commentary({"total_value": 10000, "daily_pnl": 50}, None)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# validator.py — SafetyValidator
# ---------------------------------------------------------------------------

class TestSafetyValidator:
    def _make_analysis(self, **overrides):
        from trauto.ai.analyst import AIAnalysis
        defaults = dict(
            proposed_params=dict(_DEFAULT_PARAMS),
            reasoning="test",
            confidence=0.80,
            key_findings=[],
            warnings=[],
            trade_count_analyzed=25,
            win_rate=0.60,
            avg_pnl_pct=3.0,
        )
        defaults.update(overrides)
        return AIAnalysis(**defaults)

    def test_passes_valid_analysis(self):
        from trauto.ai.validator import SafetyValidator
        analysis = self._make_analysis()
        result = SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS))
        assert result is analysis

    def test_rejects_insufficient_trades(self):
        from trauto.ai.validator import SafetyValidator
        analysis = self._make_analysis(trade_count_analyzed=15)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_rejects_low_win_rate(self):
        from trauto.ai.validator import SafetyValidator
        analysis = self._make_analysis(win_rate=0.20)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_rejects_low_confidence(self):
        from trauto.ai.validator import SafetyValidator
        analysis = self._make_analysis(confidence=0.50)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_rejects_too_many_params_changed(self):
        from trauto.ai.validator import SafetyValidator
        params = dict(_DEFAULT_PARAMS)
        # Change 4 params
        proposed = dict(params)
        proposed["direction_bullish_up_multiplier"] = 1.25
        proposed["direction_bullish_down_multiplier"] = 0.72
        proposed["rsi_overbought_multiplier"] = 0.88
        proposed["rsi_oversold_multiplier"] = 0.88
        analysis = self._make_analysis(proposed_params=proposed)
        assert SafetyValidator().validate(analysis, params) is None

    def test_rejects_param_out_of_bounds_high(self):
        from trauto.ai.validator import SafetyValidator
        proposed = dict(_DEFAULT_PARAMS)
        proposed["direction_bullish_up_multiplier"] = 1.99  # above max 1.50
        analysis = self._make_analysis(proposed_params=proposed)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_rejects_param_out_of_bounds_low(self):
        from trauto.ai.validator import SafetyValidator
        proposed = dict(_DEFAULT_PARAMS)
        proposed["direction_bullish_up_multiplier"] = 0.20  # below min 0.50
        analysis = self._make_analysis(proposed_params=proposed)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_rejects_bonus_out_of_bounds(self):
        from trauto.ai.validator import SafetyValidator
        proposed = dict(_DEFAULT_PARAMS)
        proposed["macd_crossover_bonus"] = 0.20  # above max 0.15
        analysis = self._make_analysis(proposed_params=proposed)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_rejects_param_change_too_large(self):
        from trauto.ai.validator import SafetyValidator
        current = dict(_DEFAULT_PARAMS)
        proposed = dict(current)
        # Change by 25% (max allowed is 20%)
        proposed["direction_bullish_up_multiplier"] = current["direction_bullish_up_multiplier"] * 1.25
        analysis = self._make_analysis(proposed_params=proposed)
        assert SafetyValidator().validate(analysis, current) is None

    def test_rejects_protected_env_param(self):
        from trauto.ai.validator import SafetyValidator
        proposed = dict(_DEFAULT_PARAMS)
        proposed["poly_dry_run"] = 0.0
        analysis = self._make_analysis(proposed_params=proposed)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_rejects_unknown_param(self):
        from trauto.ai.validator import SafetyValidator
        proposed = dict(_DEFAULT_PARAMS)
        proposed["some_unknown_param"] = 1.0
        analysis = self._make_analysis(proposed_params=proposed)
        assert SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS)) is None

    def test_confidence_tier_auto_apply(self):
        """High confidence + low impact → should return valid analysis."""
        from trauto.ai.validator import SafetyValidator, compute_change_impact
        proposed = dict(_DEFAULT_PARAMS)
        proposed["direction_bullish_up_multiplier"] = 1.22  # 1.7% change
        analysis = self._make_analysis(confidence=0.92, proposed_params=proposed)
        result = SafetyValidator().validate(analysis, dict(_DEFAULT_PARAMS))
        assert result is not None
        impact = compute_change_impact(proposed, dict(_DEFAULT_PARAMS))
        assert impact < 0.10  # under auto-apply threshold


# ---------------------------------------------------------------------------
# loop.py — confidence tier routing
# ---------------------------------------------------------------------------

class TestConfidenceTierRouting:
    def _make_analysis(self, confidence: float = 0.85, proposed_params=None, **kw):
        from trauto.ai.analyst import AIAnalysis
        return AIAnalysis(
            proposed_params=proposed_params if proposed_params is not None else dict(_DEFAULT_PARAMS),
            reasoning="test",
            confidence=confidence,
            key_findings=[],
            warnings=[],
            trade_count_analyzed=25,
            win_rate=0.60,
            avg_pnl_pct=3.0,
            **kw,
        )

    def test_high_confidence_low_impact_auto_applies(self):
        """confidence >= 0.90 and impact <= 10% → auto_apply_hours=None, apply immediately."""
        from trauto.ai.loop import _apply_or_queue
        from trauto.ai.analyst import AIAnalysis

        params = dict(_DEFAULT_PARAMS)
        proposed = dict(params)
        proposed["direction_bullish_up_multiplier"] = 1.22  # small change

        analysis = self._make_analysis(confidence=0.92, proposed_params=proposed)

        mock_repo = MagicMock()
        mock_repo.create_proposal.return_value = 1
        mock_repo.apply_proposal.return_value = True

        outcome, pid = _apply_or_queue(mock_repo, analysis, params, 0.017)
        assert outcome == "auto_applied"
        assert pid == 1
        # auto_apply_hours should be None (immediate)
        _, kwargs = mock_repo.create_proposal.call_args
        assert kwargs.get("auto_apply_hours") is None

    def test_moderate_confidence_queues_with_timer(self):
        from trauto.ai.loop import _apply_or_queue
        params = dict(_DEFAULT_PARAMS)
        analysis = self._make_analysis(confidence=0.80)
        mock_repo = MagicMock()
        mock_repo.create_proposal.return_value = 2

        outcome, pid = _apply_or_queue(mock_repo, analysis, params, 0.05)
        assert outcome == "queued_with_timer"
        _, kwargs = mock_repo.create_proposal.call_args
        assert kwargs.get("auto_apply_hours") is not None

    def test_low_confidence_queues_manual(self):
        from trauto.ai.loop import _apply_or_queue
        params = dict(_DEFAULT_PARAMS)
        analysis = self._make_analysis(confidence=0.65)
        mock_repo = MagicMock()
        mock_repo.create_proposal.return_value = 3

        outcome, pid = _apply_or_queue(mock_repo, analysis, params, 0.05)
        assert outcome == "queued_manual"
        _, kwargs = mock_repo.create_proposal.call_args
        assert kwargs.get("auto_apply_hours") is None


# ---------------------------------------------------------------------------
# Auto-apply countdown logic
# ---------------------------------------------------------------------------

class TestAutoApplyCountdown:
    def test_auto_apply_after_is_set_for_moderate_confidence(self):
        from trauto.ai.loop import _apply_or_queue
        from trauto.ai.analyst import AIAnalysis
        from datetime import datetime, timezone

        params = dict(_DEFAULT_PARAMS)
        analysis = AIAnalysis(
            proposed_params=params, reasoning="r", confidence=0.80,
            key_findings=[], warnings=[], trade_count_analyzed=25,
            win_rate=0.60, avg_pnl_pct=2.0,
        )
        mock_repo = MagicMock()
        mock_repo.create_proposal.return_value = 5

        with patch.dict("os.environ", {"POLY_AI_AUTO_APPLY_HOURS": "4"}):
            _apply_or_queue(mock_repo, analysis, params, 0.05)

        _, kwargs = mock_repo.create_proposal.call_args
        assert kwargs["auto_apply_hours"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# DB migration — idempotent seed
# ---------------------------------------------------------------------------

class TestSignalParamsSeed:
    def test_seed_is_idempotent(self, tmp_path):
        """Calling seed twice should not duplicate rows."""
        from trauto.ai.db import AIRepository
        from src.persistence.store import DatabaseStore

        db_url = f"sqlite:///{tmp_path}/test_ai.db"
        store = DatabaseStore(database_url=db_url)

        from src.persistence.models import Base
        Base.metadata.create_all(store.engine)

        repo = AIRepository(store=store)
        seeded1 = repo.seed_signal_params_if_needed()
        seeded2 = repo.seed_signal_params_if_needed()
        assert seeded1 is True
        assert seeded2 is False  # no-op second time

    def test_seed_loads_defaults(self, tmp_path):
        from trauto.ai.db import AIRepository
        from src.persistence.store import DatabaseStore

        db_url = f"sqlite:///{tmp_path}/test_ai2.db"
        store = DatabaseStore(database_url=db_url)

        from src.persistence.models import Base
        Base.metadata.create_all(store.engine)

        repo = AIRepository(store=store)
        repo.seed_signal_params_if_needed()
        params = repo.load_signal_params()
        assert params["direction_bullish_up_multiplier"] == pytest.approx(1.20)
        assert len(params) >= 14


# ---------------------------------------------------------------------------
# API endpoint response shapes (lightweight — no real server needed)
# ---------------------------------------------------------------------------

class TestAIAPIEndpoints:
    def _make_repo_mock(self):
        mock = MagicMock()
        mock.get_last_analysis_at.return_value = None
        mock.has_pending_proposal.return_value = False
        mock.list_proposals.return_value = []
        mock.list_analysis_logs.return_value = []
        mock.get_monthly_token_usage.return_value = 0
        mock.get_kv.return_value = None
        return mock

    def test_get_ai_status_shape(self):
        from src.dashboard.api import get_ai_status
        with patch("src.dashboard.api._get_ai_repo", return_value=self._make_repo_mock()):
            response = get_ai_status()
        data = json.loads(response.body)
        assert "last_analysis_at" in data
        assert "pending_proposals" in data
        assert "monthly_tokens_used" in data
        assert "monthly_token_budget" in data

    def test_get_ai_proposals_shape(self):
        from src.dashboard.api import get_ai_proposals
        with patch("src.dashboard.api._get_ai_repo", return_value=self._make_repo_mock()):
            response = get_ai_proposals()
        data = json.loads(response.body)
        assert "proposals" in data
        assert isinstance(data["proposals"], list)

    def test_get_ai_log_shape(self):
        from src.dashboard.api import get_ai_log
        with patch("src.dashboard.api._get_ai_repo", return_value=self._make_repo_mock()):
            response = get_ai_log()
        data = json.loads(response.body)
        assert "log" in data
        assert isinstance(data["log"], list)

    def test_get_ai_commentary_no_data(self):
        from src.dashboard.api import get_ai_commentary
        with patch("src.dashboard.api._get_ai_repo", return_value=self._make_repo_mock()):
            response = get_ai_commentary()
        data = json.loads(response.body)
        assert "commentary" in data
        assert data["commentary"] is None


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------

class TestTokenBudget:
    def test_analysis_skips_when_budget_exceeded(self, tmp_path):
        from trauto.ai.db import AIRepository
        from src.persistence.store import DatabaseStore
        from trauto.ai.loop import _run_scheduled_analysis

        db_url = f"sqlite:///{tmp_path}/test_budget.db"
        store = DatabaseStore(database_url=db_url)
        from src.persistence.models import Base
        Base.metadata.create_all(store.engine)

        repo = AIRepository(store=store)
        repo.seed_signal_params_if_needed()
        # Exhaust budget
        repo.add_monthly_token_usage(200000)

        with patch.dict("os.environ", {
            "DATABASE_URL": db_url,
            "AI_MONTHLY_TOKEN_BUDGET": "100000",
        }):
            result = _run_scheduled_analysis(db_url, force=True)

        assert result.get("reason") == "token_budget_exceeded"
        assert result.get("skipped") is True
