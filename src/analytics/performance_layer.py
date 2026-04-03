"""Deterministic performance analytics built from persisted execution data."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from src.persistence.repository import PortfolioSnapshot

EPSILON = 1e-12


@dataclass(frozen=True, slots=True)
class TradeOutcome:
    """Closed trade outcome reconstructed from fill streams."""

    strategy: str
    symbol: str
    timeframe: str
    regime: str
    run_id: str | None
    entry_timestamp: datetime
    exit_timestamp: datetime
    hold_time_hours: float
    pnl: float
    return_pct: float


@dataclass(frozen=True, slots=True)
class RollingMetricPoint:
    """Rolling metric point aligned to closed-trade index and exit timestamp."""

    trade_index: int
    timestamp: datetime
    win_rate: float
    expectancy: float
    sharpe: float


@dataclass(frozen=True, slots=True)
class WindowMetrics:
    """Summary metrics over a fixed recent-trades window."""

    trades: int
    total_return: float
    win_rate: float
    expectancy: float
    sharpe: float


@dataclass(frozen=True, slots=True)
class StrategyAnalytics:
    """Strategy-level analytics metrics and rolling windows."""

    strategy: str
    total_return: float
    win_rate: float
    average_win: float
    average_loss: float
    profit_factor: float
    expectancy: float
    sharpe: float
    max_drawdown: float
    num_trades: int
    average_hold_time_hours: float
    rolling_20_win_rate: float
    rolling_20_expectancy: float
    rolling_20_sharpe: float
    rolling_20_series: tuple[RollingMetricPoint, ...]
    last_5: WindowMetrics
    last_20: WindowMetrics
    last_60: WindowMetrics


@dataclass(frozen=True, slots=True)
class TimeSeriesPoint:
    """Time-series point for portfolio analytics outputs."""

    timestamp: datetime
    value: float


@dataclass(frozen=True, slots=True)
class StrategyContribution:
    """Per-strategy realized contribution in portfolio analytics."""

    strategy: str
    realized_pnl: float
    return_pct: float
    trades: int


@dataclass(frozen=True, slots=True)
class SymbolExposure:
    """Exposure summary for one open symbol position."""

    symbol: str
    quantity: float
    avg_price: float
    notional: float
    unrealized_pnl: float


@dataclass(frozen=True, slots=True)
class OpenRiskSummary:
    """Open-risk and exposure summary for the current portfolio snapshot."""

    open_positions: int
    gross_exposure: float
    largest_position_notional: float
    cash: float
    day_start_equity: float
    peak_equity: float


@dataclass(frozen=True, slots=True)
class PortfolioAnalytics:
    """Portfolio-level analytics derived from persisted fills and current snapshot."""

    equity_curve: tuple[TimeSeriesPoint, ...]
    daily_pnl: tuple[TimeSeriesPoint, ...]
    rolling_drawdown: tuple[TimeSeriesPoint, ...]
    realized_pnl: float
    unrealized_pnl: float
    strategy_contribution: tuple[StrategyContribution, ...]
    exposure_by_symbol: tuple[SymbolExposure, ...]
    open_risk_summary: OpenRiskSummary


@dataclass(frozen=True, slots=True)
class ContextBucketPerformance:
    """Grouped context-performance metrics for one bucket."""

    key: str
    trades: int
    total_return: float
    win_rate: float
    expectancy: float
    sharpe: float
    total_pnl: float


@dataclass(frozen=True, slots=True)
class ContextAnalytics:
    """Context and regime analytics derived from persisted outcomes."""

    by_symbol: tuple[ContextBucketPerformance, ...]
    by_timeframe: tuple[ContextBucketPerformance, ...]
    by_weekday: tuple[ContextBucketPerformance, ...]
    by_hour: tuple[ContextBucketPerformance, ...]
    by_regime: tuple[ContextBucketPerformance, ...]


@dataclass(frozen=True, slots=True)
class PerformanceAnalyticsSnapshot:
    """Full analytics snapshot used by APIs and selection logic."""

    generated_at: datetime
    outcomes: tuple[TradeOutcome, ...]
    strategies: tuple[StrategyAnalytics, ...]
    portfolio: PortfolioAnalytics
    context: ContextAnalytics

    @property
    def strategies_by_name(self) -> dict[str, StrategyAnalytics]:
        """Return strategy analytics keyed by strategy name."""
        return {item.strategy: item for item in self.strategies}


def build_performance_snapshot(
    fills: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    portfolio_snapshot: PortfolioSnapshot,
    starting_equity: float,
) -> PerformanceAnalyticsSnapshot:
    """Build deterministic analytics snapshot from persisted data."""
    run_context = _build_run_context(runs)
    outcomes = _reconstruct_outcomes(fills, run_context)
    strategy_analytics = _compute_strategy_analytics(outcomes)
    portfolio = _compute_portfolio_analytics(outcomes, portfolio_snapshot, starting_equity)
    context = _compute_context_analytics(outcomes)

    return PerformanceAnalyticsSnapshot(
        generated_at=datetime.now(tz=timezone.utc),
        outcomes=tuple(outcomes),
        strategies=tuple(strategy_analytics),
        portfolio=portfolio,
        context=context,
    )


def empty_snapshot(
    portfolio_snapshot: PortfolioSnapshot,
    starting_equity: float,
) -> PerformanceAnalyticsSnapshot:
    """Return an empty-state-friendly analytics snapshot."""
    empty_portfolio = _compute_portfolio_analytics([], portfolio_snapshot, starting_equity)
    empty_context = ContextAnalytics(
        by_symbol=(),
        by_timeframe=(),
        by_weekday=(),
        by_hour=(),
        by_regime=(),
    )
    return PerformanceAnalyticsSnapshot(
        generated_at=datetime.now(tz=timezone.utc),
        outcomes=(),
        strategies=(),
        portfolio=empty_portfolio,
        context=empty_context,
    )


def _build_run_context(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalize run metadata into a map keyed by run_id."""
    context: dict[str, dict[str, Any]] = {}
    for row in runs:
        run_id = str(row.get("run_id") or "")
        if not run_id:
            continue
        details = row.get("details")
        details_map = dict(details) if isinstance(details, dict) else {}
        selection = details_map.get("selection")
        regime = "unknown"
        if isinstance(selection, dict):
            regime = str(selection.get("regime") or "unknown")
        elif isinstance(details_map.get("regime"), str):
            regime = str(details_map["regime"])

        context[run_id] = {
            "strategy": str(row.get("strategy") or "unknown"),
            "timeframe": str(row.get("timeframe") or "unknown"),
            "regime": regime,
        }
    return context


