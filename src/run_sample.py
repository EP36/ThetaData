"""Run one end-to-end sample backtest and paper-trade flow."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.backtest.engine import BacktestEngine
from src.config.settings import Settings
from src.data.loader import MarketDataLoader
from src.execution.models import Order
from src.execution.paper_executor import PaperTradingExecutor
from src.observability import clear_run, configure_logging, start_run
from src.risk.manager import RiskManager
from src.strategies.moving_average_crossover import MovingAverageCrossoverStrategy


def run_sample() -> None:
    """Execute a complete sample workflow."""
    configure_logging()
    run_id = start_run()
    try:
        settings = Settings.from_env()

        loader = MarketDataLoader()
        data = loader.generate_synthetic_ohlcv(start="2024-01-01", periods=300, freq="D")

        strategy = MovingAverageCrossoverStrategy(short_window=20, long_window=50)
        risk_manager = RiskManager(
            max_position_size=settings.max_position_size,
            max_daily_loss=settings.max_daily_loss,
        )
        engine = BacktestEngine(
            initial_capital=settings.initial_capital,
            position_size_pct=settings.position_size_pct,
            fixed_fee=settings.fixed_fee,
            slippage_pct=settings.slippage_pct,
            stop_loss_pct=settings.stop_loss_pct,
            take_profit_pct=settings.take_profit_pct,
        )

        result = engine.run(
            data=data,
            strategy=strategy,
            risk_manager=risk_manager,
            trade_log_path=settings.trade_log_path,
            symbol="SYNTH",
        )

        print("=== Backtest Performance ===")
        for key, value in result.report.items():
            print(f"{key}: {value:.4f}")
        print(f"Trades logged to: {Path(settings.trade_log_path).resolve()}")

        executor = PaperTradingExecutor(
            starting_cash=settings.initial_capital,
            risk_manager=risk_manager,
            paper_trading_enabled=settings.paper_trading_enabled,
            max_notional_per_trade=settings.max_notional_per_trade,
            max_open_positions=settings.executor_max_open_positions,
            daily_loss_cap=settings.executor_daily_loss_cap,
        )

        latest_signal = float(result.signals.iloc[-1])
        latest_price = float(data["close"].iloc[-1])
        latest_timestamp = pd.Timestamp(data.index[-1])

        if latest_signal > 0.0:
            order = Order(
                symbol="SYNTH",
                side="BUY",
                quantity=latest_signal,
                price=latest_price,
                timestamp=latest_timestamp,
            )
            submitted = executor.submit_order(order)
            if submitted.status == "FILLED" and executor.filled_orders:
                fill = executor.filled_orders[-1]
                print(
                    f"Paper fill: {fill.side} {fill.quantity:.4f} {fill.symbol} "
                    f"@ {fill.price:.2f}"
                )
            else:
                print(f"Paper order rejected: {submitted.rejection_reasons}")
        else:
            print("No paper trade submitted: latest signal is flat (0.0)")

        paper_log_path = executor.export_trades("logs/paper_trades.csv")
        print(f"Paper fills logged to: {paper_log_path}")
        print(f"Run ID: {run_id}")
    finally:
        clear_run()


if __name__ == "__main__":
    run_sample()
