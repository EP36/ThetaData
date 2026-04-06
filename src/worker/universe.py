"""Universe scanning, filtering, and ranking for worker symbol selection."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

import numpy as np
import pandas as pd

from src.data.loaders import HistoricalDataLoader

UniverseMode = Literal[
    "static",
    "top_gainers",
    "top_losers",
    "high_relative_volume",
    "index_constituents",
]

EPSILON = 1e-12
SCAN_REASON_GROUPS: dict[str, str] = {
    "data_unavailable": "missing_data",
    "invalid_snapshot": "missing_data",
    "empty_data": "missing_data",
    "missing_required_columns": "missing_data",
    "invalid_price_or_volume": "missing_data",
    "stale_market_data": "missing_data",
    "below_min_avg_volume": "insufficient_volume_confirmation",
    "below_min_relative_volume": "insufficient_volume_confirmation",
    "spread_above_max": "risk_blocked",
    "below_min_price": "risk_blocked",
    "ranked_outside_max_candidates": "ranking_cutoff",
}


@dataclass(frozen=True, slots=True)
class SymbolSnapshot:
    """Computed market snapshot used by universe filters and ranking."""

    symbol: str
    latest_timestamp: pd.Timestamp
    latest_price: float
    average_volume: float
    latest_volume: float
    relative_volume: float
    percent_move: float
    atr_pct: float
    trend_strength: float
    spread_pct: float | None

    def as_dict(self) -> dict[str, float | str | None]:
        """Serialize snapshot for logs/API payloads."""
        return {
            "symbol": self.symbol,
            "latest_timestamp": self.latest_timestamp.isoformat(),
            "latest_price": float(self.latest_price),
            "average_volume": float(self.average_volume),
            "latest_volume": float(self.latest_volume),
            "relative_volume": float(self.relative_volume),
            "percent_move": float(self.percent_move),
            "atr_pct": float(self.atr_pct),
            "trend_strength": float(self.trend_strength),
            "spread_pct": (float(self.spread_pct) if self.spread_pct is not None else None),
        }


@dataclass(frozen=True, slots=True)
class UniverseScanResult:
    """Universe scanner output with shortlist and filter diagnostics."""

    mode: UniverseMode
    scanned_symbols: tuple[str, ...]
    ranked_symbols: tuple[str, ...]
    shortlisted_symbols: tuple[str, ...]
    filtered_out_reasons: dict[str, tuple[str, ...]]
    snapshots_by_symbol: dict[str, SymbolSnapshot]

    def as_dict(self) -> dict[str, object]:
        """Serialize scan result for structured logs."""
        return {
            "mode": self.mode,
            "scanned_symbols": list(self.scanned_symbols),
            "ranked_symbols": list(self.ranked_symbols),
            "shortlisted_symbols": list(self.shortlisted_symbols),
            "filtered_out_reasons": {
                symbol: list(reasons)
                for symbol, reasons in self.filtered_out_reasons.items()
            },
            "filtered_out_reason_groups": self.filtered_out_reason_groups(),
            "filtered_out_reason_counts": self.filtered_out_reason_counts(),
            "filtered_out_reason_group_counts": self.filtered_out_reason_group_counts(),
            "snapshots_by_symbol": {
                symbol: snapshot.as_dict()
                for symbol, snapshot in self.snapshots_by_symbol.items()
            },
        }

    def filtered_out_reason_groups(self) -> dict[str, list[str]]:
        """Return normalized reason groups keyed by rejected symbol."""
        grouped: dict[str, list[str]] = {}
        for symbol, reasons in self.filtered_out_reasons.items():
            groups = sorted(
                {
                    SCAN_REASON_GROUPS.get(reason, reason)
                    for reason in reasons
                    if reason.strip()
                }
            )
            grouped[symbol] = groups
        return grouped

    def filtered_out_reason_counts(self) -> dict[str, int]:
        """Return per-reason rejection counts for one scan cycle."""
        counts: dict[str, int] = {}
        for reasons in self.filtered_out_reasons.values():
            for reason in reasons:
                if not reason.strip():
                    continue
                counts[reason] = counts.get(reason, 0) + 1
        return dict(sorted(counts.items()))

    def filtered_out_reason_group_counts(self) -> dict[str, int]:
        """Return per-group rejection counts for one scan cycle."""
        counts: dict[str, int] = {}
        for groups in self.filtered_out_reason_groups().values():
            for group in groups:
                if not group.strip():
                    continue
                counts[group] = counts.get(group, 0) + 1
        return dict(sorted(counts.items()))


@dataclass(slots=True)
class UniverseScannerConfig:
    """Configuration for deterministic universe scanning and shortlist curation."""

    timeframe: str
    max_candidates: int = 10
    min_price: float = 1.0
    min_average_volume: float = 100_000.0
    min_relative_volume: float = 0.0
    max_spread_pct: float = 1.0

    def __post_init__(self) -> None:
        """Validate scanner parameters."""
        if not self.timeframe.strip():
            raise ValueError("timeframe cannot be empty")
        if self.max_candidates <= 0:
            raise ValueError("max_candidates must be positive")
        if self.min_price < 0:
            raise ValueError("min_price cannot be negative")
        if self.min_average_volume < 0:
            raise ValueError("min_average_volume cannot be negative")
        if self.min_relative_volume < 0:
            raise ValueError("min_relative_volume cannot be negative")
        if self.max_spread_pct < 0:
            raise ValueError("max_spread_pct cannot be negative")


@dataclass(slots=True)
class UniverseScanner:
    """Scan configured symbols and return a deterministic shortlist."""

    loader: HistoricalDataLoader
    config: UniverseScannerConfig

    def scan(
        self,
        mode: UniverseMode,
        configured_symbols: tuple[str, ...],
        force_refresh: bool = False,
        now: pd.Timestamp | None = None,
    ) -> UniverseScanResult:
        """Load, filter, and rank symbols into a worker shortlist."""
        scanned_symbols = _normalize_symbols(self._resolve_symbols(mode, configured_symbols))
        filtered_out_reasons: dict[str, tuple[str, ...]] = {}
        snapshots_by_symbol: dict[str, SymbolSnapshot] = {}
        eligible_symbols: list[str] = []

        for symbol in scanned_symbols:
            try:
                data = self.loader.load(
                    symbol=symbol,
                    timeframe=self.config.timeframe,
                    force_refresh=force_refresh,
                )
            except Exception:
                filtered_out_reasons[symbol] = ("data_unavailable",)
                continue

            try:
                snapshot = _build_snapshot(symbol=symbol, data=data)
            except Exception:
                filtered_out_reasons[symbol] = ("invalid_snapshot",)
                continue
            snapshots_by_symbol[symbol] = snapshot

            reasons = self._filter_reasons(snapshot=snapshot, now=now)
            if reasons:
                filtered_out_reasons[symbol] = tuple(sorted(set(reasons)))
                continue
            eligible_symbols.append(symbol)

        ranked_symbols = tuple(self._rank_symbols(mode=mode, symbols=eligible_symbols, snapshots=snapshots_by_symbol))
        shortlisted_symbols = ranked_symbols[: self.config.max_candidates]
        for symbol in ranked_symbols[self.config.max_candidates :]:
            existing = list(filtered_out_reasons.get(symbol, ()))
            existing.append("ranked_outside_max_candidates")
            filtered_out_reasons[symbol] = tuple(sorted(set(existing)))

        return UniverseScanResult(
            mode=mode,
            scanned_symbols=scanned_symbols,
            ranked_symbols=ranked_symbols,
            shortlisted_symbols=shortlisted_symbols,
            filtered_out_reasons=filtered_out_reasons,
            snapshots_by_symbol=snapshots_by_symbol,
        )

    @staticmethod
    def _resolve_symbols(
        mode: UniverseMode,
        configured_symbols: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Resolve initial symbols for the selected universe mode."""
        # Assumption: for index_constituents mode, WORKER_SYMBOLS carries the
        # explicit constituents list to keep the system deterministic.
        if mode in {
            "static",
            "top_gainers",
            "top_losers",
            "high_relative_volume",
            "index_constituents",
        }:
            return configured_symbols
        return configured_symbols

    def _filter_reasons(
        self,
        snapshot: SymbolSnapshot,
        now: pd.Timestamp | None,
    ) -> list[str]:
        """Apply deterministic safety filters to one symbol snapshot."""
        reasons: list[str] = []

        if snapshot.latest_price < self.config.min_price:
            reasons.append("below_min_price")
        if snapshot.average_volume < self.config.min_average_volume:
            reasons.append("below_min_avg_volume")
        if snapshot.relative_volume < self.config.min_relative_volume:
            reasons.append("below_min_relative_volume")
        if (
            snapshot.spread_pct is not None
            and snapshot.spread_pct > self.config.max_spread_pct
        ):
            reasons.append("spread_above_max")
        if _is_stale_timestamp(
            latest_timestamp=snapshot.latest_timestamp,
            timeframe=self.config.timeframe,
            now=now,
        ):
            reasons.append("stale_market_data")
        return reasons

    @staticmethod
    def _rank_symbols(
        mode: UniverseMode,
        symbols: list[str],
        snapshots: dict[str, SymbolSnapshot],
    ) -> list[str]:
        """Rank filtered symbols according to selected universe mode."""
        def key_top_gainers(symbol: str) -> tuple[float, float, float, str]:
            snap = snapshots[symbol]
            return (-snap.percent_move, -snap.relative_volume, -snap.atr_pct, symbol)

        def key_top_losers(symbol: str) -> tuple[float, float, float, str]:
            snap = snapshots[symbol]
            return (snap.percent_move, -snap.relative_volume, -snap.atr_pct, symbol)

        def key_relative_volume(symbol: str) -> tuple[float, float, float, str]:
            snap = snapshots[symbol]
            return (-snap.relative_volume, -abs(snap.percent_move), -snap.atr_pct, symbol)

        def key_static(symbol: str) -> tuple[float, float, float, float, str]:
            snap = snapshots[symbol]
            return (
                -snap.trend_strength,
                -abs(snap.percent_move),
                -snap.relative_volume,
                -snap.atr_pct,
                symbol,
            )

        if mode == "top_gainers":
            return sorted(symbols, key=key_top_gainers)
        if mode == "top_losers":
            return sorted(symbols, key=key_top_losers)
        if mode == "high_relative_volume":
            return sorted(symbols, key=key_relative_volume)
        return sorted(symbols, key=key_static)


