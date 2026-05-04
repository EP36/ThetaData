"""CoinbaseSpotEdgeStrategy — symmetric buy / sell on Coinbase spot.

Signal interpretation (SPOT_EDGE_BPS env var or constructor arg):
  + positive edge ≥  +hurdle  →  BUY  (expect price to rise)
  + negative edge ≤  -hurdle  →  SELL (expect price to fall / reduce position)
  + |edge| < hurdle           →  NO TRADE (no-trade band, reduces over-trading)

Inventory cap (SPOT_MAX_LONG_NOTIONAL_USD):
  When ETH position value exceeds the cap, sell the excess automatically,
  regardless of edge direction.  This makes the sell branch reachable even
  when SPOT_EDGE_BPS is a static positive value.  Set to 0 to disable (default).

Buy sizing:  min(quote_balance × (1 − buffer), max_notional_usd)
  A fee/safety buffer (SPOT_BUY_BUFFER_PCT, default 10 %) is applied to the
  live USD balance so the strategy never tries to spend more than Coinbase can
  fill.  This prevents PREVIEW_INSUFFICIENT_FUND rejections at the order layer.

Sell sizing: min(excess_above_cap OR base_balance × mid_price, max_notional_usd)

Insufficient-fund backoff:
  If Coinbase rejects a buy order with PREVIEW_INSUFFICIENT_FUND, an internal
  backoff flag is set.  Subsequent evaluate_opportunity() calls skip the buy
  path and log quote_balance_below_min until the spendable balance rises above
  min_notional_usd, at which point the flag is automatically cleared.

The strategy never sells more than is held, and never places an order whose
USD-equivalent is below min_notional_usd or above max_notional_usd.

Natural hysteresis:
  After a buy, the quote balance is depleted → buys stop until USD is
  replenished.  After a sell, the base balance is depleted → sells stop
  until ETH is re-acquired.  This prevents rapid alternating round-trips.

Env vars (all optional):
  SPOT_EDGE_BPS              float  default=0.0    signal in bps (positive=buy, negative=sell)
  SPOT_MAX_LONG_NOTIONAL_USD float  default=0.0    inventory cap; 0 = disabled
  SPOT_BUY_BUFFER_PCT        float  default=10.0   % of balance to reserve for fees/slippage
  CB_TAKER_FEE_BPS           float  default=60.0
  MIN_EDGE_BPS               float  default=20.0
  MIN_NOTIONAL_USD           float  default=1.0
  MAX_NOTIONAL_USD           float  default=500.0
  TRADE_LOG_DIR              str    default="logs"
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

_PREVIEW_INSUFFICIENT_FUND = "PREVIEW_INSUFFICIENT_FUND"


class CoinbaseSpotEdgeStrategy:
    """Symmetric spot buy/sell on Coinbase when an external edge signal clears the hurdle."""

    def __init__(
        self,
        config: BasisConfig | None = None,
        asset: str = "ETH",
        quote: str | None = None,
        signal_edge_bps: float | None = None,
        test_notional_usd: float | None = None,
        buy_buffer_pct: float | None = None,
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
            buy_buffer_pct:     Percentage of balance to reserve for fees/slippage before
                                sizing a buy.  Overrides SPOT_BUY_BUFFER_PCT env var.
                                Default 10.0 (keep 10 % of balance as cushion).
        """
        self._cfg = config or BasisConfig.from_env()
        self._asset = asset.upper()
        self._quote = (quote or self._cfg.default_quote).upper()
        self._signal_edge_bps = signal_edge_bps
        self._test_notional_usd = test_notional_usd
        pct = buy_buffer_pct if buy_buffer_pct is not None else float(os.getenv("SPOT_BUY_BUFFER_PCT", "10.0"))
        self._buy_buffer_fraction: float = max(0.0, min(pct, 99.0)) / 100.0

        # Backoff state — set by execute() when Coinbase returns PREVIEW_INSUFFICIENT_FUND;
        # cleared by _resolve_buy_notional() once the buffered balance is sufficient again.
        self._buy_backoff: bool = False
        self._last_known_balance: float = 0.0

    # ------------------------------------------------------------------
    # Strategy Protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return f"coinbase_spot_{self._asset}_{self._quote}".lower()

    def evaluate_opportunity(self, now: datetime) -> Optional[PlannedTrade]:
        edge_bps = self._resolve_edge_bps()
        hurdle = self._cfg.hurdle_bps

        # Inventory cap: sell excess ETH regardless of edge direction.
        # Checked first so it fires even when SPOT_EDGE_BPS is static-positive.
        if self._cfg.max_long_notional_usd > 0:
            cap_sell = self._evaluate_cap_sell()
            if cap_sell is not None:
                return cap_sell

        if edge_bps >= hurdle:
            return self._evaluate_buy(edge_bps)
        elif edge_bps <= -hurdle:
            return self._evaluate_sell(abs(edge_bps))
        else:
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

        if planned.side == "sell":
            LOGGER.info(
                "%s sell_submitted product=%s-%s notional=%.2f edge=%.1fbps dry_run=%s",
                self.name, self._asset, self._quote,
                planned.notional_usd, planned.expected_edge_bps, dry_run,
            )

        try:
            record = place_market_order(
                asset=self._asset,
                side=planned.side,
                notional_usd=planned.notional_usd,
                quote=self._quote,
                expected_edge_bps=planned.expected_edge_bps,
                config=self._cfg,
                dry_run=dry_run,
                strategy_name=self.name,
            )
            if planned.side == "sell" and not dry_run:
                LOGGER.info(
                    "%s sell_filled product=%s-%s order_id=%s notional=%.2f",
                    self.name, self._asset, self._quote,
                    record.order_id, record.notional_usd,
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
            err_str = str(exc)
            if planned.side == "buy" and _PREVIEW_INSUFFICIENT_FUND in err_str:
                self._buy_backoff = True
                LOGGER.warning(
                    "%s quote_balance_below_min order_rejected=%s "
                    "buy_backoff=set last_known_balance=%.2f",
                    self.name, _PREVIEW_INSUFFICIENT_FUND, self._last_known_balance,
                )
            LOGGER.error("%s execute failed error=%s", self.name, exc)
            return ExecutionResult(
                success=False,
                strategy_name=self.name,
                error=err_str,
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
    # Internal decision helpers
    # ------------------------------------------------------------------

    def _evaluate_buy(self, edge_bps: float) -> Optional[PlannedTrade]:
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

    def _evaluate_sell(self, abs_edge_bps: float) -> Optional[PlannedTrade]:
        """Evaluate an edge-signal-triggered sell."""
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
            "%s evaluate result=sell_opportunity notional=%.2f edge=%.1fbps "
            "mid=%.4f reason=edge_negative %s",
            self.name, notional, abs_edge_bps, mid_price, reason,
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

    def _evaluate_cap_sell(self) -> Optional[PlannedTrade]:
        """Sell excess ETH when long notional exceeds max_long_notional_usd.

        Fires before edge-based routing so the cap is enforced even when
        SPOT_EDGE_BPS is a static positive value.
        """
        try:
            from theta.marketdata.coinbase import get_base_balance, get_spot_mid_price
            mid_price = get_spot_mid_price(self._asset, self._quote)
            base_balance = get_base_balance(self._asset)
        except Exception as exc:
            LOGGER.warning("%s cap_check_failed error=%s", self.name, exc)
            return None

        if mid_price <= 0 or base_balance <= 0:
            return None

        eth_notional = base_balance * mid_price
        cap = self._cfg.max_long_notional_usd
        if eth_notional <= cap:
            return None

        # Sell only the excess above cap, capped at max_notional_usd per trade.
        excess = eth_notional - cap
        notional = min(excess, self._cfg.max_notional_usd)

        if notional < self._cfg.min_notional_usd:
            LOGGER.info(
                "%s base_balance_below_min base_balance=%.8f value_usd=%.4f "
                "cap=%.2f excess=%.2f min_notional=%.2f result=no_trade",
                self.name, base_balance, eth_notional,
                cap, excess, self._cfg.min_notional_usd,
            )
            return None

        LOGGER.info(
            "%s evaluate result=sell_opportunity notional=%.2f edge=%.1fbps "
            "reason=cap_exceeded eth_notional=%.2f cap=%.2f mid=%.4f",
            self.name, notional, self._cfg.hurdle_bps,
            eth_notional, cap, mid_price,
        )
        return PlannedTrade(
            strategy_name=self.name,
            exchange="coinbase",
            product_id=f"{self._asset}-{self._quote}",
            side="sell",
            notional_usd=notional,
            expected_edge_bps=self._cfg.hurdle_bps,
            notes=f"cap_sell eth_notional={eth_notional:.2f} cap={cap:.2f} mid={mid_price:.4f}",
        )

    def _resolve_buy_notional(self) -> float:
        """Return trade-sized notional for a buy, bounded by buffered USD balance.

        Applies _buy_buffer_fraction to the live balance so the strategy never
        asks Coinbase to spend more than is available after fees.  Also enforces
        the PREVIEW_INSUFFICIENT_FUND backoff: while the flag is set the method
        returns 0 and logs quote_balance_below_min; it self-clears once the
        spendable balance rises above min_notional_usd.
        """
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

        self._last_known_balance = balance

        # Reserve a buffer fraction so the notional never exceeds what Coinbase
        # can fill after taker fees and slippage.
        spendable = balance * (1.0 - self._buy_buffer_fraction)

        # If the insufficient-fund backoff is active, keep blocking until the
        # spendable balance is high enough for at least a minimum order.
        if self._buy_backoff:
            if spendable < self._cfg.min_notional_usd:
                LOGGER.info(
                    "%s quote_balance_below_min balance=%.2f spendable=%.2f "
                    "min_notional=%.2f result=no_trade reason=insufficient_fund_backoff",
                    self.name, balance, spendable, self._cfg.min_notional_usd,
                )
                return 0.0
            # Balance has recovered — clear the backoff and proceed.
            LOGGER.info(
                "%s buy_backoff_cleared balance=%.2f spendable=%.2f",
                self.name, balance, spendable,
            )
            self._buy_backoff = False

        desired = min(self._cfg.max_notional_usd, spendable)
        if desired < self._cfg.min_notional_usd:
            LOGGER.info(
                "%s quote_balance_below_min balance=%.2f spendable=%.2f "
                "min_notional=%.2f result=no_trade reason=balance_below_min",
                self.name, balance, spendable, self._cfg.min_notional_usd,
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
