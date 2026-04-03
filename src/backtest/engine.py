"""Backtest engine for long-only portfolio simulation."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from src.backtest.reporting import TRADE_LOG_COLUMNS, build_summary_metrics, trades_to_frame
from src.backtest.types import Trade
from src.risk.manager import RiskManager
from src.risk.models import OrderRiskRequest, PortfolioRiskState
from src.strategies.base import Strategy

REQUIRED_OHLCV_COLUMNS = ("open", "high", "low", "close", "volume")
EPSILON = 1e-12
LOGGER = logging.getLogger("theta.backtest.engine")


@dataclass(slots=True)
class BacktestResult:
    """Structured output from a backtest run."""

    equity_curve: pd.Series
    trades: list[Trade]
    metrics: dict[str, float]
    signals: pd.Series
    position_series: pd.Series
    strategy_returns: pd.Series

    @property
    def report(self) -> dict[str, float]:
        """Backward-compatible alias for metrics."""
        return self.metrics


@dataclass(slots=True)
class BacktestEngine:
    """Run long-only backtests with fees, slippage, and protective exits."""

    initial_capital: float = 100_000.0
    position_size_pct: float = 1.0
    fixed_fee: float = 1.0
    slippage_pct: float = 0.0005
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    trailing_stop_pct: float | None = None

    def __post_init__(self) -> None:
        """Validate backtest settings."""
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.position_size_pct <= 0 or self.position_size_pct > 1:
            raise ValueError("position_size_pct must be in (0, 1]")
        if self.fixed_fee < 0:
            raise ValueError("fixed_fee cannot be negative")
        if self.slippage_pct < 0 or self.slippage_pct >= 1:
            raise ValueError("slippage_pct must be in [0, 1)")
        if self.stop_loss_pct is not None and (
            self.stop_loss_pct <= 0 or self.stop_loss_pct >= 1
        ):
            raise ValueError("stop_loss_pct must be in (0, 1)")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive")
        if self.trailing_stop_pct is not None and (
            self.trailing_stop_pct <= 0 or self.trailing_stop_pct >= 1
        ):
            raise ValueError("trailing_stop_pct must be in (0, 1)")

    def run(
        self,
        data: pd.DataFrame,
        strategy: Strategy,
        risk_manager: RiskManager | None = None,
        trade_log_path: str | Path | None = None,
        symbol: str = "UNKNOWN",
    ) -> BacktestResult:
        """Execute a backtest over market data.

        Args:
            data: Market OHLCV data indexed by timestamp.
            strategy: Strategy implementation.
            risk_manager: Optional risk manager.
            trade_log_path: Optional CSV path for trade logging.
            symbol: Instrument symbol for run-level logging.

        Returns:
            BacktestResult with equity curve, trades, and summary metrics.
        """
        market_data = self._validate_market_data(data)
        LOGGER.info(
            "backtest_run_start symbol=%s strategy=%s bars=%d",
            symbol,
            strategy.name,
            len(market_data),
        )
        signals = self._prepare_signals(strategy, market_data)
        signal_count = int((signals > EPSILON).sum())
        LOGGER.info(
            "strategy_signals_generated symbol=%s strategy=%s nonzero_signals=%d",
            symbol,
            strategy.name,
            signal_count,
        )

        cash = self.initial_capital
        shares = 0.0
        entry_price: float | None = None
        trailing_peak_price: float | None = None

        equity_values = [self.initial_capital]
        position_values = [0.0]
        trades: list[Trade] = []
        rejected_order_count = 0

        current_day = market_data.index[0].date()
        day_start_equity = self.initial_capital
        previous_signal = 0.0

        close_prices = market_data["close"].astype(float)
        high_prices = market_data["high"].astype(float)
        low_prices = market_data["low"].astype(float)

        for i in range(1, len(market_data)):
            timestamp = market_data.index[i]
            close_price = float(close_prices.iloc[i])
            high_price = float(high_prices.iloc[i])
            low_price = float(low_prices.iloc[i])
            if timestamp.date() != current_day:
                current_day = timestamp.date()
                day_start_equity = cash + shares * close_price

            if shares > EPSILON:
                trailing_peak_price = (
                    high_price
                    if trailing_peak_price is None
                    else max(trailing_peak_price, high_price)
                )
            else:
                trailing_peak_price = None

            stop_or_take_triggered = False
            if shares > EPSILON and entry_price is not None:
                (
                    cash,
                    shares,
                    entry_price,
                    trailing_peak_price,
                    protective_trade,
                    stop_or_take_triggered,
                ) = (
                    self._apply_protective_exit(
                        timestamp=timestamp,
                        low_price=low_price,
                        high_price=high_price,
                        close_price=close_price,
                        cash=cash,
                        shares=shares,
                        entry_price=entry_price,
                        trailing_peak_price=trailing_peak_price,
                    )
                )
                if protective_trade is not None:
                    trades.append(protective_trade)
                    LOGGER.info(
                        "stop_exit_triggered symbol=%s timestamp=%s reason=%s fill_price=%.6f qty=%.6f",
                        symbol,
                        timestamp,
                        protective_trade.reason,
                        protective_trade.fill_price,
                        protective_trade.quantity,
                    )

            if not stop_or_take_triggered:
                raw_signal = float(signals.iloc[i - 1])
                if raw_signal > EPSILON and previous_signal <= EPSILON:
                    LOGGER.info(
                        "signal_triggered symbol=%s timestamp=%s signal=%.4f",
                        symbol,
                        timestamp,
                        raw_signal,
                    )
                previous_signal = raw_signal
                desired_position = raw_signal * self.position_size_pct
                current_equity = cash + shares * close_price

                if risk_manager is not None:
                    desired_position = risk_manager.enforce(
                        timestamp=timestamp,
                        target_position=desired_position,
                        day_start_equity=day_start_equity,
                        current_equity=current_equity,
                    )

                desired_position = float(
                    np.clip(desired_position, 0.0, self.position_size_pct)
                )
                target_shares = (current_equity * desired_position) / close_price
                delta_shares = target_shares - shares

                if delta_shares > EPSILON:
                    decision = None
                    if risk_manager is not None:
                        decision = self._validate_order_with_risk_manager(
                            risk_manager=risk_manager,
                            symbol=symbol,
                            side="BUY",
                            quantity=float(delta_shares),
                            price=close_price,
                            timestamp=timestamp,
                            current_equity=current_equity,
                            day_start_equity=day_start_equity,
                            shares=shares,
                            peak_equity=max(equity_values),
                        )
                    if decision is not None and not decision.approved:
                        rejected_order_count += 1
                        LOGGER.warning(
                            "backtest_trade_rejected symbol=%s timestamp=%s side=BUY reasons=%s",
                            symbol,
                            timestamp,
                            ",".join(decision.reasons),
                        )
                    else:
                        cash, shares, entry_price, buy_trade = self._execute_buy(
                            timestamp=timestamp,
                            reference_price=close_price,
                            close_price=close_price,
                            quantity=delta_shares,
                            cash=cash,
                            shares=shares,
                            entry_price=entry_price,
                            reason="signal",
                        )
                        if buy_trade is not None:
                            trailing_peak_price = max(high_price, buy_trade.fill_price)
                            trades.append(buy_trade)
                elif delta_shares < -EPSILON:
                    decision = None
                    if risk_manager is not None:
                        decision = self._validate_order_with_risk_manager(
                            risk_manager=risk_manager,
                            symbol=symbol,
                            side="SELL",
                            quantity=float(abs(delta_shares)),
                            price=close_price,
                            timestamp=timestamp,
                            current_equity=current_equity,
                            day_start_equity=day_start_equity,
                            shares=shares,
                            peak_equity=max(equity_values),
                        )
                    if decision is not None and not decision.approved:
                        rejected_order_count += 1
                        LOGGER.warning(
                            "backtest_trade_rejected symbol=%s timestamp=%s side=SELL reasons=%s",
                            symbol,
                            timestamp,
                            ",".join(decision.reasons),
                        )
                    else:
                        cash, shares, entry_price, sell_trade = self._execute_sell(
                            timestamp=timestamp,
                            reference_price=close_price,
                            close_price=close_price,
                            quantity=abs(delta_shares),
                            cash=cash,
                            shares=shares,
                            entry_price=entry_price,
                            reason="signal",
                        )
                        if sell_trade is not None:
                            if shares <= EPSILON:
                                trailing_peak_price = None
                            trades.append(sell_trade)

            equity = cash + shares * close_price
            position_pct = (shares * close_price / equity) if equity > 0 else 0.0

            equity_values.append(equity)
            position_values.append(position_pct)

        equity_curve = pd.Series(equity_values, index=market_data.index, name="equity")
        position_series = pd.Series(position_values, index=market_data.index, name="position")
        strategy_returns = equity_curve.pct_change().fillna(0.0).rename("strategy_returns")

        if trade_log_path is not None:
            output_path = Path(trade_log_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            trades_to_frame(trades).to_csv(output_path, index=False)

        metrics = build_summary_metrics(
            equity_curve=equity_curve,
            strategy_returns=strategy_returns,
            trades=trades,
        )
        metrics["rejected_orders"] = float(rejected_order_count)
        max_drawdown = float((equity_curve / equity_curve.cummax() - 1.0).min())
        LOGGER.info(
            "backtest_run_summary symbol=%s signals=%d trades=%d final_equity=%.2f max_drawdown=%.6f",
            symbol,
            signal_count,
            len(trades),
            float(equity_curve.iloc[-1]),
            max_drawdown,
        )

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics=metrics,
            signals=signals,
            position_series=position_series,
            strategy_returns=strategy_returns,
        )

    def _validate_market_data(self, data: pd.DataFrame) -> pd.DataFrame:
        """Validate and coerce market data to expected OHLCV shape."""
        if data.empty:
            raise ValueError("Backtest data cannot be empty")
        if not isinstance(data.index, pd.DatetimeIndex):
            raise ValueError("Backtest data index must be a DatetimeIndex")

        missing = [column for column in REQUIRED_OHLCV_COLUMNS if column not in data.columns]
        if missing:
            raise ValueError(f"Backtest data missing required OHLCV columns: {missing}")

        validated = data.copy()
        validated.loc[:, REQUIRED_OHLCV_COLUMNS] = validated.loc[
            :, REQUIRED_OHLCV_COLUMNS
        ].apply(pd.to_numeric, errors="coerce")
        if validated.loc[:, REQUIRED_OHLCV_COLUMNS].isna().any().any():
            raise ValueError("Backtest data contains non-numeric OHLCV values")
        if (validated[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError("OHLC prices must be strictly positive")
        if (validated["high"] < validated["low"]).any():
            raise ValueError("High price cannot be lower than low price")

        return validated

    def _prepare_signals(self, strategy: Strategy, data: pd.DataFrame) -> pd.Series:
        """Generate and validate strategy signals."""
        strategy.validate_required_columns(data)
        signal_frame = strategy.generate_signals(data).reindex(data.index)
        if "signal" not in signal_frame.columns:
            raise ValueError(
                f"Strategy '{strategy.name}' output must include a 'signal' column"
            )

        signals = signal_frame["signal"].fillna(0.0).astype(float)
        if not np.isfinite(signals.to_numpy()).all():
            raise ValueError("Strategy signals contain non-finite values")
        if (signals < -EPSILON).any():
            raise ValueError("Long-only backtest does not allow negative signals")
        return signals.clip(lower=0.0, upper=1.0).rename("signal")

    def _apply_protective_exit(
        self,
        timestamp: pd.Timestamp,
        low_price: float,
        high_price: float,
        close_price: float,
        cash: float,
        shares: float,
        entry_price: float,
        trailing_peak_price: float | None,
    ) -> tuple[float, float, float | None, float | None, Trade | None, bool]:
        """Apply stop loss / take profit logic for an open position."""
        if self.stop_loss_pct is not None:
            stop_price = entry_price * (1.0 - self.stop_loss_pct)
            if low_price <= stop_price:
                cash, shares, entry_price, trade = self._execute_sell(
                    timestamp=timestamp,
                    reference_price=stop_price,
                    close_price=close_price,
                    quantity=shares,
                    cash=cash,
                    shares=shares,
                    entry_price=entry_price,
                    reason="stop_loss",
                )
                return cash, shares, entry_price, None, trade, True

        if self.take_profit_pct is not None:
            take_profit_price = entry_price * (1.0 + self.take_profit_pct)
            if high_price >= take_profit_price:
                cash, shares, entry_price, trade = self._execute_sell(
                    timestamp=timestamp,
                    reference_price=take_profit_price,
                    close_price=close_price,
                    quantity=shares,
                    cash=cash,
                    shares=shares,
                    entry_price=entry_price,
                    reason="take_profit",
                )
                return cash, shares, entry_price, None, trade, True

        if self.trailing_stop_pct is not None and trailing_peak_price is not None:
            trailing_stop_price = trailing_peak_price * (1.0 - self.trailing_stop_pct)
            if low_price <= trailing_stop_price:
                cash, shares, entry_price, trade = self._execute_sell(
                    timestamp=timestamp,
                    reference_price=trailing_stop_price,
                    close_price=close_price,
                    quantity=shares,
                    cash=cash,
                    shares=shares,
                    entry_price=entry_price,
                    reason="trailing_stop",
                )
                return cash, shares, entry_price, None, trade, True

        return cash, shares, entry_price, trailing_peak_price, None, False

    def _execute_buy(
        self,
        timestamp: pd.Timestamp,
        reference_price: float,
        close_price: float,
        quantity: float,
        cash: float,
        shares: float,
        entry_price: float | None,
        reason: str,
    ) -> tuple[float, float, float | None, Trade | None]:
        """Execute a long-side fill."""
        if quantity <= EPSILON:
            return cash, shares, entry_price, None

        fill_price = reference_price * (1.0 + self.slippage_pct)
        affordable_quantity = max((cash - self.fixed_fee) / fill_price, 0.0)
        fill_quantity = min(quantity, affordable_quantity)
        if fill_quantity <= EPSILON:
            return cash, shares, entry_price, None

        cost = fill_quantity * fill_price + self.fixed_fee
        next_cash = cash - cost
        previous_shares = shares
        next_shares = shares + fill_quantity

        if previous_shares <= EPSILON or entry_price is None:
            next_entry_price = fill_price
        else:
            next_entry_price = (
                previous_shares * entry_price + fill_quantity * fill_price
            ) / next_shares

        equity_after = next_cash + next_shares * close_price
        trade = Trade(
            timestamp=timestamp,
            side="BUY",
            quantity=float(fill_quantity),
            fill_price=float(fill_price),
            fee=float(self.fixed_fee),
            reason=reason,
            cash_after=float(next_cash),
            shares_after=float(next_shares),
            equity_after=float(equity_after),
        )
        LOGGER.info(
            "trade_executed side=BUY timestamp=%s reason=%s qty=%.6f fill_price=%.6f",
            timestamp,
            reason,
            fill_quantity,
            fill_price,
        )
        return next_cash, next_shares, next_entry_price, trade

    def _execute_sell(
        self,
        timestamp: pd.Timestamp,
        reference_price: float,
        close_price: float,
        quantity: float,
        cash: float,
        shares: float,
        entry_price: float | None,
        reason: str,
    ) -> tuple[float, float, float | None, Trade | None]:
        """Execute a sell fill to reduce or close a long position."""
        if quantity <= EPSILON or shares <= EPSILON:
            return cash, shares, entry_price, None

        fill_quantity = min(quantity, shares)
        fill_price = reference_price * (1.0 - self.slippage_pct)
        proceeds = fill_quantity * fill_price - self.fixed_fee

        next_cash = cash + proceeds
        next_shares = shares - fill_quantity
        if next_shares <= EPSILON:
            next_shares = 0.0
            next_entry_price: float | None = None
        else:
            next_entry_price = entry_price

        equity_after = next_cash + next_shares * close_price
        trade = Trade(
            timestamp=timestamp,
            side="SELL",
            quantity=float(fill_quantity),
            fill_price=float(fill_price),
            fee=float(self.fixed_fee),
            reason=reason,
            cash_after=float(next_cash),
            shares_after=float(next_shares),
            equity_after=float(equity_after),
        )
        LOGGER.info(
            "trade_executed side=SELL timestamp=%s reason=%s qty=%.6f fill_price=%.6f",
            timestamp,
            reason,
            fill_quantity,
            fill_price,
        )
        return next_cash, next_shares, next_entry_price, trade

    def _validate_order_with_risk_manager(
        self,
        risk_manager: RiskManager,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        timestamp: pd.Timestamp,
        current_equity: float,
        day_start_equity: float,
        shares: float,
        peak_equity: float,
    ):
        """Validate one backtest fill request with shared risk manager rules."""
        open_positions: dict[str, float] = {}
        gross_exposure = max(shares, 0.0) * price
        if shares > EPSILON:
            open_positions[symbol] = gross_exposure

        state = PortfolioRiskState(
            equity=float(current_equity),
            day_start_equity=float(day_start_equity),
            peak_equity=float(peak_equity),
            gross_exposure=float(gross_exposure),
            open_positions=open_positions,
        )
        request = OrderRiskRequest(
            symbol=symbol,
            side=side,
            quantity=float(quantity),
            price=float(price),
            timestamp=timestamp,
            stop_loss_pct=self.stop_loss_pct,
            trailing_stop_pct=self.trailing_stop_pct,
        )
        return risk_manager.validate_order(request=request, state=state)