def _build_snapshot(symbol: str, data: pd.DataFrame) -> SymbolSnapshot:
    """Compute one symbol snapshot from OHLCV (+ optional quote) data."""
    if data.empty:
        raise ValueError("empty_data")
    required = {"high", "low", "close", "volume"}
    if not required.issubset(set(data.columns)):
        raise ValueError("missing_required_columns")

    close = pd.to_numeric(data["close"], errors="coerce")
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    volume = pd.to_numeric(data["volume"], errors="coerce")
    if close.isna().all() or volume.isna().all():
        raise ValueError("invalid_price_or_volume")

    latest_price = float(close.iloc[-1])
    latest_volume = float(volume.iloc[-1])
    avg_volume = float(volume.tail(min(20, len(volume))).mean())
    relative_volume = float(latest_volume / max(avg_volume, EPSILON))

    if len(close) >= 2 and abs(float(close.iloc[-2])) > EPSILON:
        percent_move = float((close.iloc[-1] / close.iloc[-2]) - 1.0)
    else:
        percent_move = 0.0

    atr_pct = _compute_atr_pct(high=high, low=low, close=close)
    trend_strength = _compute_trend_strength(close=close)
    spread_pct = _compute_spread_pct(data=data)

    latest_timestamp = pd.Timestamp(data.index[-1])
    return SymbolSnapshot(
        symbol=symbol,
        latest_timestamp=latest_timestamp,
        latest_price=float(latest_price),
        average_volume=float(avg_volume),
        latest_volume=float(latest_volume),
        relative_volume=float(relative_volume),
        percent_move=float(percent_move),
        atr_pct=float(atr_pct),
        trend_strength=float(trend_strength),
        spread_pct=(float(spread_pct) if spread_pct is not None else None),
    )


