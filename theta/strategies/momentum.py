"""SimpleMomentumStrategy — fast/slow SMA crossover on Coinbase 5-minute candles.

Signal:
  - Fetch the last SLOW_BARS × 5-minute candles for the product.
  - fast_avg = mean of the last FAST_BARS close prices
  - slow_avg = mean of all SLOW_BARS close prices
  - momentum_bps = (fast_avg / slow_avg - 1) × 10 000
  - Buy when momentum_bps > 0  AND  expected_edge_bps > hurdle.
  - No short selling (spot-only).

Edge estimate:
  expected_edge_bps = momentum_bps × continuation_factor − round_trip_cost
  default continuation_factor = 0.30 (assume 30% of momentum continues)

With default round-trip cost ~130 bps:
  Trade requires momentum_bps > 130 / 0.30 ≈ 433 bps  (a ~4% 25-min move).

This is intentionally conservative — momentum trades fire only during clear
trending conditions.  Tune MOMENTUM_CONTINUATION_FACTOR and fast/slow bars
via env vars or constructor args.

Env vars (all optional):
  MOMENTUM_FAST_BARS          int    default=3  (bars in fast window)
  MOMENTUM_SLOW_BARS          int    default=10 (bars in slow window)
  MOMENTUM_CONTINUATION_FACTOR float default=0.30
  MOMENTUM_PRODUCT            str    default=ETH-USD
  MOMENTUM_NOTIONAL_USD       float  default=10.0
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from theta.config.basis import BasisConfig
from theta.execution.coinbase import should_trade_spot
from theta.strategies.base import ExecutionResult, PlannedTrade

LOGGER = logging.getLogger("theta.strategies.momentum")


def _read_env_float(key: str, default: float) -> float:
    import os
    raw = __import__("os").getenv(key)
    return float(raw) if raw else default


def _read_env_int(key: str, default: int) -> int:
    import os
    raw = __import__("os").getenv(key)
    return int(raw) if raw else default


class SimpleMomentumStrategy:
    """Long-only SMA crossover on Coinbase 5-minute candles.

    Uses the public (no-auth) candles endpoint so it works even if Coinbase
    credentials are missing; only execute() requires auth.
    """

    def __init__(
        self,
        config: BasisConfig | None = None,
        product_id: str | None = None,
        fast_bars: int | None = None,
        slow_bars: int | None = None,
        continuation_factor: float | None = None,
        notional_usd: float | None = None,
    ) -> None:
        self._cfg = config or BasisConfig.from_env()
        self._product_id = (
            product_id
            or __import__("os").getenv("MOMENTUM_PRODUCT", "ETH-USD")
        )
        self._fast_bars = fast_bars or _read_env_int("MOMENTUM_FAST_BARS", 3)
        self._slow_bars = slow_bars or _read_env_int("MOMENTUM_SLOW_BARS", 10)
        self._continuation_factor = (
            continuation_factor
            or _read_env_float("MOMENTUM_CONTINUATION_FACTOR", 0.30)
        )
        self._notional_usd = (
            notional_usd
            or _read_env_float("MOMENTUM_NOTIONAL_USD", 10.0)
        )
        # Derived fields from product_id
        parts = self._product_id.split("-", 1)
        self._asset = parts[0].upper()
        self._quote = parts[1].upper() if len(parts) > 1 else self._cfg.default_quote

    # ------------------------------------------------------------------
    # Strategy Protocol
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return f"momentum_{self._product_id.lower().replace('-', '_')}"

    def evaluate_opportunity(self, now: datetime) -> Optional[PlannedTrade]:
        closes = self._fetch_closes()
        if len(closes) < self._slow_bars:
            LOGGER.info(
                "%s evaluate result=no_data bars_fetched=%d needed=%d",
                self.name, len(closes), self._slow_bars,
            )
            return None

        fast_avg = sum(closes[-self._fast_bars:]) / self._fast_bars
        slow_avg = sum(closes) / len(closes)

        if slow_avg <= 0:
            return None

        momentum_bps = (fast_avg / slow_avg - 1.0) * 10_000.0
        expected_edge_bps = (
            momentum_bps * self._continuation_factor
            - self._cfg.round_trip_cost_bps
        )

        LOGGER.info(
            "%s evaluate fast_avg=%.4f slow_avg=%.4f "
            "momentum=%.1fbps continuation_factor=%.2f "
            "expected_edge=%.1fbps hurdle=%.1fbps",
            self.name, fast_avg, slow_avg,
            momentum_bps, self._continuation_factor,
            expected_edge_bps, self._cfg.hurdle_bps,
        )

        # Only buy on positive momentum that clears the hurdle.
        if momentum_bps <= 0 or expected_edge_bps < self._cfg.hurdle_bps:
            LOGGER.info(
                "%s evaluate result=no_trade "
                "momentum=%.1fbps expected_edge=%.1fbps hurdle=%.1fbps",
                self.name, momentum_bps, expected_edge_bps, self._cfg.hurdle_bps,
            )
            return None

        # Fee/risk gate (pure, no I/O).
        notional = min(self._notional_usd, self._cfg.max_notional_usd)
        trade_ok, reason = should_trade_spot(
            asset=self._asset,
            notional_usd=notional,
            expected_edge_bps=expected_edge_bps,
            config=self._cfg,
        )
        if not trade_ok:
            LOGGER.info("%s evaluate result=blocked reason=%s", self.name, reason)
            return None

        notes = (
            f"momentum={momentum_bps:.1f}bps fast={fast_avg:.4f} "
            f"slow={slow_avg:.4f} continuation={self._continuation_factor}"
        )
        LOGGER.info(
            "%s evaluate result=opportunity notional=%.2f "
            "edge=%.1fbps %s",
            self.name, notional, expected_edge_bps, notes,
        )
        return PlannedTrade(
            strategy_name=self.name,
            exchange="coinbase",
            product_id=self._product_id,
            side="buy",
            notional_usd=notional,
            expected_edge_bps=expected_edge_bps,
            notes=notes,
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
    # Helpers
    # ------------------------------------------------------------------

    def _fetch_closes(self) -> list[float]:
        """Fetch recent 5-minute close prices via the public candles endpoint."""
        try:
            from funding_arb.coinbase_client import get_coinbase_client
            cb = get_coinbase_client()
            if cb is None:
                return self._fetch_closes_public()
            return self._fetch_closes_authenticated(cb)
        except Exception:
            return self._fetch_closes_public()

    def _fetch_closes_authenticated(self, cb) -> list[float]:
        now_ts = int(time.time())
        # Fetch slow_bars + 2 extra to ensure we have enough after any gaps.
        start_ts = now_ts - (self._slow_bars + 2) * 300  # 5-min candles
        try:
            resp = cb.get_candles(
                product_id=self._product_id,
                start=str(start_ts),
                end=str(now_ts),
                granularity="FIVE_MINUTE",
                limit=self._slow_bars + 2,
            )
            return _extract_closes(resp)
        except Exception as exc:
            LOGGER.debug(
                "%s candles_auth_failed error=%s — trying public endpoint",
                self.name, exc,
            )
            return self._fetch_closes_public()

    def _fetch_closes_public(self) -> list[float]:
        now_ts = int(time.time())
        start_ts = now_ts - (self._slow_bars + 2) * 300
        try:
            from funding_arb.coinbase_client import get_coinbase_client
            cb = get_coinbase_client()
            if cb is None:
                # No client at all — use httpx directly against the public endpoint.
                return self._fetch_closes_httpx(start_ts, now_ts)
            resp = cb.get_public_candles(
                product_id=self._product_id,
                start=str(start_ts),
                end=str(now_ts),
                granularity="FIVE_MINUTE",
                limit=self._slow_bars + 2,
            )
            return _extract_closes(resp)
        except Exception as exc:
            LOGGER.warning(
                "%s public_candles_failed product=%s error=%s",
                self.name, self._product_id, exc,
            )
            return []

    def _fetch_closes_httpx(self, start_ts: int, end_ts: int) -> list[float]:
        """Fallback: call the public REST endpoint directly without SDK."""
        try:
            import httpx
            url = (
                "https://api.coinbase.com/api/v3/brokerage/market/products"
                f"/{self._product_id}/candles"
            )
            params = {
                "start": str(start_ts),
                "end": str(end_ts),
                "granularity": "FIVE_MINUTE",
                "limit": str(self._slow_bars + 2),
            }
            resp = httpx.get(url, params=params, timeout=8.0)
            resp.raise_for_status()
            data = resp.json()
            candles = data.get("candles", [])
            closes = []
            for c in candles:
                try:
                    closes.append(float(c.get("close", 0) or 0))
                except (TypeError, ValueError):
                    pass
            closes = [c for c in closes if c > 0]
            closes.reverse()  # chronological order
            return closes[-self._slow_bars:]
        except Exception as exc:
            LOGGER.warning(
                "%s httpx_candles_failed product=%s error=%s",
                self.name, self._product_id, exc,
            )
            return []


def _extract_closes(resp) -> list[float]:
    """Extract close prices from a GetProductCandlesResponse or plain dict."""
    if isinstance(resp, dict):
        candles = resp.get("candles", [])
    else:
        candles = getattr(resp, "candles", None) or []

    closes = []
    for c in candles:
        if isinstance(c, dict):
            val = c.get("close") or c.get("Close")
        else:
            val = getattr(c, "close", None)
        try:
            closes.append(float(val))
        except (TypeError, ValueError):
            pass

    closes = [c for c in closes if c > 0]
    # Coinbase returns candles newest-first; reverse to chronological.
    closes.reverse()
    return closes
