"""Polymarket CLOB scanner configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.config.alpaca import read_alpaca_api_key, read_alpaca_api_secret

SUPPORTED_SIGNAL_PROVIDERS = ("alpaca", "synthetic")
SUPPORTED_POLY_TRADING_MODES = ("disabled", "dry_run", "live")
SUPPORTED_ALPACA_TRADING_MODES = ("disabled", "paper", "live")


def _normalize_signal_provider(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"", "none"}:
        return "synthetic"
    return normalized


def _normalize_trading_venue(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "equities":
        return "alpaca"
    return normalized


@dataclass(slots=True)
class PolymarketConfig:
    """Configuration for the Polymarket CLOB API connection and arb scanner."""

    api_key: str
    api_secret: str
    passphrase: str
    private_key: str
    scan_interval_sec: int
    min_edge_pct: float
    clob_base_url: str
    kalshi_base_url: str
    max_retries: int
    timeout_seconds: float
    # --- Phase 2: execution controls ---
    max_trade_usdc: float = 20.0       # max USDC per trade (override with POLY_MAX_TRADE_USDC)
    max_positions: int = 5             # max concurrent open positions
    daily_loss_limit: float = 200.0    # stop trading if daily P&L < -limit
    dry_run: bool = True               # True = log intent only, never place orders
    trading_mode: str = "dry_run"      # deployment-level mode: dry_run | live
    trading_venue: str = "polymarket"  # must be polymarket for live execution
    live_trading_enabled: bool = False # explicit global live opt-in
    signal_provider: str = "synthetic" # BTC signal source; independent of venue
    alpaca_trading_mode: str = "disabled"
    poly_trading_mode: str = "dry_run"
    min_volume_24h: float = 10_000.0   # minimum 24h USDC volume to trade a market
    positions_path: str = "data/polymarket_positions.json"
    # --- Phase 3: position monitoring ---
    monitor_interval_sec: int = 60     # how often to run monitor_positions()
    take_profit_pct: float = 15.0      # close when unrealized P&L >= this %
    stop_loss_pct: float = 10.0        # close when unrealized P&L <= -this %
    max_hold_hours: int = 72           # force-close after this many hours
    unhedged_grace_minutes: int = 5    # attempt close of unhedged leg after this many minutes
    poly_log_dir: str = "logs"         # directory for poly_YYYY-MM-DD.log daily summaries

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("POLY_API_KEY is required")
        if not self.api_secret.strip():
            raise ValueError("POLY_API_SECRET is required")
        if not self.passphrase.strip():
            raise ValueError("POLY_PASSPHRASE is required")
        if not self.private_key.strip():
            raise ValueError("POLY_PRIVATE_KEY is required")
        if self.scan_interval_sec <= 0:
            raise ValueError("scan_interval_sec must be positive")
        if self.min_edge_pct <= 0:
            raise ValueError("min_edge_pct must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_trade_usdc <= 0:
            raise ValueError("max_trade_usdc must be positive")
        if self.max_positions <= 0:
            raise ValueError("max_positions must be positive")
        if self.daily_loss_limit <= 0:
            raise ValueError("daily_loss_limit must be positive")
        if self.monitor_interval_sec <= 0:
            raise ValueError("monitor_interval_sec must be positive")
        if self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive")
        if self.stop_loss_pct <= 0:
            raise ValueError("stop_loss_pct must be positive")
        if self.max_hold_hours <= 0:
            raise ValueError("max_hold_hours must be positive")
        if self.unhedged_grace_minutes < 0:
            raise ValueError("unhedged_grace_minutes must be non-negative")
        self.trading_mode = self.trading_mode.strip().lower()
        self.trading_venue = _normalize_trading_venue(self.trading_venue)
        self.signal_provider = _normalize_signal_provider(self.signal_provider)
        self.alpaca_trading_mode = self.alpaca_trading_mode.strip().lower()
        self.poly_trading_mode = self.poly_trading_mode.strip().lower()
        if self.signal_provider not in SUPPORTED_SIGNAL_PROVIDERS:
            raise ValueError(
                "signal_provider must be one of "
                f"{list(SUPPORTED_SIGNAL_PROVIDERS)}"
            )
        if self.alpaca_trading_mode not in SUPPORTED_ALPACA_TRADING_MODES:
            raise ValueError(
                "alpaca_trading_mode must be one of "
                f"{list(SUPPORTED_ALPACA_TRADING_MODES)}"
            )
        if self.poly_trading_mode not in SUPPORTED_POLY_TRADING_MODES:
            raise ValueError(
                "poly_trading_mode must be one of "
                f"{list(SUPPORTED_POLY_TRADING_MODES)}"
            )
        if self.trading_venue != "polymarket" and self.poly_trading_mode != "disabled":
            raise ValueError("POLY_TRADING_MODE requires TRADING_VENUE=polymarket")
        if self.alpaca_trading_mode != "disabled":
            raise ValueError(
                "ALPACA_TRADING_MODE must be disabled for Polymarket execution"
            )
        if not self.dry_run and self.poly_trading_mode != "live":
            raise ValueError("POLY_DRY_RUN=false requires POLY_TRADING_MODE=live")
        if self.poly_trading_mode == "live":
            if self.trading_mode != "live":
                raise ValueError("POLY_TRADING_MODE=live requires TRADING_MODE=live")
            if self.trading_venue != "polymarket":
                raise ValueError("POLY_TRADING_MODE=live requires TRADING_VENUE=polymarket")
            if not self.live_trading_enabled:
                raise ValueError("POLY_TRADING_MODE=live requires LIVE_TRADING=true")
            if self.dry_run:
                raise ValueError("POLY_TRADING_MODE=live requires POLY_DRY_RUN=false")
            if (
                self.signal_provider == "alpaca"
                and (not read_alpaca_api_key() or not read_alpaca_api_secret())
            ):
                raise ValueError(
                    "SIGNAL_PROVIDER=alpaca requires ALPACA_API_KEY and "
                    "ALPACA_API_SECRET for live Polymarket trading"
                )

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "PolymarketConfig":
        """Load configuration from environment variables."""
        if env_path:
            load_dotenv(dotenv_path=Path(env_path), override=False)
        else:
            load_dotenv(override=False)

        def _bool(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        dry_run = _bool("POLY_DRY_RUN", default=True)
        poly_trading_mode = os.getenv("POLY_TRADING_MODE", "").strip().lower()
        if not poly_trading_mode:
            poly_trading_mode = "dry_run" if dry_run else "live"
        trading_mode = os.getenv("TRADING_MODE", "").strip().lower()
        if not trading_mode:
            trading_mode = "live" if poly_trading_mode == "live" else poly_trading_mode
        live_trading_enabled = _bool(
            "LIVE_TRADING",
            default=poly_trading_mode == "live",
        )

        return cls(
            api_key=os.getenv("POLY_API_KEY", ""),
            api_secret=os.getenv("POLY_API_SECRET", ""),
            passphrase=os.getenv("POLY_PASSPHRASE", ""),
            private_key=os.getenv("POLY_PRIVATE_KEY", ""),
            scan_interval_sec=int(os.getenv("POLY_SCAN_INTERVAL_SEC", "30")),
            min_edge_pct=float(os.getenv("POLY_MIN_EDGE_PCT", "1.5")),
            clob_base_url=os.getenv("POLY_CLOB_BASE_URL", "https://clob.polymarket.com"),
            kalshi_base_url=os.getenv(
                "KALSHI_BASE_URL", "https://trading-api.kalshi.com/trade-api/v2"
            ),
            max_retries=int(os.getenv("POLY_MAX_RETRIES", "3")),
            timeout_seconds=float(os.getenv("POLY_TIMEOUT_SECONDS", "15.0")),
            max_trade_usdc=float(os.getenv("POLY_MAX_TRADE_USDC", "500.0")),
            max_positions=int(os.getenv("POLY_MAX_POSITIONS", "5")),
            daily_loss_limit=float(os.getenv("POLY_DAILY_LOSS_LIMIT", "200.0")),
            dry_run=dry_run,
            trading_mode=trading_mode,
            trading_venue=os.getenv("TRADING_VENUE", "polymarket"),
            live_trading_enabled=live_trading_enabled,
            signal_provider=os.getenv("SIGNAL_PROVIDER", "synthetic"),
            alpaca_trading_mode=os.getenv("ALPACA_TRADING_MODE", "disabled"),
            poly_trading_mode=poly_trading_mode,
            min_volume_24h=float(os.getenv("POLY_MIN_VOLUME_24H", "10000.0")),
            positions_path=os.getenv(
                "POLY_POSITIONS_PATH", "data/polymarket_positions.json"
            ),
            monitor_interval_sec=int(os.getenv("POLY_MONITOR_INTERVAL_SEC", "60")),
            take_profit_pct=float(os.getenv("POLY_TAKE_PROFIT_PCT", "15.0")),
            stop_loss_pct=float(os.getenv("POLY_STOP_LOSS_PCT", "10.0")),
            max_hold_hours=int(os.getenv("POLY_MAX_HOLD_HOURS", "72")),
            unhedged_grace_minutes=int(os.getenv("POLY_UNHEDGED_GRACE_MINUTES", "5")),
            poly_log_dir=os.getenv("POLY_LOG_DIR", "logs"),
        )