def _compute_atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int = 14) -> float:
    """Compute ATR as percentage of latest close."""
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(window=lookback, min_periods=max(2, min(lookback, len(true_range)))).mean()
    atr_last = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0
    close_last = float(close.iloc[-1])
    if abs(close_last) <= EPSILON:
        return 0.0
    return float(atr_last / abs(close_last))


def _compute_trend_strength(close: pd.Series, short: int = 10, long: int = 30) -> float:
    """Compute deterministic trend-strength proxy from MA separation."""
    short_window = min(short, len(close))
    long_window = min(long, len(close))
    short_ma = close.rolling(window=max(2, short_window), min_periods=max(2, short_window)).mean()
    long_ma = close.rolling(window=max(2, long_window), min_periods=max(2, long_window)).mean()

    short_last = float(short_ma.iloc[-1]) if not np.isnan(short_ma.iloc[-1]) else 0.0
    long_last = float(long_ma.iloc[-1]) if not np.isnan(long_ma.iloc[-1]) else 0.0
    close_last = float(close.iloc[-1])
    if abs(close_last) <= EPSILON:
        return 0.0
    return float(abs(short_last - long_last) / abs(close_last))


def _compute_spread_pct(data: pd.DataFrame) -> float | None:
    """Compute spread percentage if quote columns are available."""
    columns = set(data.columns)
    if not {"bid", "ask"}.issubset(columns):
        return None

    bid = pd.to_numeric(data["bid"], errors="coerce")
    ask = pd.to_numeric(data["ask"], errors="coerce")
    bid_last = float(bid.iloc[-1]) if not np.isnan(bid.iloc[-1]) else 0.0
    ask_last = float(ask.iloc[-1]) if not np.isnan(ask.iloc[-1]) else 0.0
    if bid_last <= 0 or ask_last <= 0 or ask_last < bid_last:
        return None
    mid = (ask_last + bid_last) / 2.0
    if mid <= EPSILON:
        return None
    return float((ask_last - bid_last) / mid)


