"""BTC signal fetcher using Alpaca crypto market data.

Fetches recent hourly BTC/USD bars from the Alpaca crypto endpoint and
computes technical indicators used by the signal scoring engine.

Public API:
  BtcSignals          — frozen dataclass with all indicator fields
  fetch_btc_signals() — fetch fresh data and return BtcSignals
  get_cached_signals()         — return cached BtcSignals (stale-ok)
  refresh_btc_signals_if_stale(interval_sec) — refresh if cache is old
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass, field

import httpx
import pandas as pd

from src.config.alpaca import read_alpaca_api_key, read_alpaca_api_secret, read_alpaca_data_base_url

LOGGER = logging.getLogger("theta.polymarket.alpaca_signals")

_CRYPTO_PATH = "/v1beta3/crypto/us/bars"
_SYMBOL = "BTC/USD"
_TIMEFRAME = "1H"
_BAR_LIMIT = 120   # ~5 days of hourly bars; enough for all indicators


def _read_signal_provider() -> str:
    """Return the configured BTC signal provider."""
    return os.getenv("SIGNAL_PROVIDER", "synthetic").strip().lower() or "synthetic"

# ---------------------------------------------------------------------------
# BtcSignals dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BtcSignals:
    """Snapshot of BTC market signals derived from recent hourly bars."""

    data_available: bool

    # Price
    price_usd: float = 0.0
    change_24h_pct: float = 0.0

    # Momentum
    rsi_14: float = 50.0
    macd_crossover: str = "none"     # "bullish" | "bearish" | "none"
    consecutive_bars: int = 0
    streak_direction: str = "none"   # "green" | "red" | "none"

    # Volume
    volume_ratio: float = 1.0        # last bar volume / 20-bar avg

    # Volatility
    bb_width_ratio: float = 1.0      # current BB width / 20-bar avg BB width
    atr_ratio: float = 1.0           # current ATR(14) / 14-bar avg ATR

    # Metadata
    fetched_at: float = field(default=0.0)


# ---------------------------------------------------------------------------
# Technical indicator helpers
# ---------------------------------------------------------------------------

def _rsi(closes: pd.Series, period: int = 14) -> float:
    """Wilder's RSI for the last bar."""
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    # Wilder smoothing
    avg_gain = gain.iloc[:period].mean()
    avg_loss = loss.iloc[:period].mean()
    for g, l in zip(gain.iloc[period:], loss.iloc[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _macd_crossover(closes: pd.Series) -> str:
    """Return 'bullish', 'bearish', or 'none' based on MACD(12,26,9) crossover."""
    if len(closes) < 27:
        return "none"
    fast = _ema(closes, 12)
    slow = _ema(closes, 26)
    macd_line = fast - slow
    signal_line = _ema(macd_line, 9)
    if len(macd_line) < 2:
        return "none"
    prev_diff = macd_line.iloc[-2] - signal_line.iloc[-2]
    curr_diff = macd_line.iloc[-1] - signal_line.iloc[-1]
    if prev_diff < 0 and curr_diff >= 0:
        return "bullish"
    if prev_diff > 0 and curr_diff <= 0:
        return "bearish"
    return "none"


def _consecutive_bars(closes: pd.Series) -> tuple[int, str]:
    """Return (count, direction) of the current green/red streak."""
    if len(closes) < 2:
        return 0, "none"
    diffs = closes.diff().dropna()
    last_sign = math.copysign(1, diffs.iloc[-1])
    count = 0
    for d in reversed(diffs.tolist()):
        if d == 0:
            break
        if math.copysign(1, d) != last_sign:
            break
        count += 1
    direction = "green" if last_sign > 0 else "red"
    return count, direction


def _volume_ratio(volumes: pd.Series, window: int = 20) -> float:
    if len(volumes) < window + 1:
        return 1.0
    avg = volumes.iloc[-(window + 1):-1].mean()
    if avg == 0:
        return 1.0
    return float(volumes.iloc[-1] / avg)


def _bb_width_ratio(closes: pd.Series, window: int = 20) -> float:
    """Ratio of current Bollinger Band width to average width over the series."""
    if len(closes) < window:
        return 1.0
    rolling_mean = closes.rolling(window).mean()
    rolling_std = closes.rolling(window).std()
    upper = rolling_mean + 2 * rolling_std
    lower = rolling_mean - 2 * rolling_std
    width = (upper - lower) / rolling_mean.replace(0, float("nan"))
    width = width.dropna()
    if len(width) < 2:
        return 1.0
    avg_width = width.iloc[:-1].mean()
    if avg_width == 0:
        return 1.0
    return float(width.iloc[-1] / avg_width)


def _atr_ratio(highs: pd.Series, lows: pd.Series, closes: pd.Series, period: int = 14) -> float:
    """Ratio of current ATR to the average ATR over the series."""
    if len(closes) < period + 1:
        return 1.0
    prev_close = closes.shift(1)
    tr = pd.concat([
        highs - lows,
        (highs - prev_close).abs(),
        (lows - prev_close).abs(),
    ], axis=1).max(axis=1).dropna()
    if len(tr) < period:
        return 1.0
    # Wilder smoothing
    atr = tr.iloc[:period].mean()
    for val in tr.iloc[period:]:
        atr = (atr * (period - 1) + val) / period
    avg_atr = tr.mean()
    if avg_atr == 0:
        return 1.0
    return float(atr / avg_atr)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_btc_signals(
    timeout: float = 15.0,
    bar_limit: int = _BAR_LIMIT,
) -> BtcSignals:
    """Fetch recent BTC/USD hourly bars and compute signals.

    Returns a BtcSignals with data_available=False when credentials are
    absent or the Alpaca request fails.
    """
    signal_provider = _read_signal_provider()
    if signal_provider != "alpaca":
        LOGGER.info(
            "btc_signals_unavailable reason=signal_provider_disabled signal_provider=%s",
            signal_provider,
        )
        return BtcSignals(data_available=False, fetched_at=time.monotonic())

    api_key = read_alpaca_api_key()
    api_secret = read_alpaca_api_secret()
    if not api_key or not api_secret:
        LOGGER.debug("btc_signals_unavailable reason=missing_alpaca_credentials")
        return BtcSignals(data_available=False, fetched_at=time.monotonic())

    base_url = read_alpaca_data_base_url()
    try:
        with httpx.Client(base_url=base_url, timeout=timeout) as client:
            resp = client.get(
                _CRYPTO_PATH,
                params={
                    "symbols": _SYMBOL,
                    "timeframe": _TIMEFRAME,
                    "limit": bar_limit,
                    "sort": "asc",
                },
                headers={
                    "APCA-API-KEY-ID": api_key,
                    "APCA-API-SECRET-KEY": api_secret,
                },
            )
            resp.raise_for_status()
    except Exception as exc:
        LOGGER.warning("btc_signals_fetch_failed error=%s", exc)
        return BtcSignals(data_available=False, fetched_at=time.monotonic())

    raw = resp.json()
    bars = raw.get("bars", {}).get(_SYMBOL, [])
    if not bars:
        LOGGER.warning("btc_signals_empty_response symbol=%s", _SYMBOL)
        return BtcSignals(data_available=False, fetched_at=time.monotonic())

    df = pd.DataFrame({
        "close":  [b.get("c", 0.0) for b in bars],
        "high":   [b.get("h", 0.0) for b in bars],
        "low":    [b.get("l", 0.0) for b in bars],
        "volume": [b.get("v", 0.0) for b in bars],
    })
    closes  = df["close"].astype(float)
    highs   = df["high"].astype(float)
    lows    = df["low"].astype(float)
    volumes = df["volume"].astype(float)

    price_usd   = float(closes.iloc[-1])
    price_24h   = float(closes.iloc[-25]) if len(closes) >= 25 else float(closes.iloc[0])
    change_24h  = (price_usd - price_24h) / price_24h * 100.0 if price_24h != 0 else 0.0

    streak_count, streak_dir = _consecutive_bars(closes)

    signals = BtcSignals(
        data_available=True,
        price_usd=round(price_usd, 2),
        change_24h_pct=round(change_24h, 4),
        rsi_14=round(_rsi(closes), 2),
        macd_crossover=_macd_crossover(closes),
        consecutive_bars=streak_count,
        streak_direction=streak_dir,
        volume_ratio=round(_volume_ratio(volumes), 4),
        bb_width_ratio=round(_bb_width_ratio(closes), 4),
        atr_ratio=round(_atr_ratio(highs, lows, closes), 4),
        fetched_at=time.monotonic(),
    )
    LOGGER.info(
        "btc_signals_fetched price=%.2f change_24h=%+.2f%% rsi=%.1f macd=%s",
        signals.price_usd,
        signals.change_24h_pct,
        signals.rsi_14,
        signals.macd_crossover,
    )
    return signals


# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_cached_signals: BtcSignals = BtcSignals(data_available=False)
_cache_ts: float = 0.0


def get_cached_signals() -> BtcSignals:
    """Return the most recently fetched BtcSignals (may be stale)."""
    return _cached_signals


def refresh_btc_signals_if_stale(interval_sec: float = 300.0) -> BtcSignals:
    """Fetch fresh signals if the cache is older than interval_sec.

    Thread-safety note: this module is used from a single-threaded scan loop;
    no locking is needed.
    """
    global _cached_signals, _cache_ts
    now = time.monotonic()
    if now - _cache_ts >= interval_sec:
        _cached_signals = fetch_btc_signals()
        _cache_ts = now
    return _cached_signals
