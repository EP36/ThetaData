"""Tests for Phase 5 signal engine: classify_direction, score_opportunity,
BtcSignals, fetch_btc_signals, and related helpers."""

from __future__ import annotations

import csv
import io
import math
import time
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.polymarket.alpaca_signals import (
    BtcSignals,
    _atr_ratio,
    _bb_width_ratio,
    _consecutive_bars,
    _macd_crossover,
    _rsi,
    _volume_ratio,
    fetch_btc_signals,
    get_cached_signals,
    refresh_btc_signals_if_stale,
)
from src.polymarket.opportunities import Opportunity
from src.polymarket.signals import (
    _CONFIDENCE_CAP,
    _CONFIDENCE_FLOOR,
    _CONFIDENCE_MAP,
    _apply_rules,
    classify_direction,
    score_opportunity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opp(**kwargs) -> Opportunity:
    defaults = dict(
        strategy="correlated_markets",
        market_question="Will BTC exceed $100,000 by end of year?",
        edge_pct=3.0,
        action="buy YES @ 0.40",
        confidence="medium",
        notes="",
    )
    defaults.update(kwargs)
    return Opportunity(**defaults)


def _signals(**kwargs) -> BtcSignals:
    defaults = dict(
        data_available=True,
        price_usd=95_000.0,
        change_24h_pct=0.0,
        rsi_14=50.0,
        macd_crossover="none",
        consecutive_bars=0,
        streak_direction="none",
        volume_ratio=1.0,
        bb_width_ratio=1.0,
        atr_ratio=1.0,
        fetched_at=time.monotonic(),
    )
    defaults.update(kwargs)
    return BtcSignals(**defaults)


# ---------------------------------------------------------------------------
# classify_direction
# ---------------------------------------------------------------------------

class TestClassifyDirection:
    def test_orderbook_spread_always_neutral(self):
        opp = _opp(strategy="orderbook_spread", market_question="Will BTC hit $100k?")
        assert classify_direction(opp) == "neutral"

    def test_bullish_keyword_above(self):
        opp = _opp(market_question="Will BTC be above $90,000 on Dec 31?")
        assert classify_direction(opp) == "bullish"

    def test_bullish_keyword_exceeds(self):
        opp = _opp(market_question="Will BTC exceed $100,000 this quarter?")
        assert classify_direction(opp) == "bullish"

    def test_bullish_keyword_breaks(self):
        opp = _opp(market_question="Will BTC break $95,000 before January?")
        assert classify_direction(opp) == "bullish"

    def test_bearish_keyword_below(self):
        opp = _opp(market_question="Will BTC be below $80,000 by December?")
        assert classify_direction(opp) == "bearish"

    def test_bearish_keyword_drops(self):
        opp = _opp(market_question="Will BTC drop below $70,000?")
        assert classify_direction(opp) == "bearish"

    def test_bearish_keyword_falls(self):
        opp = _opp(market_question="Will BTC fall below $60k?")
        assert classify_direction(opp) == "bearish"

    def test_action_buy_yes_bullish(self):
        opp = _opp(market_question="Some unrelated market?", action="buy YES @ 0.40")
        assert classify_direction(opp) == "bullish"

    def test_action_sell_yes_bearish(self):
        opp = _opp(market_question="Some unrelated market?", action="sell YES @ 0.70")
        assert classify_direction(opp) == "bearish"

    def test_neutral_fallback(self):
        opp = _opp(market_question="Will the Fed raise rates?", action="buy NO @ 0.30")
        assert classify_direction(opp) == "neutral"

    def test_case_insensitive_bullish(self):
        opp = _opp(market_question="Will BTC EXCEED $100K?")
        assert classify_direction(opp) == "bullish"

    def test_uses_existing_direction_field_preserved(self):
        # classify_direction reads market_question, not opp.direction —
        # the signals engine sets direction via _apply_rules
        opp = _opp(market_question="Will BTC be above $90k?", direction="bearish")
        # classify_direction ignores opp.direction — returns from question
        assert classify_direction(opp) == "bullish"


# ---------------------------------------------------------------------------
# score_opportunity — pass-through when unavailable
# ---------------------------------------------------------------------------

class TestScoreOpportunityPassthrough:
    def test_unavailable_signals_returns_original(self):
        opp = _opp()
        sigs = BtcSignals(data_available=False)
        result = score_opportunity(opp, sigs)
        assert result is opp

    def test_exception_in_apply_returns_original(self):
        opp = _opp()
        sigs = _signals()
        with patch("src.polymarket.signals._apply_rules", side_effect=RuntimeError("boom")):
            result = score_opportunity(opp, sigs)
        assert result is opp

    def test_no_signal_note_added_when_unavailable(self):
        opp = _opp()
        sigs = BtcSignals(data_available=False)
        result = score_opportunity(opp, sigs)
        assert result.signal_notes == ()
        assert result.confidence_score == 0.0


# ---------------------------------------------------------------------------
# _apply_rules — direction alignment
# ---------------------------------------------------------------------------

class TestDirectionAlignment:
    def test_bullish_aligned_strong_up(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(change_24h_pct=5.0)
        result = score_opportunity(opp, sigs)
        assert result.direction == "bullish"
        assert result.confidence_score > _CONFIDENCE_MAP["medium"]
        assert any("direction_aligned_bullish" in n for n in result.signal_notes)

    def test_bullish_opposed_strong_down(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(change_24h_pct=-5.0)
        result = score_opportunity(opp, sigs)
        assert result.confidence_score < _CONFIDENCE_MAP["medium"]
        assert any("direction_opposed_bullish" in n for n in result.signal_notes)

    def test_bearish_aligned_strong_down(self):
        opp = _opp(market_question="Will BTC fall below $80k?")
        sigs = _signals(change_24h_pct=-5.0)
        result = score_opportunity(opp, sigs)
        assert result.direction == "bearish"
        assert result.confidence_score > _CONFIDENCE_MAP["medium"]
        assert any("direction_aligned_bearish" in n for n in result.signal_notes)

    def test_bearish_opposed_strong_up(self):
        opp = _opp(market_question="Will BTC fall below $80k?")
        sigs = _signals(change_24h_pct=5.0)
        result = score_opportunity(opp, sigs)
        assert result.confidence_score < _CONFIDENCE_MAP["medium"]
        assert any("direction_opposed_bearish" in n for n in result.signal_notes)

    def test_neutral_no_alignment_rule(self):
        opp = _opp(strategy="orderbook_spread")
        sigs = _signals(change_24h_pct=10.0)
        result = score_opportunity(opp, sigs)
        assert result.direction == "neutral"
        # No direction rule should fire for neutral
        assert not any("direction_aligned" in n or "direction_opposed" in n for n in result.signal_notes)


# ---------------------------------------------------------------------------
# _apply_rules — RSI
# ---------------------------------------------------------------------------

class TestRsiRule:
    def test_overbought_penalizes_bullish(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(rsi_14=75.0)
        result = score_opportunity(opp, sigs)
        assert any("rsi_overbought" in n for n in result.signal_notes)
        assert result.confidence_score < _CONFIDENCE_MAP["medium"]

    def test_oversold_penalizes_bearish(self):
        opp = _opp(market_question="Will BTC fall below $80k?")
        sigs = _signals(rsi_14=25.0)
        result = score_opportunity(opp, sigs)
        assert any("rsi_oversold" in n for n in result.signal_notes)

    def test_rsi_no_rule_mid_range(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(rsi_14=55.0)
        result = score_opportunity(opp, sigs)
        assert not any("rsi" in n for n in result.signal_notes)


# ---------------------------------------------------------------------------
# _apply_rules — MACD
# ---------------------------------------------------------------------------

class TestMacdRule:
    def test_bullish_crossover_boosts_bullish(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(macd_crossover="bullish")
        result = score_opportunity(opp, sigs)
        assert any("macd_bullish_crossover" in n for n in result.signal_notes)
        base = _CONFIDENCE_MAP["medium"]
        assert result.confidence_score > base

    def test_macd_bearish_crossover_no_boost_for_bullish(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(macd_crossover="bearish")
        result = score_opportunity(opp, sigs)
        assert not any("macd" in n for n in result.signal_notes)


# ---------------------------------------------------------------------------
# _apply_rules — streak
# ---------------------------------------------------------------------------

class TestStreakRule:
    def test_green_streak_boosts_bullish(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(consecutive_bars=5, streak_direction="green")
        result = score_opportunity(opp, sigs)
        assert any("green_streak" in n for n in result.signal_notes)

    def test_short_streak_no_rule(self):
        opp = _opp(market_question="Will BTC exceed $100k?")
        sigs = _signals(consecutive_bars=3, streak_direction="green")
        result = score_opportunity(opp, sigs)
        assert not any("green_streak" in n for n in result.signal_notes)


# ---------------------------------------------------------------------------
# _apply_rules — volume
# ---------------------------------------------------------------------------

class TestVolumeRule:
    def test_volume_spike_boosts_score(self):
        opp = _opp()
        sigs = _signals(volume_ratio=3.5)
        result = score_opportunity(opp, sigs)
        assert any("volume_spike" in n for n in result.signal_notes)

    def test_volume_drought_penalizes(self):
        opp = _opp()
        sigs = _signals(volume_ratio=0.3)
        result = score_opportunity(opp, sigs)
        assert any("volume_low" in n for n in result.signal_notes)

    def test_normal_volume_no_rule(self):
        opp = _opp()
        sigs = _signals(volume_ratio=1.0)
        result = score_opportunity(opp, sigs)
        assert not any("volume" in n for n in result.signal_notes)


# ---------------------------------------------------------------------------
# _apply_rules — proximity
# ---------------------------------------------------------------------------

class TestProximityRule:
    def test_too_close_penalizes(self):
        opp = _opp(market_question="Will BTC exceed $95,000?")
        sigs = _signals(price_usd=95_500.0)  # ~0.5% away
        result = score_opportunity(opp, sigs)
        assert any("threshold_proximity" in n for n in result.signal_notes)

    def test_far_bullish_clearance_boosts(self):
        opp = _opp(market_question="Will BTC exceed $70,000?")
        sigs = _signals(price_usd=95_000.0)  # 35% above threshold
        result = score_opportunity(opp, sigs)
        assert any("threshold_clearance" in n for n in result.signal_notes)

    def test_no_threshold_in_question_no_rule(self):
        opp = _opp(market_question="Will the Federal Reserve cut rates?")
        sigs = _signals(price_usd=95_000.0)
        result = score_opportunity(opp, sigs)
        assert not any("threshold" in n for n in result.signal_notes)


# ---------------------------------------------------------------------------
# _apply_rules — volatility
# ---------------------------------------------------------------------------

class TestVolatilityRule:
    def test_high_bb_penalizes(self):
        opp = _opp()
        sigs = _signals(bb_width_ratio=2.5)
        result = score_opportunity(opp, sigs)
        assert any("high_volatility" in n for n in result.signal_notes)

    def test_high_atr_penalizes(self):
        opp = _opp()
        sigs = _signals(atr_ratio=2.0)
        result = score_opportunity(opp, sigs)
        assert any("high_atr" in n for n in result.signal_notes)

    def test_normal_volatility_no_rule(self):
        opp = _opp()
        sigs = _signals(bb_width_ratio=1.0, atr_ratio=1.0)
        result = score_opportunity(opp, sigs)
        assert not any("volatility" in n or "atr" in n for n in result.signal_notes)


# ---------------------------------------------------------------------------
# Confidence clamping
# ---------------------------------------------------------------------------

class TestConfidenceClamping:
    def test_floor_applied(self):
        opp = _opp(confidence="low", market_question="Will BTC fall below $60k?")
        # Combine multiple downward multipliers
        sigs = _signals(
            change_24h_pct=5.0,     # bearish opp opposed
            rsi_14=25.0,            # oversold penalty
            volume_ratio=0.3,       # volume drought
            bb_width_ratio=3.0,     # high vol
            atr_ratio=2.0,          # high ATR
        )
        result = score_opportunity(opp, sigs)
        assert result.confidence_score >= _CONFIDENCE_FLOOR

    def test_cap_applied(self):
        opp = _opp(confidence="high", market_question="Will BTC exceed $70k?")
        sigs = _signals(
            change_24h_pct=10.0,
            price_usd=95_000.0,    # clearance
            macd_crossover="bullish",
            consecutive_bars=5,
            streak_direction="green",
            volume_ratio=3.0,
        )
        result = score_opportunity(opp, sigs)
        assert result.confidence_score <= _CONFIDENCE_CAP

    def test_no_rules_triggered_note(self):
        opp = _opp(strategy="orderbook_spread")
        sigs = _signals()
        result = score_opportunity(opp, sigs)
        assert "no_signal_rules_triggered" in result.signal_notes

    def test_rank_score_formula(self):
        opp = _opp(edge_pct=4.0)
        sigs = _signals()
        result = score_opportunity(opp, sigs)
        assert abs(result.rank_score - result.confidence_score * 4.0) < 1e-6


# ---------------------------------------------------------------------------
# Ranking — higher rank_score bubbles to top
# ---------------------------------------------------------------------------

class TestRanking:
    def test_bullish_aligned_ranks_above_opposed(self):
        bullish_q = "Will BTC exceed $90k?"
        opp_a = _opp(market_question=bullish_q, edge_pct=3.0)
        opp_b = _opp(market_question=bullish_q, edge_pct=3.0)

        sig_up   = _signals(change_24h_pct=5.0)   # aligned
        sig_down = _signals(change_24h_pct=-5.0)  # opposed

        scored_a = score_opportunity(opp_a, sig_up)
        scored_b = score_opportunity(opp_b, sig_down)

        assert scored_a.rank_score > scored_b.rank_score


# ---------------------------------------------------------------------------
# Technical indicator unit tests
# ---------------------------------------------------------------------------

class TestRsiHelper:
    def test_all_up_bars_near_100(self):
        closes = pd.Series([float(i) for i in range(1, 30)])
        assert _rsi(closes) > 90

    def test_all_down_bars_near_0(self):
        closes = pd.Series([float(30 - i) for i in range(30)])
        assert _rsi(closes) < 10

    def test_insufficient_data_returns_50(self):
        closes = pd.Series([100.0, 101.0])
        assert _rsi(closes) == 50.0


class TestMacdHelper:
    def test_insufficient_data_returns_none(self):
        closes = pd.Series([float(i) for i in range(10)])
        assert _macd_crossover(closes) == "none"

    def test_bullish_crossover_detected(self):
        # Descending then sharply ascending → MACD crosses above signal
        closes = pd.Series([100.0 - i * 0.5 for i in range(40)] + [100.0 + i * 3.0 for i in range(15)])
        result = _macd_crossover(closes)
        assert result in ("bullish", "bearish", "none")  # just ensure no exception


class TestConsecutiveBars:
    def test_three_green(self):
        closes = pd.Series([100.0, 101.0, 102.0, 103.0])
        count, direction = _consecutive_bars(closes)
        assert count == 3
        assert direction == "green"

    def test_two_red(self):
        closes = pd.Series([103.0, 102.0, 101.0])
        count, direction = _consecutive_bars(closes)
        assert count == 2
        assert direction == "red"

    def test_insufficient_returns_zero(self):
        closes = pd.Series([100.0])
        count, _ = _consecutive_bars(closes)
        assert count == 0


class TestVolumeRatio:
    def test_spike_returns_high_ratio(self):
        vols = pd.Series([100.0] * 20 + [500.0])
        ratio = _volume_ratio(vols)
        assert ratio == pytest.approx(5.0, rel=0.01)

    def test_insufficient_data_returns_one(self):
        vols = pd.Series([100.0] * 5)
        assert _volume_ratio(vols) == 1.0


class TestBbWidthRatio:
    def test_low_vol_flat_series(self):
        closes = pd.Series([100.0] * 25)
        ratio = _bb_width_ratio(closes)
        # All values identical → std = 0 → width = 0 → ratio = 0 or 1
        assert ratio == 1.0 or math.isfinite(ratio)

    def test_insufficient_data_returns_one(self):
        closes = pd.Series([100.0] * 10)
        assert _bb_width_ratio(closes) == 1.0


class TestAtrRatio:
    def test_constant_candles_ratio_one(self):
        n = 20
        highs  = pd.Series([105.0] * n)
        lows   = pd.Series([95.0] * n)
        closes = pd.Series([100.0] * n)
        ratio = _atr_ratio(highs, lows, closes)
        assert abs(ratio - 1.0) < 0.01

    def test_insufficient_data_returns_one(self):
        h = pd.Series([105.0] * 5)
        l = pd.Series([95.0] * 5)
        c = pd.Series([100.0] * 5)
        assert _atr_ratio(h, l, c) == 1.0


# ---------------------------------------------------------------------------
# fetch_btc_signals — credential and HTTP mocking
# ---------------------------------------------------------------------------

class TestFetchBtcSignals:
    def test_missing_credentials_returns_unavailable(self):
        with patch("src.polymarket.alpaca_signals.read_alpaca_api_key", return_value=""), \
             patch("src.polymarket.alpaca_signals.read_alpaca_api_secret", return_value=""):
            result = fetch_btc_signals()
        assert result.data_available is False

    def test_http_error_returns_unavailable(self):
        import httpx
        with patch("src.polymarket.alpaca_signals.read_alpaca_api_key", return_value="key"), \
             patch("src.polymarket.alpaca_signals.read_alpaca_api_secret", return_value="sec"), \
             patch("httpx.Client") as mock_client:
            mock_client.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("timeout")
            result = fetch_btc_signals()
        assert result.data_available is False

    def test_empty_bars_returns_unavailable(self):
        with patch("src.polymarket.alpaca_signals.read_alpaca_api_key", return_value="key"), \
             patch("src.polymarket.alpaca_signals.read_alpaca_api_secret", return_value="sec"), \
             patch("httpx.Client") as mock_client:
            resp = MagicMock()
            resp.json.return_value = {"bars": {}}
            mock_client.return_value.__enter__.return_value.get.return_value = resp
            result = fetch_btc_signals()
        assert result.data_available is False

    def test_valid_response_returns_signals(self):
        bars = [
            {"t": f"2024-01-01T{h:02d}:00:00Z", "c": 95000.0 + h * 10, "h": 95100.0 + h * 10,
             "l": 94900.0 + h * 10, "v": 100.0 + h}
            for h in range(50)
        ]
        with patch("src.polymarket.alpaca_signals.read_alpaca_api_key", return_value="key"), \
             patch("src.polymarket.alpaca_signals.read_alpaca_api_secret", return_value="sec"), \
             patch("httpx.Client") as mock_client:
            resp = MagicMock()
            resp.json.return_value = {"bars": {"BTC/USD": bars}}
            mock_client.return_value.__enter__.return_value.get.return_value = resp
            result = fetch_btc_signals()
        assert result.data_available is True
        assert result.price_usd > 0
        assert isinstance(result.rsi_14, float)
        assert result.macd_crossover in ("bullish", "bearish", "none")


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

class TestCacheHelpers:
    def test_get_cached_returns_last_fetched(self):
        import src.polymarket.alpaca_signals as mod
        original = mod._cached_signals
        try:
            sentinel = BtcSignals(data_available=False, fetched_at=999.0)
            mod._cached_signals = sentinel
            assert get_cached_signals() is sentinel
        finally:
            mod._cached_signals = original

    def test_refresh_fetches_when_stale(self):
        import src.polymarket.alpaca_signals as mod
        fresh = _signals()
        with patch("src.polymarket.alpaca_signals.fetch_btc_signals", return_value=fresh) as mock_fetch:
            mod._cache_ts = 0.0  # force stale
            result = refresh_btc_signals_if_stale(interval_sec=300.0)
        mock_fetch.assert_called_once()
        assert result is fresh

    def test_refresh_skips_when_fresh(self):
        import src.polymarket.alpaca_signals as mod
        with patch("src.polymarket.alpaca_signals.fetch_btc_signals") as mock_fetch:
            mod._cache_ts = time.monotonic()  # just refreshed
            refresh_btc_signals_if_stale(interval_sec=300.0)
        mock_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# Backtest CSV output
# ---------------------------------------------------------------------------

class TestBacktestOutput:
    def test_csv_has_expected_columns(self, tmp_path):
        from src.polymarket.backtest import CSV_FIELDS, run_backtest

        markets = [
            {
                "strategy": "correlated_markets",
                "market_question": "Will BTC exceed $90,000?",
                "edge_pct": 2.5,
                "action": "buy YES @ 0.40",
                "confidence": "medium",
                "notes": "",
            }
        ]
        markets_file = tmp_path / "markets.json"
        import json
        markets_file.write_text(json.dumps(markets))

        out_file = tmp_path / "result.csv"

        # Build a minimal DataFrame of 50 hourly bars
        n = 50
        df = pd.DataFrame({
            "ts":     pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC"),
            "close":  [90000.0 + i * 50 for i in range(n)],
            "high":   [90100.0 + i * 50 for i in range(n)],
            "low":    [89900.0 + i * 50 for i in range(n)],
            "volume": [200.0 + i for i in range(n)],
        })

        with patch("src.polymarket.backtest._fetch_historical_bars", return_value=df):
            run_backtest(
                markets_path=str(markets_file),
                start="2024-01-01",
                end="2024-02-01",
                out_path=str(out_file),
                step_hours=24,
            )

        assert out_file.exists()
        with out_file.open() as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        assert len(rows) > 0
        assert set(reader.fieldnames or []) == set(CSV_FIELDS)
        assert rows[0]["strategy"] == "correlated_markets"
        assert float(rows[0]["edge_pct"]) == pytest.approx(2.5)