def _reconstruct_outcomes(
    fills: list[dict[str, Any]],
    run_context: dict[str, dict[str, Any]],
) -> list[TradeOutcome]:
    """Reconstruct closed long-only trade outcomes from fills."""
    if not fills:
        return []

    normalized = []
    for row in fills:
        timestamp = _to_utc_timestamp(row.get("timestamp"))
        if pd.isna(timestamp):
            continue
        side = str(row.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            continue
        quantity = float(row.get("quantity") or 0.0)
        price = float(row.get("price") or 0.0)
        if quantity <= 0.0 or price <= 0.0:
            continue
        run_id = row.get("run_id")
        run_key = str(run_id) if run_id is not None else ""
        context = run_context.get(run_key, {})
        strategy = str(row.get("strategy") or context.get("strategy") or "unknown")
        normalized.append(
            {
                "timestamp": timestamp,
                "side": side,
                "quantity": quantity,
                "price": price,
                "symbol": str(row.get("symbol") or "UNKNOWN"),
                "run_id": run_key if run_key else None,
                "strategy": strategy,
                "timeframe": str(context.get("timeframe") or "unknown"),
                "regime": str(context.get("regime") or "unknown"),
            }
        )

    normalized.sort(
        key=lambda row: (
            row["timestamp"],
            0 if row["side"] == "BUY" else 1,
            row["strategy"],
            row["symbol"],
        )
    )

    outcomes: list[TradeOutcome] = []
    # key=(strategy, symbol)
    positions: dict[tuple[str, str], dict[str, Any]] = {}

    for fill in normalized:
        key = (fill["strategy"], fill["symbol"])
        position = positions.get(
            key,
            {
                "quantity": 0.0,
                "avg_price": 0.0,
                "entry_ns": None,
            },
        )

        side = fill["side"]
        quantity = float(fill["quantity"])
        price = float(fill["price"])
        timestamp = _to_utc_timestamp(fill["timestamp"])

        if side == "BUY":
            prior_qty = float(position["quantity"])
            next_qty = prior_qty + quantity
            position["avg_price"] = (
                ((prior_qty * float(position["avg_price"])) + (quantity * price)) / next_qty
                if next_qty > EPSILON
                else 0.0
            )

            ts_ns = float(timestamp.value)
            if position["entry_ns"] is None:
                position["entry_ns"] = ts_ns
            else:
                position["entry_ns"] = (
                    ((prior_qty * float(position["entry_ns"])) + (quantity * ts_ns)) / next_qty
                    if next_qty > EPSILON
                    else ts_ns
                )
            position["quantity"] = next_qty
            positions[key] = position
            continue

        # SELL branch
        current_qty = float(position["quantity"])
        if current_qty <= EPSILON:
            continue

        close_qty = min(quantity, current_qty)
        avg_price = float(position["avg_price"])
        entry_ns = position["entry_ns"]
        if entry_ns is None:
            entry_ts = timestamp
        else:
            entry_ts = pd.Timestamp(int(entry_ns), tz="UTC")
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")

        pnl = (price - avg_price) * close_qty
        return_pct = (price / avg_price - 1.0) if avg_price > EPSILON else 0.0
        hold_time_hours = max(
            (
                timestamp.to_pydatetime(warn=False)
                - entry_ts.to_pydatetime(warn=False)
            ).total_seconds(),
            0.0,
        ) / 3600.0

        outcomes.append(
            TradeOutcome(
                strategy=fill["strategy"],
                symbol=fill["symbol"],
                timeframe=fill["timeframe"],
                regime=fill["regime"],
                run_id=fill["run_id"],
                entry_timestamp=entry_ts.to_pydatetime(warn=False),
                exit_timestamp=timestamp.to_pydatetime(warn=False),
                hold_time_hours=float(hold_time_hours),
                pnl=float(pnl),
                return_pct=float(return_pct),
            )
        )

        remaining = current_qty - close_qty
        if remaining <= EPSILON:
            position["quantity"] = 0.0
            position["avg_price"] = 0.0
            position["entry_ns"] = None
        else:
            position["quantity"] = remaining
        positions[key] = position

    return outcomes


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    """Normalize timestamp-like input to timezone-aware UTC Timestamp."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        return timestamp
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _compute_strategy_analytics(outcomes: list[TradeOutcome]) -> list[StrategyAnalytics]:
    """Compute strategy-level analytics from closed trade outcomes."""
    grouped: dict[str, list[TradeOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[outcome.strategy].append(outcome)

    rows: list[StrategyAnalytics] = []
    for strategy_name, strategy_outcomes in grouped.items():
        ordered = sorted(strategy_outcomes, key=lambda item: item.exit_timestamp)
        returns = pd.Series([item.return_pct for item in ordered], dtype=float)
        pnls = pd.Series([item.pnl for item in ordered], dtype=float)
        hold_hours = pd.Series([item.hold_time_hours for item in ordered], dtype=float)

        rolling_series = _rolling_metrics(ordered, window=20)
        latest_rolling = rolling_series[-1] if rolling_series else None

        rows.append(
            StrategyAnalytics(
                strategy=strategy_name,
                total_return=_total_return(returns),
                win_rate=_win_rate(pnls),
                average_win=_average_win(pnls),
                average_loss=_average_loss(pnls),
                profit_factor=_profit_factor(pnls),
                expectancy=_expectancy(pnls),
                sharpe=_sharpe(returns),
                max_drawdown=_max_drawdown(returns),
                num_trades=int(len(ordered)),
                average_hold_time_hours=float(hold_hours.mean()) if not hold_hours.empty else 0.0,
                rolling_20_win_rate=(latest_rolling.win_rate if latest_rolling else 0.0),
                rolling_20_expectancy=(latest_rolling.expectancy if latest_rolling else 0.0),
                rolling_20_sharpe=(latest_rolling.sharpe if latest_rolling else 0.0),
                rolling_20_series=tuple(rolling_series),
                last_5=_window_metrics(ordered, 5),
                last_20=_window_metrics(ordered, 20),
                last_60=_window_metrics(ordered, 60),
            )
        )

    rows.sort(key=lambda row: row.strategy)
    return rows


def _rolling_metrics(outcomes: list[TradeOutcome], window: int) -> list[RollingMetricPoint]:
    """Compute rolling metrics over a fixed trade-count window."""
    if len(outcomes) < window:
        return []

    rows: list[RollingMetricPoint] = []
    for end_index in range(window - 1, len(outcomes)):
        window_slice = outcomes[end_index - window + 1 : end_index + 1]
        returns = pd.Series([row.return_pct for row in window_slice], dtype=float)
        pnls = pd.Series([row.pnl for row in window_slice], dtype=float)
        rows.append(
            RollingMetricPoint(
                trade_index=end_index + 1,
                timestamp=window_slice[-1].exit_timestamp,
                win_rate=_win_rate(pnls),
                expectancy=_expectancy(pnls),
                sharpe=_sharpe(returns),
            )
        )
    return rows


def _window_metrics(outcomes: list[TradeOutcome], size: int) -> WindowMetrics:
    """Compute summary metrics over the latest `size` trades."""
    if not outcomes:
        return WindowMetrics(trades=0, total_return=0.0, win_rate=0.0, expectancy=0.0, sharpe=0.0)
    window = outcomes[-size:]
    returns = pd.Series([row.return_pct for row in window], dtype=float)
    pnls = pd.Series([row.pnl for row in window], dtype=float)
    return WindowMetrics(
        trades=len(window),
        total_return=_total_return(returns),
        win_rate=_win_rate(pnls),
        expectancy=_expectancy(pnls),
        sharpe=_sharpe(returns),
    )


def _compute_portfolio_analytics(
    outcomes: list[TradeOutcome],
    snapshot: PortfolioSnapshot,
    starting_equity: float,
) -> PortfolioAnalytics:
    """Compute portfolio-level analytics from outcomes and snapshot state."""
    realized_pnl = float(sum(outcome.pnl for outcome in outcomes))
    unrealized_pnl = float(sum(position.unrealized_pnl for position in snapshot.positions.values()))

    equity_points, daily_points, drawdown_points = _portfolio_time_series(
        outcomes=outcomes,
        starting_equity=starting_equity,
        unrealized_pnl=unrealized_pnl,
    )

    contribution_rows = _strategy_contribution_rows(outcomes, starting_equity)

    exposure_rows = []
    gross_exposure = 0.0
    largest_notional = 0.0
    for symbol, position in sorted(snapshot.positions.items()):
        if position.quantity <= EPSILON:
            continue
        notional = float(position.quantity * position.avg_price)
        gross_exposure += abs(notional)
        largest_notional = max(largest_notional, abs(notional))
        exposure_rows.append(
            SymbolExposure(
                symbol=symbol,
                quantity=float(position.quantity),
                avg_price=float(position.avg_price),
                notional=notional,
                unrealized_pnl=float(position.unrealized_pnl),
            )
        )

    open_risk = OpenRiskSummary(
        open_positions=int(sum(1 for position in snapshot.positions.values() if position.quantity > EPSILON)),
        gross_exposure=float(gross_exposure),
        largest_position_notional=float(largest_notional),
        cash=float(snapshot.cash),
        day_start_equity=float(snapshot.day_start_equity),
        peak_equity=float(snapshot.peak_equity),
    )

    return PortfolioAnalytics(
        equity_curve=tuple(equity_points),
        daily_pnl=tuple(daily_points),
        rolling_drawdown=tuple(drawdown_points),
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        strategy_contribution=tuple(contribution_rows),
        exposure_by_symbol=tuple(exposure_rows),
        open_risk_summary=open_risk,
    )


def _portfolio_time_series(
    outcomes: list[TradeOutcome],
    starting_equity: float,
    unrealized_pnl: float,
) -> tuple[list[TimeSeriesPoint], list[TimeSeriesPoint], list[TimeSeriesPoint]]:
    """Build equity/daily-PnL/drawdown series from realized outcomes."""
    if not outcomes:
        return ([], [], [])

    frame = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp(outcome.exit_timestamp) for outcome in outcomes],
            "pnl": [outcome.pnl for outcome in outcomes],
        }
    ).sort_values("timestamp")

    frame["date"] = frame["timestamp"].dt.normalize()
    daily_realized = frame.groupby("date", as_index=True)["pnl"].sum().sort_index()

    today = pd.Timestamp.now(tz="UTC").normalize()
    if daily_realized.index.max() < today:
        daily_realized.loc[today] = 0.0
    daily_realized = daily_realized.sort_index()

    cumulative_realized = daily_realized.cumsum()
    equity = starting_equity + cumulative_realized
    equity.iloc[-1] += unrealized_pnl

    daily_pnl = equity.diff().fillna(0.0)
    drawdown = (equity / equity.cummax() - 1.0).fillna(0.0)

    equity_points = [
        TimeSeriesPoint(timestamp=ts.to_pydatetime(), value=float(value))
        for ts, value in equity.items()
    ]
    daily_points = [
        TimeSeriesPoint(timestamp=ts.to_pydatetime(), value=float(value))
        for ts, value in daily_pnl.items()
    ]
    drawdown_points = [
        TimeSeriesPoint(timestamp=ts.to_pydatetime(), value=float(value))
        for ts, value in drawdown.items()
    ]

    return equity_points, daily_points, drawdown_points


def _strategy_contribution_rows(
    outcomes: list[TradeOutcome],
    starting_equity: float,
) -> list[StrategyContribution]:
    """Compute realized PnL contribution by strategy."""
    grouped: dict[str, list[TradeOutcome]] = defaultdict(list)
    for row in outcomes:
        grouped[row.strategy].append(row)

    rows: list[StrategyContribution] = []
    for strategy_name, strategy_outcomes in grouped.items():
        pnl = float(sum(row.pnl for row in strategy_outcomes))
        rows.append(
            StrategyContribution(
                strategy=strategy_name,
                realized_pnl=pnl,
                return_pct=(pnl / starting_equity) if starting_equity > EPSILON else 0.0,
                trades=len(strategy_outcomes),
            )
        )
    rows.sort(key=lambda row: row.strategy)
    return rows


def _compute_context_analytics(outcomes: list[TradeOutcome]) -> ContextAnalytics:
    """Compute grouped context analytics across symbol/time/timeframe/regime buckets."""
    return ContextAnalytics(
        by_symbol=_grouped_context(outcomes, key_fn=lambda row: row.symbol),
        by_timeframe=_grouped_context(outcomes, key_fn=lambda row: row.timeframe),
        by_weekday=_grouped_context(
            outcomes,
            key_fn=lambda row: pd.Timestamp(row.exit_timestamp).day_name(),
        ),
        by_hour=_grouped_context(
            outcomes,
            key_fn=lambda row: f"{pd.Timestamp(row.exit_timestamp).hour:02d}:00",
        ),
        by_regime=_grouped_context(outcomes, key_fn=lambda row: row.regime),
    )


def _grouped_context(
    outcomes: list[TradeOutcome],
    key_fn,
) -> tuple[ContextBucketPerformance, ...]:
    """Aggregate one context dimension into deterministic grouped metrics."""
    grouped: dict[str, list[TradeOutcome]] = defaultdict(list)
    for row in outcomes:
        grouped[str(key_fn(row))].append(row)

    items: list[ContextBucketPerformance] = []
    for key in sorted(grouped):
        bucket = grouped[key]
        returns = pd.Series([row.return_pct for row in bucket], dtype=float)
        pnls = pd.Series([row.pnl for row in bucket], dtype=float)
        items.append(
            ContextBucketPerformance(
                key=key,
                trades=len(bucket),
                total_return=_total_return(returns),
                win_rate=_win_rate(pnls),
                expectancy=_expectancy(pnls),
                sharpe=_sharpe(returns),
                total_pnl=float(pnls.sum()),
            )
        )
    return tuple(items)


def _total_return(returns: pd.Series) -> float:
    """Compute compounded total return from period returns."""
    clean = _clean_series(returns)
    if clean.empty:
        return 0.0
    return float((1.0 + clean).prod() - 1.0)


def _win_rate(pnls: pd.Series) -> float:
    """Compute win rate from non-zero realized PnL values."""
    clean = _clean_series(pnls)
    clean = clean[clean != 0.0]
    if clean.empty:
        return 0.0
    return float((clean > 0.0).sum() / len(clean))


def _average_win(pnls: pd.Series) -> float:
    """Compute average positive PnL."""
    clean = _clean_series(pnls)
    wins = clean[clean > 0.0]
    if wins.empty:
        return 0.0
    return float(wins.mean())


def _average_loss(pnls: pd.Series) -> float:
    """Compute average negative PnL."""
    clean = _clean_series(pnls)
    losses = clean[clean < 0.0]
    if losses.empty:
        return 0.0
    return float(losses.mean())


def _profit_factor(pnls: pd.Series) -> float:
    """Compute profit factor from realized PnL."""
    clean = _clean_series(pnls)
    gross_profit = float(clean[clean > 0.0].sum())
    gross_loss = float(abs(clean[clean < 0.0].sum()))
    if gross_loss <= EPSILON:
        return 0.0
    return float(gross_profit / gross_loss)


def _expectancy(pnls: pd.Series) -> float:
    """Compute expectancy from win rate and average win/loss."""
    clean = _clean_series(pnls)
    if clean.empty:
        return 0.0
    win_rate = _win_rate(clean)
    avg_win = _average_win(clean)
    avg_loss = abs(_average_loss(clean))
    return float((win_rate * avg_win) - ((1.0 - win_rate) * avg_loss))


def _sharpe(returns: pd.Series) -> float:
    """Compute Sharpe ratio from trade returns."""
    clean = _clean_series(returns)
    if clean.empty:
        return 0.0
    std = float(clean.std(ddof=0))
    if std <= EPSILON:
        return 0.0
    return float(clean.mean() / std)


def _max_drawdown(returns: pd.Series) -> float:
    """Compute max drawdown from compounded returns."""
    clean = _clean_series(returns)
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(abs(drawdown.min()))


def _clean_series(values: pd.Series) -> pd.Series:
    """Drop non-finite values for deterministic metric handling."""
    return values.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
