"""Typed configuration for Coinbase spot basis trading.

All parameters have production-safe defaults and can be overridden via
environment variables (see from_env()).  The library itself never reads
/etc/trauto/env — that belongs to the script layer.

Usage:
    cfg = BasisConfig.from_env()          # override from os.environ
    cfg = BasisConfig(min_edge_bps=30.0)  # inline override for tests
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Coinbase Advanced Trade fee schedule (taker, < $10k/mo volume)
# https://help.coinbase.com/en/advanced-trade/trading-and-funding/fees
# ---------------------------------------------------------------------------
_CB_TAKER_FEE_BPS_DEFAULT   = 60.0   # 0.60 %
_CB_SLIPPAGE_BUFFER_BPS_DEFAULT = 5.0  # 0.05 % estimated market impact
_MIN_EDGE_BPS_DEFAULT        = 20.0   # 0.20 % safety margin above costs


@dataclass
class BasisConfig:
    """All trading parameters in one place.

    Attributes:
        cb_taker_fee_bps:       Coinbase taker fee in basis points (1 bps = 0.01 %).
        slippage_buffer_bps:    Estimated market-impact per side in bps.
        min_edge_bps:           Additional alpha required above round-trip cost.
        min_notional_usd:       Hard lower bound on per-trade notional.
        max_notional_usd:       Hard upper bound on per-trade notional.
        max_daily_notional_usd: Rolling daily notional budget.
        max_risk_pct_per_trade: Max % of estimated portfolio per trade.
        default_quote:          Default quote currency for product IDs.
        log_dir:                Directory for trade telemetry files.
    """
    cb_taker_fee_bps:       float = _CB_TAKER_FEE_BPS_DEFAULT
    slippage_buffer_bps:    float = _CB_SLIPPAGE_BUFFER_BPS_DEFAULT
    min_edge_bps:           float = _MIN_EDGE_BPS_DEFAULT
    min_notional_usd:       float = 1.0
    max_notional_usd:       float = 500.0
    max_daily_notional_usd: float = 2_000.0
    max_risk_pct_per_trade: float = 1.0     # % of portfolio
    default_quote:          str   = "USD"
    log_dir:                str   = "logs"

    # ---------- derived quantities ----------

    @property
    def one_way_cost_bps(self) -> float:
        """Total cost of one leg: fee + slippage."""
        return self.cb_taker_fee_bps + self.slippage_buffer_bps

    @property
    def round_trip_cost_bps(self) -> float:
        """Total cost to enter AND exit a position."""
        return 2.0 * self.one_way_cost_bps

    @property
    def hurdle_bps(self) -> float:
        """Minimum expected edge to approve a trade (costs + margin)."""
        return self.round_trip_cost_bps + self.min_edge_bps

    # ---------- loader ----------

    @classmethod
    def from_env(cls) -> "BasisConfig":
        """Build config from environment variables, using dataclass defaults as fallback.

        Env vars (all optional):
            CB_TAKER_FEE_BPS, CB_SLIPPAGE_BUFFER_BPS, MIN_EDGE_BPS
            MIN_NOTIONAL_USD, MAX_NOTIONAL_USD
            MAX_DAILY_NOTIONAL_USD, MAX_RISK_PCT_PER_TRADE
            DEFAULT_QUOTE, TRADE_LOG_DIR
        """
        def _f(name: str, default: float) -> float:
            raw = os.getenv(name)
            return float(raw) if raw is not None else default

        def _s(name: str, default: str) -> str:
            return os.getenv(name, default)

        return cls(
            cb_taker_fee_bps=_f("CB_TAKER_FEE_BPS",       _CB_TAKER_FEE_BPS_DEFAULT),
            slippage_buffer_bps=_f("CB_SLIPPAGE_BUFFER_BPS", _CB_SLIPPAGE_BUFFER_BPS_DEFAULT),
            min_edge_bps=_f("MIN_EDGE_BPS",                _MIN_EDGE_BPS_DEFAULT),
            min_notional_usd=_f("MIN_NOTIONAL_USD",        1.0),
            max_notional_usd=_f("MAX_NOTIONAL_USD",        500.0),
            max_daily_notional_usd=_f("MAX_DAILY_NOTIONAL_USD", 2_000.0),
            max_risk_pct_per_trade=_f("MAX_RISK_PCT_PER_TRADE", 1.0),
            default_quote=_s("DEFAULT_QUOTE",              "USD"),
            log_dir=_s("TRADE_LOG_DIR",                    "logs"),
        )
