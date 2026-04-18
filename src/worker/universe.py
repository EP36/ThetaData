"""Universe scanning, filtering, and ranking for worker symbol selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
import re
from typing import Literal

import numpy as np
import pandas as pd

from src.data.loaders import HistoricalDataLoader
from src.trading.session import (
    SessionConfig,
    SessionContext,
    SessionState,
    classify_trading_session,
)

UniverseMode = Literal[
    "static",
    "top_gainers",
    "top_losers",
    "high_relative_volume",
    "index_constituents",
]

EPSILON = 1e-12
AVERAGE_VOLUME_LOOKBACK_SESSIONS = 20
RELATIVE_VOLUME_LOOKBACK_BARS = 20
SCAN_REASON_GROUPS: dict[str, str] = {
    "data_unavailable": "missing_data",
    "invalid_snapshot": "missing_data",
    "empty_data": "missing_data",
    "missing_required_columns": "missing_data",
    "invalid_price_or_volume": "missing_data",
    "outside_trading_session": "outside_trading_session",
    "closed_session": "outside_trading_session",
    "weekend_closed": "outside_trading_session",
    "extended_hours_disabled": "outside_trading_session",
    "extended_hours_unsupported": "outside_trading_session",
    "missing_recent_bar": "missing_recent_bar",
    "stale_market_data": "stale_market_data",
    "below_min_avg_volume": "insufficient_volume_confirmation",
    "below_min_relative_volume": "insufficient_volume_confirmation",
    "spread_above_max": "risk_blocked",
    "below_min_price": "risk_blocked",
    "ranked_outside_max_candidates": "ranking_cutoff",
}
MarketSessionState = SessionState | Literal["unknown"]


@dataclass(frozen=True, slots=True)
class SymbolSnapshot:
    """Computed market snapshot used by universe filters and ranking."""

    symbol: str
    latest_timestamp: pd.Timestamp
    latest_price: float
    average_volume: float
    average_volume_unit: str
    average_volume_lookback_window: str
    latest_volume: float
    relative_volume: float
    relative_volume_lookback_window: str
    vwap: float
    price_vs_vwap_pct: float
    range_expansion: float
    candidate_score: float
    score_components: dict[str, float]
    percent_move: float
    atr_pct: float
    trend_strength: float
    spread_pct: float | None

    def as_dict(self) -> dict[str, object]:
        """Serialize snapshot for logs/API payloads."""
        return {
            "symbol": self.symbol,
            "latest_timestamp": self.latest_timestamp.isoformat(),
            "latest_price": float(self.latest_price),
            "average_volume": float(self.average_volume),
            "average_volume_unit": self.average_volume_unit,
            "average_volume_lookback_window": self.average_volume_lookback_window,
            "latest_volume": float(self.latest_volume),
            "relative_volume": float(self.relative_volume),
            "relative_volume_lookback_window": self.relative_volume_lookback_window,
            "vwap": float(self.vwap),
            "price_vs_vwap_pct": float(self.price_vs_vwap_pct),
            "range_expansion": float(self.range_expansion),
            "candidate_score": float(self.candidate_score),
            "score_components": dict(self.score_components),
            "percent_move": float(self.percent_move),
            "atr_pct": float(self.atr_pct),
            "trend_strength": float(self.trend_strength),
            "spread_pct": (float(self.spread_pct) if self.spread_pct is not None else None),
        }


@dataclass(frozen=True, slots=True)
class SymbolScanContext:
    """Compact observability context for one scanned symbol."""

    symbol: str
    timeframe: str
    latest_bar_timestamp: str | None
    now_timestamp: str | None
    latest_bar_age_minutes: float | None
    min_avg_volume_threshold: float
    actual_avg_volume: float | None
    avg_volume_unit: str | None
    lookback_window: str | None
    min_relative_volume_threshold: float
    actual_relative_volume: float | None
    relative_volume_lookback_window: str | None
    candidate_score: float | None
    score_components: dict[str, float] | None
    price_vs_vwap_pct: float | None
    spread_pct: float | None
    market_session_state: MarketSessionState
    freshness_rejection_reason: str | None
    missing_recent_bar_threshold_minutes: float | None
    stale_market_data_threshold_minutes: float | None

    def as_dict(self) -> dict[str, object]:
        """Serialize context for structured logs."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "latest_bar_timestamp": self.latest_bar_timestamp,
            "now_timestamp": self.now_timestamp,
            "latest_bar_age_minutes": self.latest_bar_age_minutes,
            "min_avg_volume_threshold": float(self.min_avg_volume_threshold),
            "actual_avg_volume": self.actual_avg_volume,
            "avg_volume_unit": self.avg_volume_unit,
            "lookback_window": self.lookback_window,
            "min_relative_volume_threshold": float(self.min_relative_volume_threshold),
            "actual_relative_volume": self.actual_relative_volume,
            "relative_volume_lookback_window": self.relative_volume_lookback_window,
            "candidate_score": self.candidate_score,
            "score_components": self.score_components,
            "price_vs_vwap_pct": self.price_vs_vwap_pct,
            "spread_pct": self.spread_pct,
            "market_session_state": self.market_session_state,
            "freshness_rejection_reason": self.freshness_rejection_reason,
            "missing_recent_bar_threshold_minutes": self.missing_recent_bar_threshold_minutes,
            "stale_market_data_threshold_minutes": self.stale_market_data_threshold_minutes,
            "stale_threshold_minutes": self.stale_market_data_threshold_minutes,
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
    scan_context_by_symbol: dict[str, SymbolScanContext]

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
            "scan_context_by_symbol": {
                symbol: context.as_dict()
                for symbol, context in self.scan_context_by_symbol.items()
            },
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

    def symbol_rejection_payload(self, symbol: str) -> dict[str, object]:
        """Return compact structured rejection context for one symbol."""
        symbol_key = symbol.strip().upper()
        context = self.scan_context_by_symbol.get(symbol_key)
        payload: dict[str, object] = {
            "symbol": symbol_key,
            "rejection_reasons": list(self.filtered_out_reasons.get(symbol_key, ())),
            "reason_groups": self.filtered_out_reason_groups().get(symbol_key, []),
        }
        if context is not None:
            payload.update(context.as_dict())
        return payload


