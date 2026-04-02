"""Tests for CLI parser and command workflows."""

from __future__ import annotations

import json
from pathlib import Path

from src.cli.app import build_parser, main


def test_cli_parser_smoke() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "backtest",
            "--symbol",
            "AAPL",
            "--timeframe",
            "1d",
            "--strategy",
            "moving_average_crossover",
        ]
    )
    assert args.command == "backtest"
    assert args.symbol == "AAPL"


def test_cli_download_and_report_workflow(tmp_path, capsys) -> None:
    cache_dir = tmp_path / "cache"
    trade_log_path = tmp_path / "trades.csv"
    output_dir = tmp_path / "report"

    exit_code = main(
        [
            "download-data",
            "--symbol",
            "SPY",
            "--timeframe",
            "1d",
            "--cache-dir",
            str(cache_dir),
            "--force-refresh",
        ]
    )
    assert exit_code == 0
    download_payload = json.loads(capsys.readouterr().out.strip())
    assert download_payload["rows"] > 0
    assert Path(download_payload["cache_file"]).exists()

    exit_code = main(
        [
            "report",
            "--symbol",
            "SPY",
            "--timeframe",
            "1d",
            "--strategy",
            "moving_average_crossover",
            "--strategy-param",
            "short_window=5",
            "--strategy-param",
            "long_window=20",
            "--cache-dir",
            str(cache_dir),
            "--trade-log-path",
            str(trade_log_path),
            "--output-dir",
            str(output_dir),
            "--force-refresh",
        ]
    )
    assert exit_code == 0
    report_payload = json.loads(capsys.readouterr().out.strip())
    assert "metrics" in report_payload
    assert "artifacts" in report_payload
    assert Path(report_payload["artifacts"]["equity_curve_plot"]).exists()
