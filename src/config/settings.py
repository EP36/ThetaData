"""Runtime settings loaded from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    """Container for configurable runtime parameters."""

    data_api_key: str
    broker_api_key: str
    broker_api_secret: str
    initial_capital: float
    position_size_pct: float
    fixed_fee: float
    slippage_pct: float
    stop_loss_pct: float | None
    take_profit_pct: float | None
    max_position_size: float
    max_daily_loss: float
    paper_trading_enabled: bool
    max_notional_per_trade: float
    executor_max_open_positions: int
    executor_daily_loss_cap: float
    trade_log_path: str

    def __post_init__(self) -> None:
        """Validate runtime settings."""
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.position_size_pct <= 0 or self.position_size_pct > 1:
            raise ValueError("position_size_pct must be in (0, 1]")
        if self.fixed_fee < 0:
            raise ValueError("fixed_fee cannot be negative")
        if self.slippage_pct < 0 or self.slippage_pct >= 1:
            raise ValueError("slippage_pct must be in [0, 1)")
        if self.stop_loss_pct is not None and (
            self.stop_loss_pct <= 0 or self.stop_loss_pct >= 1
        ):
            raise ValueError("stop_loss_pct must be in (0, 1)")
        if self.take_profit_pct is not None and self.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be positive")
        if self.max_position_size <= 0:
            raise ValueError("max_position_size must be positive")
        if self.max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")
        if self.max_notional_per_trade <= 0:
            raise ValueError("max_notional_per_trade must be positive")
        if self.executor_max_open_positions <= 0:
            raise ValueError("executor_max_open_positions must be positive")
        if self.executor_daily_loss_cap <= 0:
            raise ValueError("executor_daily_loss_cap must be positive")
        if not self.trade_log_path.strip():
            raise ValueError("trade_log_path cannot be empty")

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "Settings":
        """Build settings from environment variables.

        Args:
            env_path: Optional custom `.env` path.

        Returns:
            Settings object with environment-driven values.
        """
        def read_optional_float(env_name: str) -> float | None:
            raw = os.getenv(env_name, "").strip()
            return None if raw == "" else float(raw)

        def read_bool(env_name: str, default: bool = False) -> bool:
            raw = os.getenv(env_name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        if env_path is not None:
            load_dotenv(dotenv_path=Path(env_path), override=False)
        else:
            load_dotenv(override=False)

        return cls(
            data_api_key=os.getenv("DATA_API_KEY", ""),
            broker_api_key=os.getenv("BROKER_API_KEY", ""),
            broker_api_secret=os.getenv("BROKER_API_SECRET", ""),
            initial_capital=float(os.getenv("INITIAL_CAPITAL", "100000")),
            position_size_pct=float(os.getenv("POSITION_SIZE_PCT", "1.0")),
            fixed_fee=float(os.getenv("FIXED_FEE", "1.0")),
            slippage_pct=float(os.getenv("SLIPPAGE_PCT", "0.0005")),
            stop_loss_pct=read_optional_float("STOP_LOSS_PCT"),
            take_profit_pct=read_optional_float("TAKE_PROFIT_PCT"),
            max_position_size=float(os.getenv("MAX_POSITION_SIZE", "1.0")),
            max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "2000")),
            paper_trading_enabled=read_bool("PAPER_TRADING", default=False),
            max_notional_per_trade=float(os.getenv("MAX_NOTIONAL_PER_TRADE", "100000")),
            executor_max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "10")),
            executor_daily_loss_cap=float(os.getenv("EXECUTOR_DAILY_LOSS_CAP", "2000")),
            trade_log_path=os.getenv("TRADE_LOG_PATH", "logs/trades.csv"),
        )