@dataclass(slots=True)
class UniverseScannerConfig:
    """Configuration for deterministic universe scanning and shortlist curation."""

    timeframe: str
    max_candidates: int = 10
    min_price: float = 1.0
    min_average_volume: float = 100_000.0
    min_relative_volume: float = 0.0
    max_spread_pct: float = 1.0
    trading_start: str = "09:30"
    trading_end: str = "16:00"
    allow_after_hours: bool = False
    extended_hours_enabled: bool = False
    overnight_trading_enabled: bool = False
    broker_extended_hours_supported: bool = False
    enforce_relative_volume_filter: bool = False
    only_open_new_positions_during_market_hours: bool = True
    stale_market_data_grace_minutes: float = 120.0
    stale_market_data_interval_multiplier: float = 3.0

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
        if self.stale_market_data_grace_minutes <= 0:
            raise ValueError("stale_market_data_grace_minutes must be positive")
        if self.stale_market_data_interval_multiplier <= 0:
            raise ValueError("stale_market_data_interval_multiplier must be positive")
        trading_start = _parse_session_time(self.trading_start)
        trading_end = _parse_session_time(self.trading_end)
        if trading_start >= trading_end:
            raise ValueError("trading_start must be earlier than trading_end")


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
        scan_context_by_symbol: dict[str, SymbolScanContext] = {}
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
                scan_context_by_symbol[symbol] = self._build_scan_context(
                    symbol=symbol,
                    snapshot=None,
                    now=now,
                )
                continue

            try:
                snapshot = _build_snapshot(
                    symbol=symbol,
                    data=data,
                    timeframe=self.config.timeframe,
                )
            except Exception:
                filtered_out_reasons[symbol] = ("invalid_snapshot",)
                scan_context_by_symbol[symbol] = self._build_scan_context(
                    symbol=symbol,
                    snapshot=None,
                    now=now,
                )
                continue
            snapshots_by_symbol[symbol] = snapshot
            context = self._build_scan_context(
                symbol=symbol,
                snapshot=snapshot,
                now=now,
            )
            if _should_refresh_stale_intraday_data(
                context=context,
                force_refresh=force_refresh,
            ):
                try:
                    refreshed_data = self.loader.load(
                        symbol=symbol,
                        timeframe=self.config.timeframe,
                        force_refresh=True,
                    )
                    refreshed_snapshot = _build_snapshot(
                        symbol=symbol,
                        data=refreshed_data,
                        timeframe=self.config.timeframe,
                    )
                except Exception:
                    pass
                else:
                    snapshot = refreshed_snapshot
                    snapshots_by_symbol[symbol] = snapshot
                    context = self._build_scan_context(
                        symbol=symbol,
                        snapshot=snapshot,
                        now=now,
                    )
            scan_context_by_symbol[symbol] = context

            reasons = self._filter_reasons(snapshot=snapshot, context=context)
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
            scan_context_by_symbol=scan_context_by_symbol,
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
        context: SymbolScanContext,
    ) -> list[str]:
        """Apply deterministic safety filters to one symbol snapshot."""
        reasons: list[str] = []

        if snapshot.latest_price < self.config.min_price:
            reasons.append("below_min_price")
        if snapshot.average_volume < self.config.min_average_volume:
            reasons.append("below_min_avg_volume")
        if (
            self.config.enforce_relative_volume_filter
            and snapshot.relative_volume < self.config.min_relative_volume
        ):
            reasons.append("below_min_relative_volume")
        if (
            snapshot.spread_pct is not None
            and snapshot.spread_pct > self.config.max_spread_pct
        ):
            reasons.append("spread_above_max")
        if context.freshness_rejection_reason is not None:
            reasons.append(context.freshness_rejection_reason)
        return reasons

    def _build_scan_context(
        self,
        symbol: str,
        snapshot: SymbolSnapshot | None,
        now: pd.Timestamp | None,
    ) -> SymbolScanContext:
        """Build compact per-symbol context for rejection logging."""
        assessment = _assess_bar_freshness(
            latest_timestamp=(snapshot.latest_timestamp if snapshot is not None else None),
            timeframe=self.config.timeframe,
            now=now,
            config=self.config,
        )
        return SymbolScanContext(
            symbol=symbol,
            timeframe=self.config.timeframe,
            latest_bar_timestamp=(
                snapshot.latest_timestamp.isoformat()
                if snapshot is not None
                else None
            ),
            now_timestamp=assessment["now_timestamp"],
            latest_bar_age_minutes=assessment["latest_bar_age_minutes"],
            min_avg_volume_threshold=float(self.config.min_average_volume),
            actual_avg_volume=(
                float(snapshot.average_volume)
                if snapshot is not None
                else None
            ),
            avg_volume_unit=(
                snapshot.average_volume_unit
                if snapshot is not None
                else None
            ),
            lookback_window=(
                snapshot.average_volume_lookback_window
                if snapshot is not None
                else None
            ),
            min_relative_volume_threshold=float(self.config.min_relative_volume),
            actual_relative_volume=(
                float(snapshot.relative_volume)
                if snapshot is not None
                else None
            ),
            relative_volume_lookback_window=(
                snapshot.relative_volume_lookback_window
                if snapshot is not None
                else None
            ),
            candidate_score=(
                float(snapshot.candidate_score)
                if snapshot is not None
                else None
            ),
            score_components=(
                dict(snapshot.score_components)
                if snapshot is not None
                else None
            ),
            price_vs_vwap_pct=(
                float(snapshot.price_vs_vwap_pct)
                if snapshot is not None
                else None
            ),
            spread_pct=(
                float(snapshot.spread_pct)
                if snapshot is not None and snapshot.spread_pct is not None
                else None
            ),
            market_session_state=assessment["market_session_state"],  # type: ignore[arg-type]
            freshness_rejection_reason=assessment["freshness_rejection_reason"],
            missing_recent_bar_threshold_minutes=assessment[
                "missing_recent_bar_threshold_minutes"
            ],
            stale_market_data_threshold_minutes=assessment[
                "stale_market_data_threshold_minutes"
            ],
        )

    @staticmethod
    def _rank_symbols(
        mode: UniverseMode,
        symbols: list[str],
        snapshots: dict[str, SymbolSnapshot],
    ) -> list[str]:
        """Rank filtered symbols according to selected universe mode."""
        def key_top_gainers(symbol: str) -> tuple[float, float, float, str]:
            snap = snapshots[symbol]
            return (-snap.percent_move, -snap.candidate_score, -snap.relative_volume, symbol)

        def key_top_losers(symbol: str) -> tuple[float, float, float, str]:
            snap = snapshots[symbol]
            return (snap.percent_move, -snap.candidate_score, -snap.relative_volume, symbol)

        def key_relative_volume(symbol: str) -> tuple[float, float, float, str]:
            snap = snapshots[symbol]
            return (-snap.relative_volume, -snap.candidate_score, -abs(snap.percent_move), symbol)

        def key_static(symbol: str) -> tuple[float, float, float, float, str]:
            snap = snapshots[symbol]
            return (
                -snap.candidate_score,
                -snap.trend_strength,
                -snap.relative_volume,
                -abs(snap.percent_move),
                symbol,
            )

        if mode == "top_gainers":
            return sorted(symbols, key=key_top_gainers)
        if mode == "top_losers":
            return sorted(symbols, key=key_top_losers)
        if mode == "high_relative_volume":
            return sorted(symbols, key=key_relative_volume)
        return sorted(symbols, key=key_static)


