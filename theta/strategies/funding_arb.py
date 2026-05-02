"""FundingArbStrategy — wraps the existing funding_arb.monitor logic.

Surfaces the funding rate arbitrage opportunity through the Strategy
interface so the orchestration runner can rank it alongside other strategies.

Signal:
  - Fetch Hyperliquid funding rates and predicted rates.
  - For each eligible asset, call compare_carry() to choose funding vs basis.
  - Return the best opportunity if within the 15-minute execution window AND
    the annualized return exceeds MIN_ANNUAL_PCT.

The expected_edge_bps is derived from the annualized carry:
  edge_bps = (annual_pct / 100) / (3 * 365) * 10_000
  (converts annual % back to a single funding-period bps equivalent)

This is a multi-leg strategy (spot long + perp short on Hyperliquid), so
the PlannedTrade product_id represents the primary leg.  execute() delegates
to funding_arb.executor.enter_arb() which handles both legs atomically.

Env vars consumed (same as funding_arb/monitor.py):
  HL_MIN_FUNDING_RATE   float  default=0.0015  minimum hourly rate to flag
  HL_MAX_POSITION_USD   float  default=50      position size
  HL_DRY_RUN            bool   default=true
  HL_PRIVATE_KEY        str    required for live execution
  HL_WALLET             str    required for live execution
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from theta.strategies.base import ExecutionResult, PlannedTrade

LOGGER = logging.getLogger("theta.strategies.funding_arb")

# Annual % → single-period bps conversion factor:
#   1% annual / (3 funding/day × 365 days) × 10_000 = 0.912 bps per period
_ANNUAL_PCT_TO_PERIOD_BPS = 10_000.0 / (3.0 * 365.0)


class FundingArbStrategy:
    """Long spot / short perp carry on Hyperliquid, surfaced as a Strategy."""

    def __init__(
        self,
        min_funding_rate: float | None = None,
        max_position_usd: float | None = None,
        min_annual_pct: float | None = None,
        entry_window_sec: int = 900,   # enter only within 15 min of funding
    ) -> None:
        self._min_rate = (
            min_funding_rate
            if min_funding_rate is not None
            else float(os.getenv("HL_MIN_FUNDING_RATE", "0.0015"))
        )
        self._pos_usd = (
            max_position_usd
            if max_position_usd is not None
            else float(os.getenv("HL_MAX_POSITION_USD", "50.0"))
        )
        self._min_annual_pct = (
            min_annual_pct
            if min_annual_pct is not None
            else float(os.getenv("MIN_BASIS_PCT", "1.0"))
        )
        self._entry_window_sec = entry_window_sec

    # ------------------------------------------------------------------
    # Strategy Protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "funding_arb_hl"

    def evaluate_opportunity(self, now: datetime) -> Optional[PlannedTrade]:
        from funding_arb.monitor import (
            get_funding_rates,
            get_predicted_rates,
            seconds_to_next_funding,
            compare_carry,
        )

        secs_left = seconds_to_next_funding()
        in_window = secs_left <= self._entry_window_sec

        LOGGER.info(
            "%s evaluate secs_to_funding=%d in_window=%s",
            self.name, secs_left, in_window,
        )

        try:
            rates = get_funding_rates()
            predicted = get_predicted_rates()
        except Exception as exc:
            LOGGER.warning("%s evaluate fetch_failed error=%s", self.name, exc)
            return None

        best: Optional[PlannedTrade] = None
        best_edge = 0.0

        for r in rates:
            asset = r["asset"]
            cur_rate = r["rate"]
            pred_rate = predicted.get(asset, 0.0)

            # Both current and predicted must be strong enough.
            if cur_rate < self._min_rate or pred_rate < self._min_rate * 0.7:
                continue

            carry = compare_carry(
                asset=asset,
                funding_rate_pct=cur_rate * 100,
                mark_px=r["mark_px"],
                pos_size_usd=self._pos_usd,
            )

            strategy = carry["strategy"]
            if strategy == "no_trade":
                continue

            annual_pct = (
                carry["funding_annual_pct"]
                if strategy == "funding"
                else carry["basis_annual_pct"]
            )
            if annual_pct < self._min_annual_pct:
                continue

            # Convert annualized % to per-funding-period bps for scoring.
            edge_bps = annual_pct * _ANNUAL_PCT_TO_PERIOD_BPS

            if not in_window:
                LOGGER.info(
                    "%s evaluate asset=%s annual=%.2f%% edge=%.1fbps "
                    "result=monitor_only (outside_window secs_left=%d)",
                    self.name, asset, annual_pct, edge_bps, secs_left,
                )
                continue

            LOGGER.info(
                "%s evaluate asset=%s annual=%.2f%% edge=%.1fbps "
                "carry_strategy=%s result=opportunity",
                self.name, asset, annual_pct, edge_bps, strategy,
            )

            if edge_bps > best_edge:
                best_edge = edge_bps
                best = PlannedTrade(
                    strategy_name=self.name,
                    exchange="hyperliquid",
                    product_id=f"{asset}/USD:USDC",
                    side="buy",           # primary leg: long spot
                    notional_usd=self._pos_usd,
                    expected_edge_bps=edge_bps,
                    notes=(
                        f"carry={strategy} annual={annual_pct:.2f}% "
                        f"rate={cur_rate*100:.4f}%/hr "
                        f"secs_to_funding={secs_left}"
                    ),
                )

        return best

    def execute(
        self,
        planned: PlannedTrade,
        dry_run: bool = False,
    ) -> ExecutionResult:
        private_key = os.getenv("HL_PRIVATE_KEY", "").strip()
        wallet = os.getenv("HL_WALLET", "").strip()

        if not private_key or not wallet:
            msg = "missing HL_PRIVATE_KEY or HL_WALLET"
            LOGGER.warning("%s execute skipped reason=%s", self.name, msg)
            return ExecutionResult(
                success=False,
                strategy_name=self.name,
                error=msg,
                dry_run=dry_run,
            )

        asset = planned.product_id.split("/")[0]

        try:
            from funding_arb.executor import enter_arb
            result = enter_arb(
                private_key=private_key,
                wallet=wallet,
                asset=asset,
                size_usd=planned.notional_usd,
                dry_run=dry_run,
            )
            LOGGER.info(
                "%s execute asset=%s notional=%.2f dry_run=%s result=%r",
                self.name, asset, planned.notional_usd, dry_run, result,
            )
            return ExecutionResult(
                success=True,
                strategy_name=self.name,
                notional_usd=planned.notional_usd,
                dry_run=dry_run,
            )
        except Exception as exc:
            LOGGER.error("%s execute error=%s", self.name, exc)
            return ExecutionResult(
                success=False,
                strategy_name=self.name,
                error=str(exc),
                dry_run=dry_run,
            )