def _normalize_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize symbols to uppercase unique values preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        symbol = raw.strip().upper()
        if not symbol or symbol in seen:
            continue
        normalized.append(symbol)
        seen.add(symbol)
    return tuple(normalized)


def _is_stale_timestamp(
    latest_timestamp: pd.Timestamp,
    timeframe: str,
    now: pd.Timestamp | None = None,
) -> bool:
    """Determine whether a latest bar is stale for intraday timeframes."""
    interval_minutes = _timeframe_to_minutes(timeframe)
    if interval_minutes >= 1_440:
        # Daily/longer data is intentionally not stale-filtered here.
        return False

    latest = pd.Timestamp(latest_timestamp)
    now_ts = pd.Timestamp.utcnow() if now is None else pd.Timestamp(now)
    if latest.tzinfo is None:
        latest = latest.tz_localize("UTC")
    else:
        latest = latest.tz_convert("UTC")
    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")

    age_minutes = (now_ts - latest).total_seconds() / 60.0
    if age_minutes < 0:
        return False

    max_age_minutes = max(float(interval_minutes * 3), 120.0)
    return age_minutes > max_age_minutes


def _timeframe_to_minutes(timeframe: str) -> int:
    """Parse timeframe strings like 1m/1h/1d into minute counts."""
    match = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", timeframe.lower())
    if match is None:
        return 1_440
    size = max(int(match.group(1)), 1)
    unit = match.group(2)
    if unit == "m":
        return size
    if unit == "h":
        return size * 60
    return size * 1_440