def _build_snapshot(
    symbol: str,
    data: pd.DataFrame,
    timeframe: str,
) -> SymbolSnapshot:
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
    avg_volume, avg_volume_unit, avg_volume_lookback_window = (
        _compute_average_volume_for_filter(
            volume=volume,
            timeframe=timeframe,
        )
    )
    relative_volume, relative_volume_lookback_window = _compute_relative_volume(
        volume=volume,
        latest_volume=latest_volume,
    )

    if len(close) >= 2 and abs(float(close.iloc[-2])) > EPSILON:
        percent_move = float((close.iloc[-1] / close.iloc[-2]) - 1.0)
    else:
        percent_move = 0.0

    vwap = _compute_recent_vwap(data=data)
    price_vs_vwap_pct = float((latest_price - vwap) / max(abs(vwap), EPSILON))
    atr_pct = _compute_atr_pct(high=high, low=low, close=close)
    range_expansion = _compute_range_expansion(high=high, low=low, close=close)
    trend_strength = _compute_trend_strength(close=close)
    spread_pct = _compute_spread_pct(data=data)
    candidate_score, score_components = _compute_candidate_score(
        trend_strength=trend_strength,
        percent_move=percent_move,
        price_vs_vwap_pct=price_vs_vwap_pct,
        atr_pct=atr_pct,
        range_expansion=range_expansion,
        relative_volume=relative_volume,
        average_volume=avg_volume,
    )

    latest_timestamp = pd.Timestamp(data.index[-1])
    return SymbolSnapshot(
        symbol=symbol,
        latest_timestamp=latest_timestamp,
        latest_price=float(latest_price),
        average_volume=float(avg_volume),
        average_volume_unit=avg_volume_unit,
        average_volume_lookback_window=avg_volume_lookback_window,
        latest_volume=float(latest_volume),
        relative_volume=float(relative_volume),
        relative_volume_lookback_window=relative_volume_lookback_window,
        vwap=float(vwap),
        price_vs_vwap_pct=float(price_vs_vwap_pct),
        range_expansion=float(range_expansion),
        candidate_score=float(candidate_score),
        score_components=score_components,
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


def _compute_recent_vwap(data: pd.DataFrame, lookback: int = 20) -> float:
    """Compute recent rolling VWAP for ranking diagnostics."""
    high = pd.to_numeric(data["high"], errors="coerce")
    low = pd.to_numeric(data["low"], errors="coerce")
    close = pd.to_numeric(data["close"], errors="coerce")
    volume = pd.to_numeric(data["volume"], errors="coerce")
    typical = (high + low + close) / 3.0
    selected_typical = typical.tail(min(lookback, len(typical)))
    selected_volume = volume.tail(min(lookback, len(volume)))
    volume_sum = float(selected_volume.sum())
    if volume_sum <= EPSILON:
        return float(close.iloc[-1])
    return float((selected_typical * selected_volume).sum() / volume_sum)


def _compute_range_expansion(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    lookback: int = 20,
) -> float:
    """Return latest true range divided by recent average true range."""
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    selected = true_range.tail(min(lookback, len(true_range)))
    avg_range = float(selected.mean()) if not selected.empty else 0.0
    latest_range = float(true_range.iloc[-1]) if len(true_range) else 0.0
    if avg_range <= EPSILON:
        return 0.0
    return float(latest_range / avg_range)


def _compute_candidate_score(
    *,
    trend_strength: float,
    percent_move: float,
    price_vs_vwap_pct: float,
    atr_pct: float,
    range_expansion: float,
    relative_volume: float,
    average_volume: float,
) -> tuple[float, dict[str, float]]:
    """Score one candidate using soft signals rather than hard global gates."""
    components = {
        "trend_alignment": min(max(trend_strength / 0.02, 0.0), 1.0),
        "momentum": min(max(percent_move / 0.02, 0.0), 1.0),
        "price_vs_vwap": min(max(price_vs_vwap_pct / 0.01, 0.0), 1.0),
        "volatility": min(max(atr_pct / 0.03, 0.0), 1.0),
        "range_expansion": min(max(range_expansion / 2.0, 0.0), 1.0),
        "relative_volume": min(max(relative_volume / 2.0, 0.0), 1.0),
        "liquidity": min(max(average_volume / 1_000_000.0, 0.0), 1.0),
    }
    score = (
        (components["trend_alignment"] * 0.20)
        + (components["momentum"] * 0.20)
        + (components["price_vs_vwap"] * 0.15)
        + (components["volatility"] * 0.10)
        + (components["range_expansion"] * 0.10)
        + (components["relative_volume"] * 0.15)
        + (components["liquidity"] * 0.10)
    )
    return float(score), components


def _compute_average_volume_for_filter(
    volume: pd.Series,
    timeframe: str,
) -> tuple[float, str, str]:
    """Return average daily volume for threshold filtering."""
    valid_volume = pd.to_numeric(volume, errors="coerce").dropna()
    if valid_volume.empty:
        return 0.0, "shares_per_day", "no_valid_volume"

    interval_minutes = _timeframe_to_minutes(timeframe)
    if interval_minutes < 1_440:
        daily_totals = _daily_volume_totals(
            timestamps=valid_volume.index,
            volume=valid_volume,
            timeframe=timeframe,
        )
        latest_market_date = _bar_market_date(
            pd.Timestamp(valid_volume.index[-1]),
            timeframe=timeframe,
        )
        completed_sessions = daily_totals[daily_totals.index < latest_market_date]
        if not completed_sessions.empty:
            selected = completed_sessions.tail(AVERAGE_VOLUME_LOOKBACK_SESSIONS)
            lookback_window = f"last_{len(selected)}_completed_sessions"
        else:
            selected = daily_totals.tail(AVERAGE_VOLUME_LOOKBACK_SESSIONS)
            lookback_window = f"last_{len(selected)}_sessions_including_current"
        return float(selected.mean()), "shares_per_day", lookback_window

    selected_volume = valid_volume.tail(AVERAGE_VOLUME_LOOKBACK_SESSIONS)
    return (
        float(selected_volume.mean()),
        "shares_per_day",
        f"last_{len(selected_volume)}_bars",
    )


def _compute_relative_volume(
    volume: pd.Series,
    latest_volume: float,
) -> tuple[float, str]:
    """Return latest bar volume divided by recent average bar volume."""
    valid_volume = pd.to_numeric(volume, errors="coerce").dropna()
    if valid_volume.empty:
        return 0.0, "no_valid_volume"

    selected_volume = valid_volume.tail(RELATIVE_VOLUME_LOOKBACK_BARS)
    avg_bar_volume = float(selected_volume.mean())
    return (
        float(latest_volume / max(avg_bar_volume, EPSILON)),
        f"last_{len(selected_volume)}_bars_including_latest",
    )


def _daily_volume_totals(
    timestamps: pd.Index,
    volume: pd.Series,
    timeframe: str,
) -> pd.Series:
    """Return per-market-date volume totals for intraday bars."""
    market_dates = [
        _bar_market_date(pd.Timestamp(timestamp), timeframe=timeframe)
        for timestamp in timestamps
    ]
    daily = pd.DataFrame(
        {
            "market_date": market_dates,
            "volume": volume.to_numpy(dtype=float),
        }
    )
    return daily.groupby("market_date")["volume"].sum().sort_index()


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


def _parse_session_time(value: str) -> time:
    """Parse HH:MM session config values."""
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid time format '{value}', expected HH:MM") from exc


def _assess_bar_freshness(
    latest_timestamp: pd.Timestamp | None,
    timeframe: str,
    now: pd.Timestamp | None,
    config: UniverseScannerConfig,
) -> dict[str, float | str | None]:
    """Classify intraday bar freshness without hiding outside-session scans."""
    interval_minutes = _timeframe_to_minutes(timeframe)
    now_ts = _to_utc_timestamp(pd.Timestamp.utcnow() if now is None else pd.Timestamp(now))
    market_session = _market_session_context(
        now=now,
        timeframe=timeframe,
        config=config,
    )
    market_session_state = market_session.state
    if interval_minutes >= 1_440:
        return {
            "now_timestamp": now_ts.isoformat(),
            "latest_bar_age_minutes": None,
            "market_session_state": market_session_state,
            "freshness_rejection_reason": None,
            "missing_recent_bar_threshold_minutes": None,
            "stale_market_data_threshold_minutes": None,
        }

    stale_threshold = max(
        float(interval_minutes * config.stale_market_data_interval_multiplier),
        float(config.stale_market_data_grace_minutes),
    )
    missing_recent_bar_threshold = stale_threshold
    if (
        config.only_open_new_positions_during_market_hours
        and not market_session.can_open_new_positions
    ):
        return {
            "now_timestamp": now_ts.isoformat(),
            "latest_bar_age_minutes": _bar_age_minutes(
                latest_timestamp=latest_timestamp,
                now=now,
                timeframe=timeframe,
            ),
            "market_session_state": market_session_state,
            "freshness_rejection_reason": market_session.reason or market_session_state,
            "missing_recent_bar_threshold_minutes": missing_recent_bar_threshold,
            "stale_market_data_threshold_minutes": stale_threshold,
        }

    age_minutes = _bar_age_minutes(
        latest_timestamp=latest_timestamp,
        now=now,
        timeframe=timeframe,
    )
    freshness_rejection_reason: str | None = None
    if age_minutes is not None and age_minutes > stale_threshold:
        if (
            market_session.can_open_new_positions
            and _is_same_market_date(
                latest_timestamp=latest_timestamp,
                now=now,
                timeframe=timeframe,
            )
        ):
            freshness_rejection_reason = "missing_recent_bar"
        else:
            freshness_rejection_reason = "stale_market_data"

    return {
        "now_timestamp": now_ts.isoformat(),
        "latest_bar_age_minutes": age_minutes,
        "market_session_state": market_session_state,
        "freshness_rejection_reason": freshness_rejection_reason,
        "missing_recent_bar_threshold_minutes": missing_recent_bar_threshold,
        "stale_market_data_threshold_minutes": stale_threshold,
    }


def _market_session_context(
    now: pd.Timestamp | None,
    timeframe: str,
    config: UniverseScannerConfig,
) -> SessionContext:
    """Return regular-session state for intraday worker scans."""
    if _timeframe_to_minutes(timeframe) >= 1_440:
        now_ts = _to_utc_timestamp(pd.Timestamp.utcnow() if now is None else pd.Timestamp(now))
        market_ts = now_ts.tz_convert("America/New_York")
        return SessionContext(
            state="not_applicable",
            timestamp_utc=now_ts,
            timestamp_market=market_ts,
            can_open_new_positions=True,
            size_multiplier=1.0,
        )

    return classify_trading_session(
        pd.Timestamp.utcnow() if now is None else pd.Timestamp(now),
        SessionConfig(
            regular_start=config.trading_start,
            regular_end=config.trading_end,
            extended_hours_enabled=config.allow_after_hours or config.extended_hours_enabled,
            overnight_trading_enabled=config.overnight_trading_enabled,
            broker_extended_hours_supported=(
                config.broker_extended_hours_supported
                or (config.allow_after_hours and not config.extended_hours_enabled)
            ),
        ),
    )


def _market_session_state(
    now: pd.Timestamp | None,
    timeframe: str,
    config: UniverseScannerConfig,
) -> MarketSessionState:
    """Return regular/extended session state for scanner diagnostics."""
    return _market_session_context(now=now, timeframe=timeframe, config=config).state


def _bar_age_minutes(
    latest_timestamp: pd.Timestamp | None,
    now: pd.Timestamp | None,
    timeframe: str,
) -> float | None:
    """Return latest bar age in minutes, or None when unavailable."""
    if latest_timestamp is None:
        return None
    latest = _to_bar_utc_timestamp(pd.Timestamp(latest_timestamp), timeframe=timeframe)
    now_ts = _to_utc_timestamp(pd.Timestamp.utcnow() if now is None else pd.Timestamp(now))
    age_minutes = (now_ts - latest).total_seconds() / 60.0
    return float(max(age_minutes, 0.0))


def _is_same_market_date(
    latest_timestamp: pd.Timestamp | None,
    now: pd.Timestamp | None,
    timeframe: str,
) -> bool:
    """Return true when latest bar and now land on the same market-local date."""
    if latest_timestamp is None:
        return False
    latest_local = _to_bar_market_time(
        pd.Timestamp(latest_timestamp),
        timeframe=timeframe,
    )
    now_local = _to_market_time(pd.Timestamp.utcnow() if now is None else pd.Timestamp(now))
    return latest_local.date() == now_local.date()


def _to_market_time(value: pd.Timestamp) -> pd.Timestamp:
    """Normalize a timestamp to New York market time."""
    ts = _to_utc_timestamp(value)
    return ts.tz_convert("America/New_York")


def _to_bar_market_time(value: pd.Timestamp, timeframe: str) -> pd.Timestamp:
    """Normalize a bar timestamp to New York market time."""
    ts = _to_bar_utc_timestamp(value, timeframe=timeframe)
    return ts.tz_convert("America/New_York")


def _bar_market_date(value: pd.Timestamp, timeframe: str) -> date:
    """Return the market-local date for a bar timestamp."""
    return _to_bar_market_time(value, timeframe=timeframe).date()


def _to_utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    """Normalize a timestamp to timezone-aware UTC."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _to_bar_utc_timestamp(value: pd.Timestamp, timeframe: str) -> pd.Timestamp:
    """Normalize a market bar timestamp to timezone-aware UTC."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        return ts.tz_convert("UTC")
    if _timeframe_to_minutes(timeframe) < 1_440:
        return ts.tz_localize("America/New_York").tz_convert("UTC")
    return ts.tz_localize("UTC")


def _should_refresh_stale_intraday_data(
    context: SymbolScanContext,
    force_refresh: bool,
) -> bool:
    """Return true when a stale open-session cache read should be retried once."""
    return (
        not force_refresh
        and context.market_session_state
        in {
            "regular_session",
            "premarket_session",
            "afterhours_session",
            "overnight_session",
        }
        and context.freshness_rejection_reason
        in {"missing_recent_bar", "stale_market_data"}
    )


def _is_stale_timestamp(
    latest_timestamp: pd.Timestamp,
    timeframe: str,
    now: pd.Timestamp | None = None,
) -> bool:
    """Determine whether a latest bar is stale for intraday timeframes."""
    config = UniverseScannerConfig(
        timeframe=timeframe,
        allow_after_hours=True,
        only_open_new_positions_during_market_hours=False,
    )
    assessment = _assess_bar_freshness(
        latest_timestamp=latest_timestamp,
        timeframe=timeframe,
        now=now,
        config=config,
    )
    return assessment["freshness_rejection_reason"] in {
        "missing_recent_bar",
        "stale_market_data",
    }


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
