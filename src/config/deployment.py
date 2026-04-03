"""Deployment/runtime settings and environment validation for services."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

STRICT_REQUIRED_ENV_VARS = (
    "APP_ENV",
    "DATABASE_URL",
    "WORKER_NAME",
    "PAPER_TRADING",
    "WORKER_ENABLE_TRADING",
    "LIVE_TRADING",
    "CORS_ALLOWED_ORIGINS",
)


def _read_bool(env_name: str, default: bool = False) -> bool:
    """Read a boolean-like env value with a safe default."""
    raw = os.getenv(env_name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_database_url(value: str) -> str:
    """Normalize DB URLs so SQLAlchemy can connect consistently."""
    normalized = value.strip()
    if normalized.startswith("postgres://"):
        return normalized.replace("postgres://", "postgresql+psycopg://", 1)
    if normalized.startswith("postgresql://"):
        return normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return normalized


def _missing_env_vars(env_names: tuple[str, ...]) -> list[str]:
    """Return env variable names that are unset or blank."""
    missing: list[str] = []
    for env_name in env_names:
        raw = os.getenv(env_name)
        if raw is None or raw.strip() == "":
            missing.append(env_name)
    return missing


def _parse_csv_env(value: str) -> tuple[str, ...]:
    """Parse comma-separated env value into a normalized tuple."""
    parsed = [item.strip() for item in value.split(",")]
    return tuple(item for item in parsed if item)


@dataclass(slots=True)
class DeploymentSettings:
    """Settings for web/worker deployment, including safety toggles."""

    app_env: str = "development"
    service_name: str = "theta"
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "sqlite+pysqlite:///data/theta.db"
    strict_env_validation: bool = False
    run_migrations_on_startup: bool = True
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    paper_trading_enabled: bool = False
    worker_enable_trading: bool = False
    worker_name: str = "default-worker"
    worker_poll_seconds: int = 60
    worker_symbol: str = "SPY"
    worker_timeframe: str = "1d"
    worker_strategy: str = "moving_average_crossover"
    worker_strategy_params: dict[str, Any] = field(default_factory=dict)
    worker_order_quantity: float = 1.0
    worker_force_refresh: bool = False

    initial_capital: float = 100_000.0
    max_position_size: float = 0.25
    max_daily_loss: float = 2_000.0
    max_notional_per_trade: float = 100_000.0
    max_open_positions: int = 3
    executor_daily_loss_cap: float = 2_000.0
    trading_start: str = "09:30"
    trading_end: str = "16:00"
    allow_after_hours: bool = False
    kill_switch_on_startup: bool = False

    log_dir: str = "logs"
    cache_dir: str = "data/cache"

    def __post_init__(self) -> None:
        """Validate deployment-level constraints and safety gates."""
        valid_envs = {"development", "test", "staging", "production"}
        if self.app_env not in valid_envs:
            raise ValueError(f"app_env must be one of {sorted(valid_envs)}")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("port must be in [1, 65535]")
        if not self.database_url.strip():
            raise ValueError("database_url cannot be empty")
        if self.worker_poll_seconds < 5:
            raise ValueError("worker_poll_seconds must be at least 5 seconds")
        if self.worker_order_quantity <= 0:
            raise ValueError("worker_order_quantity must be positive")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.max_position_size <= 0:
            raise ValueError("max_position_size must be positive")
        if self.max_daily_loss <= 0:
            raise ValueError("max_daily_loss must be positive")
        if self.max_notional_per_trade <= 0:
            raise ValueError("max_notional_per_trade must be positive")
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        if self.executor_daily_loss_cap <= 0:
            raise ValueError("executor_daily_loss_cap must be positive")
        if not self.cors_allowed_origins:
            raise ValueError("cors_allowed_origins cannot be empty")
        if self.app_env in {"production", "staging"} and any(
            origin == "*" for origin in self.cors_allowed_origins
        ):
            raise ValueError("Wildcard CORS origin is not allowed in production/staging")
        if self.app_env == "production" and self.database_url.startswith("sqlite"):
            raise ValueError("production deployment requires a Postgres DATABASE_URL")

        # Safety gate: active worker trading always requires explicit paper mode.
        if self.worker_enable_trading and not self.paper_trading_enabled:
            raise ValueError(
                "worker_enable_trading requires paper_trading_enabled=true"
            )

        # Hard guard against accidental live trading flags.
        if _read_bool("LIVE_TRADING", default=False):
            raise ValueError("LIVE_TRADING must remain disabled for this repository")

        if self.strict_env_validation or self.app_env == "production":
            self._validate_strict_requirements()

    def _validate_strict_requirements(self) -> None:
        """Validate environment values required for unattended deployment."""
        required = {
            "DATABASE_URL": self.database_url,
            "WORKER_NAME": self.worker_name,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"Missing required environment values: {', '.join(missing)}")

    @classmethod
    def from_env(cls, env_path: str | Path | None = None) -> "DeploymentSettings":
        """Load deployment settings from env vars with safe defaults."""
        if env_path is not None:
            load_dotenv(dotenv_path=Path(env_path), override=False)
        else:
            load_dotenv(override=False)

        strict_env_validation = _read_bool("STRICT_ENV_VALIDATION", default=False)
        app_env = os.getenv("APP_ENV", "development").strip().lower()
        if strict_env_validation or app_env == "production":
            missing = _missing_env_vars(STRICT_REQUIRED_ENV_VARS)
            if missing:
                raise ValueError(
                    "Missing required environment variables for strict/production mode: "
                    + ", ".join(missing)
                )

        strategy_params_raw = os.getenv("WORKER_STRATEGY_PARAMS_JSON", "{}").strip()
        try:
            strategy_params = json.loads(strategy_params_raw)
        except json.JSONDecodeError as exc:
            raise ValueError("WORKER_STRATEGY_PARAMS_JSON must be valid JSON") from exc
        if not isinstance(strategy_params, dict):
            raise ValueError("WORKER_STRATEGY_PARAMS_JSON must decode to an object")

        database_url = _normalize_database_url(
            os.getenv("DATABASE_URL", "sqlite+pysqlite:///data/theta.db")
        )
        cors_allowed_origins = _parse_csv_env(
            os.getenv(
                "CORS_ALLOWED_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            )
        )

        return cls(
            app_env=app_env,
            service_name=os.getenv("SERVICE_NAME", "theta").strip(),
            host=os.getenv("HOST", "0.0.0.0").strip(),
            port=int(os.getenv("PORT", "8000")),
            database_url=database_url,
            strict_env_validation=strict_env_validation,
            run_migrations_on_startup=_read_bool("RUN_MIGRATIONS_ON_STARTUP", default=True),
            cors_allowed_origins=cors_allowed_origins,
            paper_trading_enabled=_read_bool("PAPER_TRADING", default=False),
            worker_enable_trading=_read_bool("WORKER_ENABLE_TRADING", default=False),
            worker_name=os.getenv("WORKER_NAME", "default-worker").strip(),
            worker_poll_seconds=int(os.getenv("WORKER_POLL_SECONDS", "60")),
            worker_symbol=os.getenv("WORKER_SYMBOL", "SPY").strip(),
            worker_timeframe=os.getenv("WORKER_TIMEFRAME", "1d").strip(),
            worker_strategy=os.getenv("WORKER_STRATEGY", "moving_average_crossover").strip(),
            worker_strategy_params=strategy_params,
            worker_order_quantity=float(os.getenv("WORKER_ORDER_QUANTITY", "1.0")),
            worker_force_refresh=_read_bool("WORKER_FORCE_REFRESH", default=False),
            initial_capital=float(os.getenv("INITIAL_CAPITAL", "100000")),
            max_position_size=float(os.getenv("MAX_POSITION_SIZE", "0.25")),
            max_daily_loss=float(os.getenv("MAX_DAILY_LOSS", "2000")),
            max_notional_per_trade=float(os.getenv("MAX_NOTIONAL_PER_TRADE", "100000")),
            max_open_positions=int(os.getenv("MAX_OPEN_POSITIONS", "3")),
            executor_daily_loss_cap=float(os.getenv("EXECUTOR_DAILY_LOSS_CAP", "2000")),
            trading_start=os.getenv("TRADING_START", "09:30").strip(),
            trading_end=os.getenv("TRADING_END", "16:00").strip(),
            allow_after_hours=_read_bool("ALLOW_AFTER_HOURS", default=False),
            kill_switch_on_startup=_read_bool("KILL_SWITCH_ON_STARTUP", default=False),
            log_dir=os.getenv("LOG_DIR", "logs").strip(),
            cache_dir=os.getenv("CACHE_DIR", "data/cache").strip(),
        )
