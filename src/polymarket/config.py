"""Polymarket CLOB scanner configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


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
    max_trade_usdc: float = 500.0      # max USDC per trade
    max_positions: int = 5             # max concurrent open positions
    daily_loss_limit: float = 200.0    # stop trading if daily P&L < -limit
    dry_run: bool = True               # True = log intent only, never place orders
    min_volume_24h: float = 10_000.0   # minimum 24h USDC volume to trade a market
    positions_path: str = "data/polymarket_positions.json"

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
            dry_run=_bool("POLY_DRY_RUN", default=True),
            min_volume_24h=float(os.getenv("POLY_MIN_VOLUME_24H", "10000.0")),
            positions_path=os.getenv(
                "POLY_POSITIONS_PATH", "data/polymarket_positions.json"
            ),
        )
