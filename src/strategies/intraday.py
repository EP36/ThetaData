"""Intraday strategy profiles for active paper-trading workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import ClassVar

import numpy as np
import pandas as pd

from src.strategies.base import Strategy

EPSILON = 1e-12


@dataclass(slots=True)
class BreakoutMomentumIntradayStrategy(Strategy):
    """Intraday breakout strategy using compact price and volume confirmation."""

    name: ClassVar[str] = "breakout_momentum_intraday"
    required_columns: ClassVar[tuple[str, ...]] = ("high", "close", "volume")

    lookback_period: int = 12
    breakout_threshold: float = 1.002
    volume_multiplier: float = 1.2
    stop_loss_pct: float = 0.008
    take_profit_pct: float = 0.015
    trailing_stop_pct: float = 0.006
    max_hold_bars: int = 12

    def __post_init__(self) -> None:
        if self.lookback_period <= 1:
            raise ValueError("lookback_period must be > 1")
        if self.breakout_threshold <= 1.0:
            raise ValueError("breakout_threshold must be > 1.0")
        if self.volume_multiplier <= 0:
            raise ValueError("volume_multiplier must be positive")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        high = data["high"].astype(float)
        close = data["close"].astype(float)
        volume = data["volume"].astype(float)
        breakout_level = high.rolling(self.lookback_period, min_periods=2).max().shift(1)
        avg_volume = volume.rolling(self.lookback_period, min_periods=2).mean().shift(1)
        signal = (
            (close >= breakout_level * self.breakout_threshold)
            & (volume >= avg_volume * self.volume_multiplier)
        ).fillna(False).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)


@dataclass(slots=True)
class OpeningRangeBreakoutStrategy(Strategy):
    """Opening-range breakout: long when price clears the initial range high."""

    name: ClassVar[str] = "opening_range_breakout"
    required_columns: ClassVar[tuple[str, ...]] = ("high", "close", "volume")

    range_start: str = "09:30"
    range_end: str = "09:45"
    breakout_threshold: float = 1.001
    stop_loss_pct: float = 0.006
    trailing_stop_pct: float = 0.006
    max_hold_bars: int = 20

    def __post_init__(self) -> None:
        if _parse_time(self.range_start) >= _parse_time(self.range_end):
            raise ValueError("range_start must be earlier than range_end")
        if self.breakout_threshold <= 1.0:
            raise ValueError("breakout_threshold must be > 1.0")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        high = data["high"].astype(float)
        close = data["close"].astype(float)
        market_index = _market_index(data.index)
        range_start = _parse_time(self.range_start)
        range_end = _parse_time(self.range_end)
        signal = pd.Series(0.0, index=data.index)

        for market_date in sorted(set(market_index.date)):
            day_mask = market_index.date == market_date
            range_mask = day_mask & (market_index.time >= range_start) & (market_index.time <= range_end)
            trade_mask = day_mask & (market_index.time > range_end)
            if not bool(range_mask.any()):
                continue
            opening_high = float(high.loc[range_mask].max())
            signal.loc[trade_mask] = (
                close.loc[trade_mask] >= opening_high * self.breakout_threshold
            ).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)


@dataclass(slots=True)
class VWAPReclaimIntradayStrategy(Strategy):
    """Enter when price reclaims VWAP after a pullback."""

    name: ClassVar[str] = "vwap_reclaim_intraday"
    required_columns: ClassVar[tuple[str, ...]] = ("high", "low", "close", "volume")

    vwap_window: int = 20
    trend_window: int = 20
    stop_loss_pct: float = 0.006
    take_profit_pct: float = 0.012
    max_hold_bars: int = 12

    def __post_init__(self) -> None:
        if self.vwap_window <= 1:
            raise ValueError("vwap_window must be > 1")
        if self.trend_window <= 1:
            raise ValueError("trend_window must be > 1")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        close = data["close"].astype(float)
        vwap = _rolling_vwap(data, self.vwap_window)
        trend_ma = close.rolling(self.trend_window, min_periods=2).mean()
        reclaim = (close.shift(1) < vwap.shift(1)) & (close >= vwap)
        bullish_bias = close >= trend_ma.fillna(close)
        signal = (reclaim & bullish_bias).fillna(False).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)


@dataclass(slots=True)
class PullbackTrendContinuationStrategy(Strategy):
    """Enter trend continuation after a shallow pullback and recovery."""

    name: ClassVar[str] = "pullback_trend_continuation"
    required_columns: ClassVar[tuple[str, ...]] = ("high", "low", "close", "volume")

    trend_window: int = 30
    pullback_window: int = 6
    stop_loss_pct: float = 0.007
    trailing_stop_pct: float = 0.006
    max_hold_bars: int = 16

    def __post_init__(self) -> None:
        if self.trend_window <= 2:
            raise ValueError("trend_window must be > 2")
        if self.pullback_window <= 1:
            raise ValueError("pullback_window must be > 1")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        close = data["close"].astype(float)
        low = data["low"].astype(float)
        trend_ma = close.rolling(self.trend_window, min_periods=3).mean()
        pullback_ma = close.rolling(self.pullback_window, min_periods=2).mean()
        uptrend = (close > trend_ma) & (trend_ma.diff() > 0)
        touched_pullback = low.rolling(self.pullback_window, min_periods=1).min() <= pullback_ma
        reclaimed = close > pullback_ma
        signal = (uptrend & touched_pullback & reclaimed).fillna(False).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)


@dataclass(slots=True)
class MeanReversionScalpStrategy(Strategy):
    """Short-horizon long scalp from VWAP deviation and oversold RSI."""

    name: ClassVar[str] = "mean_reversion_scalp"
    required_columns: ClassVar[tuple[str, ...]] = ("high", "low", "close", "volume")

    vwap_window: int = 20
    vwap_deviation: float = 0.006
    rsi_lookback: int = 7
    rsi_oversold: float = 35.0
    stop_loss_pct: float = 0.005
    take_profit_pct: float = 0.008
    max_hold_bars: int = 8

    def __post_init__(self) -> None:
        if self.vwap_window <= 1:
            raise ValueError("vwap_window must be > 1")
        if self.vwap_deviation <= 0 or self.vwap_deviation >= 1:
            raise ValueError("vwap_deviation must be in (0, 1)")
        if self.rsi_lookback <= 1:
            raise ValueError("rsi_lookback must be > 1")
        if not 0 < self.rsi_oversold < 100:
            raise ValueError("rsi_oversold must be in (0, 100)")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        self.validate_required_columns(data)
        close = data["close"].astype(float)
        vwap = _rolling_vwap(data, self.vwap_window)
        rsi = _rsi(close, self.rsi_lookback)
        signal = (
            (close <= vwap * (1.0 - self.vwap_deviation))
            & (rsi <= self.rsi_oversold)
        ).fillna(False).astype(float)
        return pd.DataFrame({"signal": signal}, index=data.index)


def _rolling_vwap(data: pd.DataFrame, window: int) -> pd.Series:
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    volume = data["volume"].astype(float)
    typical = (high + low + close) / 3.0
    pv_sum = (typical * volume).rolling(window, min_periods=1).sum()
    volume_sum = volume.rolling(window, min_periods=1).sum()
    return (pv_sum / volume_sum.replace(0.0, np.nan)).fillna(close)


def _rsi(close: pd.Series, lookback: int) -> pd.Series:
    delta = close.diff().fillna(0.0)
    gains = pd.Series(np.where(delta > 0, delta, 0.0), index=close.index)
    losses = pd.Series(np.where(delta < 0, -delta, 0.0), index=close.index)
    avg_gain = gains.rolling(lookback, min_periods=1).mean()
    avg_loss = losses.rolling(lookback, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def _market_index(index: pd.Index) -> pd.DatetimeIndex:
    ts_index = pd.DatetimeIndex(index)
    if ts_index.tz is None:
        return ts_index.tz_localize("America/New_York")
    return ts_index.tz_convert("America/New_York")


def _parse_time(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid time format '{value}', expected HH:MM") from exc
