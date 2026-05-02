"""CoinbaseSpotEdgeStrategy — wraps existing Coinbase spot execution.

Signal: external edge estimate (from env SPOT_EDGE_BPS or constructor arg).
Gate:   BasisConfig hurdle (round-trip cost + safety margin, default 150 bps).

This is the simplest possible Strategy: a human (or higher-level system)
provides an expected_edge_bps estimate; the strategy gates it against the
fee hurdle and checks balance before returning a PlannedTrade.

Typical use:
  - Direct testing:  CoinbaseSpotEdgeStrategy(signal_edge_bps=200.0)
  - Env-driven:      CoinbaseSpotEdgeStrategy()  # reads SPOT_EDGE_BPS
  - As a building block when another system provides the edge estimate.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from theta.config.basis import BasisConfig
from theta.execution.coinbase import should_trade_spot
from theta.strategies.base import ExecutionResult, PlannedTrade

LOGGER = logging.getLogger("theta.strategies.coinbase_spot")


class CoinbaseSpotEdgeStrategy:
    """Spot buy on Coinbase when an external edge signal clears the fee hurdle."""

    def __init__(
        self,
        config: BasisConfig | None = None,
        asset: str = "ETH",
        quote: str | None = None,
        signal_edge_bps: float | None = None,
        test_notional_usd: float | None = None,
    ) -> None:
        """
        Args:
            config:             BasisConfig (reads from env if None).
            asset:              Base currency to trade (default ETH).
            quote:              Quote currency (defaults to config.default_quote = USD).
            signal_edge_bps:    Override the expected edge in bps.  If None, reads
                                SPOT_EDGE_BPS env var (default 0.0).  Set > hurdle
                                (~150 bps) to generate a trade opportunity.
            test_notional_usd:  Fallback notional when balance is unavailable
                                (useful for dry-run smoke tests without credentials).
                                Only used when the real balance returns 0.
        """
        self._cfg = config or BasisConfig.from_env()
        self._asset = asset.upper()
        self._quote = (quote or self._cfg.default_quote).upper()
        self._signal_edge_bps = signal_edge_bps
        self._test_notional_usd = test_notional_usd

    # ------------------------------------------------------------------
    # Strategy Protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return f"coinbase_spot_{self._asset}_{self._quote}"

    def evaluate_opportunity(self, now: datetime) -> Optional[PlannedTrade]:
        edge_bps = self._resolve_edge_bps()

        # Quick pre-filter before any I/O.
        if edge_bps < self._cfg.hurdle_bps:
            LOGGER.debug(
                "%s evaluate edge=%.1fbps hurdle=%.1fbps result=below_hurdle",
                self.name, edge_bps, self._cfg.hurdle_bps,
            )
            return None

        # Fetch balance (I/O) — determines notional size.
        notional = self._resolve_notional()
        if notional <= 0:
            if self._test_notional_usd and self._test_notional_usd >= self._cfg.min_notional_usd:
                notional = min(self._test_notional_usd, self._cfg.max_notional_usd)
                LOGGER.info(
                    "%s evaluate balance_unavailable — using test_notional=%.2f",
                    self.name, notional,
                )
            else:
                LOGGER.info(
                    "%s evaluate result=no_trade reason=zero_balance_or_client_unavailable",
                    self.name,
                )
                return None

        # Run the fee/risk gate (pure, no I/O).
        trade_ok, reason = should_trade_spot(
            asset=self._asset,
            notional_usd=notional,
            expected_edge_bps=edge_bps,
            config=self._cfg,
        )

        if not trade_ok:
            LOGGER.info(
                "%s evaluate result=blocked reason=%s", self.name, reason,
            )
            return None

        LOGGER.info(
            "%s evaluate result=opportunity notional=%.2f edge=%.1fbps reason=%s",
            self.name, notional, edge_bps, reason,
        )
        return PlannedTrade(
            strategy_name=self.name,
            exchange="coinbase",
            product_id=f"{self._asset}-{self._quote}",
            side="buy",
            notional_usd=notional,
            expected_edge_bps=edge_bps,
            notes=reason,
        )

    def execute(
        self,
        planned: PlannedTrade,
        dry_run: bool = False,
    ) -> ExecutionResult:
        from theta.execution.coinbase import place_market_order, ExecutionError

        try:
            record = place_market_order(
                asset=self._asset,
                side=planned.side,
                notional_usd=planned.notional_usd,
                quote=self._quote,
                expected_edge_bps=planned.expected_edge_bps,
                config=self._cfg,
                dry_run=dry_run,
            )
            return ExecutionResult(
                success=True,
                strategy_name=self.name,
                order_id=record.order_id,
                client_order_id=record.client_order_id,
                notional_usd=record.notional_usd,
                dry_run=dry_run,
            )
        except ExecutionError as exc:
            LOGGER.error("%s execute failed error=%s", self.name, exc)
            return ExecutionResult(
                success=False,
                strategy_name=self.name,
                error=str(exc),
                dry_run=dry_run,
            )
        except Exception as exc:
            LOGGER.error("%s execute unexpected error=%s", self.name, exc)
            return ExecutionResult(
                success=False,
                strategy_name=self.name,
                error=f"unexpected: {exc}",
                dry_run=dry_run,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_edge_bps(self) -> float:
        if self._signal_edge_bps is not None:
            return self._signal_edge_bps
        return float(os.getenv("SPOT_EDGE_BPS", "0.0"))

    def _resolve_notional(self) -> float:
        """Return a trade-sized notional bounded by config limits and available balance."""
        try:
            from theta.marketdata.coinbase import get_quote_balance
            balance = get_quote_balance(self._quote)
        except Exception as exc:
            LOGGER.warning("%s balance_fetch_failed error=%s", self.name, exc)
            return 0.0

        if balance <= 0:
            return 0.0

        # Use the config max as the default trade size, capped by available balance.
        desired = min(self._cfg.max_notional_usd, balance)
        if desired < self._cfg.min_notional_usd:
            return 0.0
        return desired
