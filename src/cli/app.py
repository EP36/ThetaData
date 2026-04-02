"""CLI entrypoint for data download, backtest, and analytics reporting."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from src.cli.services import (
    download_data,
    generate_report,
    parse_optional_float,
    parse_strategy_params,
    run_backtest,
)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser with supported subcommands."""
    parser = argparse.ArgumentParser(prog="theta", description="Trading system MVP CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download-data", help="Fetch and cache market data")
    download.add_argument("--symbol", required=True)
    download.add_argument("--timeframe", required=True)
    download.add_argument("--start")
    download.add_argument("--end")
    download.add_argument("--cache-dir", default="data/cache")
    download.add_argument("--force-refresh", action="store_true")

    backtest = subparsers.add_parser("backtest", help="Run a backtest")
    backtest.add_argument("--symbol", required=True)
    backtest.add_argument("--timeframe", required=True)
    backtest.add_argument("--strategy", required=True)
    backtest.add_argument("--strategy-param", action="append", default=[])
    backtest.add_argument("--start")
    backtest.add_argument("--end")
    backtest.add_argument("--cache-dir", default="data/cache")
    backtest.add_argument("--trade-log-path", default="logs/trades.csv")
    backtest.add_argument("--initial-capital", type=float, default=100000.0)
    backtest.add_argument("--position-size-pct", type=float, default=1.0)
    backtest.add_argument("--fixed-fee", type=float, default=1.0)
    backtest.add_argument("--slippage-pct", type=float, default=0.0005)
    backtest.add_argument("--stop-loss-pct", default="")
    backtest.add_argument("--take-profit-pct", default="")
    backtest.add_argument("--max-position-size", type=float, default=1.0)
    backtest.add_argument("--max-daily-loss", type=float, default=2000.0)
    backtest.add_argument("--force-refresh", action="store_true")

    report = subparsers.add_parser("report", help="Run backtest and generate analytics report")
    report.add_argument("--symbol", required=True)
    report.add_argument("--timeframe", required=True)
    report.add_argument("--strategy", required=True)
    report.add_argument("--strategy-param", action="append", default=[])
    report.add_argument("--start")
    report.add_argument("--end")
    report.add_argument("--cache-dir", default="data/cache")
    report.add_argument("--trade-log-path", default="logs/trades.csv")
    report.add_argument("--output-dir", default="logs/report")
    report.add_argument("--initial-capital", type=float, default=100000.0)
    report.add_argument("--position-size-pct", type=float, default=1.0)
    report.add_argument("--fixed-fee", type=float, default=1.0)
    report.add_argument("--slippage-pct", type=float, default=0.0005)
    report.add_argument("--stop-loss-pct", default="")
    report.add_argument("--take-profit-pct", default="")
    report.add_argument("--max-position-size", type=float, default=1.0)
    report.add_argument("--max-daily-loss", type=float, default=2000.0)
    report.add_argument("--force-refresh", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run CLI command dispatcher."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "download-data":
        result = download_data(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            cache_dir=args.cache_dir,
            force_refresh=args.force_refresh,
        )
        print(json.dumps({"rows": result.rows, "cache_file": result.cache_file}))
        return 0

    strategy_params = parse_strategy_params(args.strategy_param)
    stop_loss_pct = parse_optional_float(args.stop_loss_pct)
    take_profit_pct = parse_optional_float(args.take_profit_pct)

    backtest_result = run_backtest(
        symbol=args.symbol,
        timeframe=args.timeframe,
        strategy_name=args.strategy,
        strategy_params=strategy_params,
        start=args.start,
        end=args.end,
        cache_dir=args.cache_dir,
        trade_log_path=args.trade_log_path,
        initial_capital=args.initial_capital,
        position_size_pct=args.position_size_pct,
        fixed_fee=args.fixed_fee,
        slippage_pct=args.slippage_pct,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        max_position_size=args.max_position_size,
        max_daily_loss=args.max_daily_loss,
        force_refresh=args.force_refresh,
    )

    if args.command == "backtest":
        print(json.dumps(backtest_result.metrics))
        return 0

    if args.command == "report":
        report = generate_report(backtest_result=backtest_result, output_dir=args.output_dir)
        print(json.dumps({"metrics": report.metrics, "artifacts": report.artifacts}))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
