"""CoinbaseSpotEdgeStrategy — symmetric buy / sell on Coinbase spot.

Signal interpretation (SPOT_EDGE_BPS env var or constructor arg):
  + positive edge ≥  +hurdle  →  BUY  (expect price to rise)
  + negative edge ≤  -hurdle  →  SELL (expect price to fall / reduce position)
  + |edge| < hurdle           →  NO TRADE (no-trade band, reduces over-trading)

Buy sizing:  min(quote_balance, max_notional_usd)
Sell sizing: min(base_balance × mid_price, max_notional_usd)

Inventory cap (SPOT_MAX_LONG_NOTIONAL_USD, default disabled / 0):
  When the USD-equivalent of held ETH exceeds this cap:
    - In the BUY band:       buy is blocked (log max_long_notional_reached)
    - In the NO-TRADE band:  excess is sold down to the cap (cap-driven sell)
  This ensures net long exposure never grows beyond the cap even when the
  edge signal stays positive indefinitely.

Natural hysteresis:
  After a buy the quote balance is depleted → buys stop until USD is
  replenished.  After a sell the base balance is depleted → sells stop
  until ETH is re-acquired.  This prevents rapid alternating round-trips.

Env vars (all optional):
  SPOT_EDGE_BPS              float  default=0.0    signal (positive=buy, negative=sell)
  SPOT_MAX_LONG_NOTIONAL_USD float  default=0.0    cap on long ETH exposure (0 = disabled)
  CB_TAKER_FEE_BPS           float  default=60.0
  MIN_EDGE_BPS               float  default=20.0
  MIN_NOTIONAL_USD           float  default=1.0
  MAX_NOTIONAL_USD           float  default=500.0
  TRADE_LOG_DIR              str    default="logs"

journalctl filter for this strategy:
  journalctl -u theta-runner -f | grep -Ei \
    "coinbase_spot_eth_usd|sell_edge_not_met|base_balance_below_min| \
     sell_submitted|sell_filled|max_long_notional_reached|cap_exceeded"
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
    """Symmetric spot buy/sell on Coinbase with optional inventory cap."""

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
                                SPOT_EDGE_BPS env var (default 0.0).  Positive values
                                trigger a buy; negative values trigger a sell.
                                The magnitude must exceed hurdle_bps (~150 bps) to trade.
            test_notional_usd:  Fallback buy notional when quote balance is zero
                                (useful for dry-run smoke tests without real USD).
                                Only applied for the BUY path.
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
        return f"coinbase_spot_{self._asset}_{self._quote}".lower()

    def evaluate_opportunity(self, now: datetime) -> Optional[PlannedTrade]:
        """Return a PlannedTrade or None.

        Decision priority:
        1. Inventory cap (if SPOT_MAX_LONG_NOTIONAL_USD > 0):
             - BUY band + cap exceeded  → block buy (log max_long_notional_reached)
             - NO-TRADE band + cap exceeded → cap-driven sell (log sell_submitted reason=cap_exceeded)
        2. Edge-driven buy   (SPOT_EDGE_BPS >= +hurdle)
        3. Edge-driven sell  (SPOT_EDGE_BPS <= -hurdle)
        4. No-trade band     (|edge| < hurdle) → None
        """
        edge_bps = self._resolve_edge_bps()
        hurdle = self._cfg.hurdle_bps

        if edge_bps >= hurdle:
            return self._evaluate_buy(edge_bps)
        elif edge_bps <= -hurdle:
            return self._evaluate_sell_edge(abs(edge_bps))
        else:
            # No-trade band: check inventory cap before returning None
            if self._cfg.max_long_notional_usd > 0:
                cap_sell = self._evaluate_cap_sell_if_needed()
                if cap_sell is not None:
                    return cap_sell
            if edge_bps < 0:
                LOGGER.info(
                    "%s sell_edge_not_met edge=%.1fbps hurdle=±%.1fbps "
                    "result=no_trade reason=edge_within_no_trade_band",
                    self.name, edge_bps, hurdle,
                )
            else:
                LOGGER.info(
                    "%s evaluate edge=%.1fbps hurdle=±%.1fbps result=no_trade "
                    "reason=edge_within_no_trade_band",
                    self.name, edge_bps, hurdle,
                )
            return None

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
            if planned.side == "sell" and not dry_run:
                LOGGER.info(
                    "%s sell_filled order_id=%s notional=%.2f",
                    self.name, record.order_id, record.notional_usd,
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
    # Buy evaluation
    # ------------------------------------------------------------------

    def _evaluate_buy(self, edge_bps: float) -> Optional[PlannedTrade]:
        # Check inventory cap before committing to a buy.
        if self._cfg.max_long_notional_usd > 0:
            try:
                from theta.marketdata.coinbase import get_base_balance, get_spot_mid_price
                eth_balance = get_base_balance(self._asset)
                if eth_balance > 0:
                    mid_price = get_spot_mid_price(self._asset, self._quote)
                    eth_notional = eth_balance * mid_price
                    if eth_notional >= self._cfg.max_long_notional_usd:
                        LOGGER.info(
                            "%s max_long_notional_reached eth_balance=%.8f "
                            "mid=%.4f eth_notional=%.2f cap=%.2f — buy blocked",
                            self.name, eth_balance, mid_price, eth_notional,
                            self._cfg.max_long_notional_usd,
                        )
                        return None
            except Exception as exc:
                LOGGER.warning(
                    "%s buy_cap_check_failed error=%s — proceeding without cap check",
                    self.name, exc,
                )

        notional = self._resolve_buy_notional()
        if notional <= 0:
            return None

        trade_ok, reason = should_trade_spot(
            asset=self._asset,
            notional_usd=notional,
            expected_edge_bps=edge_bps,
            config=self._cfg,
        )
        if not trade_ok:
            LOGGER.info("%s evaluate result=buy_blocked reason=%s", self.name, reason)
            return None

        LOGGER.info(
            "%s evaluate result=buy_opportunity notional=%.2f edge=%.1fbps reason=%s",
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

    # ------------------------------------------------------------------
    # Sell evaluation — edge-driven
    # ------------------------------------------------------------------

    def _evaluate_sell_edge(self, abs_edge_bps: float) -> Optional[PlannedTrade]:
        """Sell triggered by a negative edge signal."""
        try:
            from theta.marketdata.coinbase import get_spot_mid_price
            mid_price = get_spot_mid_price(self._asset, self._quote)
        except Exception as exc:
            LOGGER.warning(
                "%s evaluate mid_price_unavailable error=%s — cannot size sell",
                self.name, exc,
            )
            return None

        notional = self._resolve_sell_notional(mid_price)
        if notional <= 0:
            return None

        trade_ok, reason = should_trade_spot(
            asset=self._asset,
            notional_usd=notional,
            expected_edge_bps=abs_edge_bps,
            config=self._cfg,
        )
        if not trade_ok:
            LOGGER.info("%s evaluate result=sell_blocked reason=%s", self.name, reason)
            return None

        LOGGER.info(
            "%s sell_submitted reason=edge_negative notional=%.2f edge=%.1fbps "
            "mid=%.4f net_after_costs=%.1fbps",
            self.name, notional, abs_edge_bps, mid_price,
            abs_edge_bps - self._cfg.round_trip_cost_bps,
        )
        return PlannedTrade(
            strategy_name=self.name,
            exchange="coinbase",
            product_id=f"{self._asset}-{self._quote}",
            side="sell",
            notional_usd=notional,
            expected_edge_bps=abs_edge_bps,
            notes=f"sell_signal mid={mid_price:.4f} {reason}",
        )

    # ------------------------------------------------------------------
    # Sell evaluation — inventory cap-driven
    # ------------------------------------------------------------------

    def _evaluate_cap_sell_if_needed(self) -> Optional[PlannedTrade]:
        """Sell the excess ETH when the position exceeds SPOT_MAX_LONG_NOTIONAL_USD."""
        max_long = self._cfg.max_long_notional_usd
        try:
            from theta.marketdata.coinbase import get_base_balance, get_spot_mid_price
            eth_balance = get_base_balance(self._asset)
            if eth_balance <= 0:
                return None
            mid_price = get_spot_mid_price(self._asset, self._quote)
            if mid_price <= 0:
                return None
        except Exception as exc:
            LOGGER.warning("%s cap_check_failed error=%s", self.name, exc)
            return None

        eth_notional = eth_balance * mid_price
        if eth_notional <= max_long:
            return None

        excess = eth_notional - max_long
        sell_notional = min(excess, self._cfg.max_notional_usd)

        if sell_notional < self._cfg.min_notional_usd:
            LOGGER.info(
                "%s cap_excess_dust eth_balance=%.8f eth_notional=%.2f "
                "cap=%.2f excess=%.4f min_notional=%.2f — no sell",
                self.name, eth_balance, eth_notional, max_long,
                excess, self._cfg.min_notional_usd,
            )
            return None

        LOGGER.info(
            "%s sell_submitted reason=cap_exceeded eth_balance=%.8f mid=%.4f "
            "eth_notional=%.2f cap=%.2f excess=%.2f sell_notional=%.2f",
            self.name, eth_balance, mid_price, eth_notional,
            max_long, excess, sell_notional,
        )
        return PlannedTrade(
            strategy_name=self.name,
            exchange="coinbase",
            product_id=f"{self._asset}-{self._quote}",
            side="sell",
            notional_usd=sell_notional,
            expected_edge_bps=0.0,
            notes=f"cap_sell mid={mid_price:.4f} excess={excess:.2f}",
        )

    # ------------------------------------------------------------------
    # Sizing helpers
    # ------------------------------------------------------------------

    def _resolve_buy_notional(self) -> float:
        """Return USD notional for a buy, bounded by config and available USD balance."""
        try:
            from theta.marketdata.coinbase import get_quote_balance
            balance = get_quote_balance(self._quote)
        except Exception as exc:
            LOGGER.warning("%s buy_balance_fetch_failed error=%s", self.name, exc)
            return 0.0

        if balance <= 0:
            if (
                self._test_notional_usd is not None
                and self._test_notional_usd >= self._cfg.min_notional_usd
            ):
                notional = min(self._test_notional_usd, self._cfg.max_notional_usd)
                LOGGER.info(
                    "%s evaluate balance_unavailable — using test_notional=%.2f",
                    self.name, notional,
                )
                return notional
            LOGGER.info(
                "%s evaluate result=no_trade reason=zero_balance_or_client_unavailable",
                self.name,
            )
            return 0.0

        desired = min(self._cfg.max_notional_usd, balance)
        if desired < self._cfg.min_notional_usd:
            LOGGER.info(
                "%s evaluate result=no_trade reason=balance_below_min "
                "balance=%.8f min=%.2f",
                self.name, balance, self._cfg.min_notional_usd,
            )
            return 0.0
        return desired

    def _resolve_sell_notional(self, mid_price: float) -> float:
        """Return USD-equivalent notional of base asset available to sell."""
        try:
            from theta.marketdata.coinbase import get_base_balance
            base_balance = get_base_balance(self._asset)
        except Exception as exc:
            LOGGER.warning("%s sell_balance_fetch_failed error=%s", self.name, exc)
            return 0.0

        if base_balance <= 0 or mid_price <= 0:
            LOGGER.info(
                "%s evaluate result=no_trade reason=zero_base_balance "
                "base_balance=%.8f mid=%.4f",
                self.name, base_balance, mid_price,
            )
            return 0.0

        base_value_usd = base_balance * mid_price
        bounded = min(base_value_usd, self._cfg.max_notional_usd)

        if bounded < self._cfg.min_notional_usd:
            LOGGER.info(
                "%s base_balance_below_min base_balance=%.8f value_usd=%.4f "
                "min_notional=%.2f result=no_trade",
                self.name, base_balance, base_value_usd, self._cfg.min_notional_usd,
            )
            return 0.0

        LOGGER.info(
            "%s evaluate base_position base_balance=%.8f mid=%.4f "
            "value_usd=%.4f sell_notional=%.2f",
            self.name, base_balance, mid_price, base_value_usd, bounded,
        )
        return bounded

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_edge_bps(self) -> float:
        if self._signal_edge_bps is not None:
            return self._signal_edge_bps
        return float(os.getenv("SPOT_EDGE_BPS", "0.0"))
