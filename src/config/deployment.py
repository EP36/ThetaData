"""Deployment/runtime settings and environment validation for services."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.config.alpaca import (
    read_alpaca_api_key,
    read_alpaca_api_secret,
    read_alpaca_execution_base_url,
)

SUPPORTED_WORKER_UNIVERSE_MODES = (
    "static",
    "top_gainers",
    "top_losers",
    "high_relative_volume",
    "index_constituents",
)

STRICT_REQUIRED_ENV_VARS = (
    "APP_ENV",
    "DATABASE_URL",
    "WORKER_NAME",
    "PAPER_TRADING",
    "WORKER_ENABLE_TRADING",
    "LIVE_TRADING",
    "CORS_ALLOWED_ORIGINS",
    "AUTH_SESSION_SECRET",
    "AUTH_PASSWORD_PEPPER",
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


def _normalize_symbols(symbols: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize symbol tuples to uppercase, non-empty, de-duplicated values."""
    normalized: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        cleaned = symbol.strip().upper()
        if not cleaned or cleaned in seen:
            continue
        normalized.append(cleaned)
        seen.add(cleaned)
    return tuple(normalized)


@dataclass(slots=True)
class DeploymentSettings:
    """Settings for web/worker deployment, including safety toggles."""

    app_env: str = "development"
    service_name: str = "trauto"
    host: str = "0.0.0.0"
    port: int = 8000
    database_url: str = "sqlite+pysqlite:///data/trauto.db"
    strict_env_validation: bool = False
    run_migrations_on_startup: bool = True
    cors_allowed_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )
    auth_enabled: bool = True
    auth_session_secret: str = "dev-insecure-auth-session-secret-change-me"
    auth_password_pepper: str = "dev-insecure-auth-password-pepper-change-me"
    auth_session_ttl_minutes: int = 720
    auth_login_max_attempts: int = 5
    auth_login_window_seconds: int = 900
    auth_login_block_seconds: int = 900
    auth_bootstrap_admin_on_startup: bool = False
    auth_bootstrap_admin_email: str = ""
    auth_bootstrap_admin_password: str = ""

    paper_trading_enabled: bool = False
    worker_enable_trading: bool = False
    worker_name: str = "default-worker"
    worker_poll_seconds: int = 60
    worker_symbol: str = "SPY"
    worker_symbols: tuple[str, ...] = ("SPY",)
    worker_timeframe: str = "1d"
    worker_strategy: str = "moving_average_crossover"
    worker_strategy_params: dict[str, Any] = field(default_factory=dict)
    worker_order_quantity: float = 1.0
    worker_force_refresh: bool = False
    worker_dry_run: bool = True
    worker_allow_multi_strategy_per_symbol: bool = False
    worker_universe_mode: str = "static"
    worker_max_candidates: int = 10
    selection_min_recent_trades: int = 5
    worker_startup_warmup_cycles: int = 20
    min_price: float = 1.0
    min_avg_volume: float = 100_000.0
    min_relative_volume: float = 0.0
    max_spread_pct: float = 1.0

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

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

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
        self.worker_symbols = _normalize_symbols(self.worker_symbols)
        if not self.worker_symbols:
            raise ValueError("worker_symbols cannot be empty")
        self.worker_symbol = self.worker_symbol.strip().upper()
        if not self.worker_symbol:
            self.worker_symbol = self.worker_symbols[0]
        if self.worker_symbol not in self.worker_symbols:
            self.worker_symbol = self.worker_symbols[0]
        if self.worker_order_quantity <= 0:
            raise ValueError("worker_order_quantity must be positive")
        if self.worker_universe_mode not in SUPPORTED_WORKER_UNIVERSE_MODES:
            raise ValueError(
                "worker_universe_mode must be one of "
                f"{list(SUPPORTED_WORKER_UNIVERSE_MODES)}"
            )
        if self.worker_max_candidates <= 0:
            raise ValueError("worker_max_candidates must be positive")
        if self.selection_min_recent_trades < 0:
            raise ValueError("selection_min_recent_trades cannot be negative")
        if self.worker_startup_warmup_cycles < 0:
            raise ValueError("worker_startup_warmup_cycles cannot be negative")
        if self.min_price < 0:
            raise ValueError("min_price cannot be negative")
        if self.min_avg_volume < 0:
            raise ValueError("min_avg_volume cannot be negative")
        if self.min_relative_volume < 0:
            raise ValueError("min_relative_volume cannot be negative")
        if self.max_spread_pct < 0:
            raise ValueError("max_spread_pct cannot be negative")
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
        if self.auth_session_ttl_minutes <= 0:
            raise ValueError("auth_session_ttl_minutes must be positive")
        if self.auth_login_max_attempts <= 0:
            raise ValueError("auth_login_max_attempts must be positive")
        if self.auth_login_window_seconds <= 0:
            raise ValueError("auth_login_window_seconds must be positive")
        if self.auth_login_block_seconds <= 0:
            raise ValueError("auth_login_block_seconds must be positive")
        if not self.alpaca_base_url.strip():
            raise ValueError("alpaca_base_url cannot be empty")
        if self.app_env in {"production", "staging"} and any(
            origin == "*" for origin in self.cors_allowed_origins
        ):
            raise ValueError("Wildcard CORS origin is not allowed in production/staging")
        if self.app_env == "production" and self.database_url.startswith("sqlite"):
            raise ValueError("production deployment requires a Postgres DATABASE_URL")
        if self.auth_enabled and (
            not self.auth_session_secret.strip() or not self.auth_password_pepper.strip()
        ):
            raise ValueError("auth_session_secret and auth_password_pepper cannot be empty")
        if self.auth_bootstrap_admin_on_startup:
            if not self.auth_bootstrap_admin_email.strip():
                raise ValueError(
                    "auth_bootstrap_admin_email is required when bootstrap on startup is enabled"
                )
            if not self.auth_bootstrap_admin_password:
                raise ValueError(
                    "auth_bootstrap_admin_password is required when bootstrap on startup is enabled"
                )

        # Safety gate: active worker trading requires explicit paper mode unless dry-run is on.
        if self.worker_enable_trading and not self.paper_trading_enabled and not self.worker_dry_run:
            raise ValueError(
                "worker_enable_trading requires paper_trading_enabled=true unless WORKER_DRY_RUN=true"
            )

        # Hard guard against accidental live trading flags.
        if _read_bool("LIVE_TRADING", default=False):
            raise ValueError("LIVE_TRADING must remain disabled for this repository")

        if self.app_env in {"production", "staging"} and self.auth_enabled:
            if len(self.auth_session_secret.strip()) < 32:
                raise ValueError(
                    "auth_session_secret must be at least 32 characters in production/staging"
                )
            if len(self.auth_password_pepper.strip()) < 32:
                raise ValueError(
                    "auth_password_pepper must be at least 32 characters in production/staging"
                )
            insecure_defaults = {
                "dev-insecure-auth-session-secret-change-me",
                "dev-insecure-auth-password-pepper-change-me",
            }
            if (
                self.auth_session_secret.strip() in insecure_defaults
                or self.auth_password_pepper.strip() in insecure_defaults
            ):
                raise ValueError(
                    "auth secrets must not use development placeholder values in production/staging"
                )

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
            os.getenv("DATABASE_URL", "sqlite+pysqlite:///data/trauto.db")
        )
        worker_symbols_raw = os.getenv("WORKER_SYMBOLS", "").strip()
        if worker_symbols_raw:
            worker_symbols = _normalize_symbols(_parse_csv_env(worker_symbols_raw))
        else:
            worker_symbols = _normalize_symbols((os.getenv("WORKER_SYMBOL", "SPY"),))
        cors_allowed_origins = _parse_csv_env(
            os.getenv(
                "CORS_ALLOWED_ORIGINS",
                "http://localhost:3000,http://127.0.0.1:3000",
            )
        )

        return cls(
            app_env=app_env,
            service_name=os.getenv("SERVICE_NAME", "trauto").strip(),
            host=os.getenv("HOST", "0.0.0.0").strip(),
            port=int(os.getenv("PORT", "8000")),
            database_url=database_url,
            strict_env_validation=strict_env_validation,
            run_migrations_on_startup=_read_bool("RUN_MIGRATIONS_ON_STARTUP", default=True),
            cors_allowed_origins=cors_allowed_origins,
            auth_enabled=_read_bool("AUTH_ENABLED", default=True),
            auth_session_secret=os.getenv(
                "AUTH_SESSION_SECRET",
                "dev-insecure-auth-session-secret-change-me",
            ).strip(),
            auth_password_pepper=os.getenv(
                "AUTH_PASSWORD_PEPPER",
                "dev-insecure-auth-password-pepper-change-me",
            ).strip(),
            auth_session_ttl_minutes=int(os.getenv("AUTH_SESSION_TTL_MINUTES", "720")),
            auth_login_max_attempts=int(os.getenv("AUTH_LOGIN_MAX_ATTEMPTS", "5")),
            auth_login_window_seconds=int(os.getenv("AUTH_LOGIN_WINDOW_SECONDS", "900")),
            auth_login_block_seconds=int(os.getenv("AUTH_LOGIN_BLOCK_SECONDS", "900")),
            auth_bootstrap_admin_on_startup=_read_bool(
                "AUTH_BOOTSTRAP_ADMIN_ON_STARTUP",
                default=False,
            ),
            auth_bootstrap_admin_email=os.getenv("AUTH_BOOTSTRAP_ADMIN_EMAIL", "").strip(),
            auth_bootstrap_admin_password=os.getenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", ""),
            paper_trading_enabled=_read_bool("PAPER_TRADING", default=False),
            worker_enable_trading=_read_bool("WORKER_ENABLE_TRADING", default=False),
            worker_name=os.getenv("WORKER_NAME", "default-worker").strip(),
            worker_poll_seconds=int(os.getenv("WORKER_POLL_SECONDS", "60")),
            worker_symbol=(worker_symbols[0] if worker_symbols else "SPY"),
            worker_symbols=worker_symbols,
            worker_timeframe=os.getenv("WORKER_TIMEFRAME", "1d").strip(),
            worker_strategy=os.getenv("WORKER_STRATEGY", "moving_average_crossover").strip(),
            worker_strategy_params=strategy_params,
            worker_order_quantity=float(os.getenv("WORKER_ORDER_QUANTITY", "1.0")),
            worker_force_refresh=_read_bool("WORKER_FORCE_REFRESH", default=False),
            worker_dry_run=_read_bool("WORKER_DRY_RUN", default=True),
            worker_allow_multi_strategy_per_symbol=_read_bool(
                "WORKER_ALLOW_MULTI_STRATEGY_PER_SYMBOL",
                default=False,
            ),
            worker_universe_mode=os.getenv("WORKER_UNIVERSE_MODE", "static").strip().lower(),
            worker_max_candidates=int(os.getenv("WORKER_MAX_CANDIDATES", "10")),
            selection_min_recent_trades=int(os.getenv("SELECTION_MIN_RECENT_TRADES", "5")),
            worker_startup_warmup_cycles=int(os.getenv("WORKER_STARTUP_WARMUP_CYCLES", "20")),
            min_price=float(os.getenv("MIN_PRICE", "1.0")),
            min_avg_volume=float(os.getenv("MIN_AVG_VOLUME", "100000")),
            min_relative_volume=float(os.getenv("MIN_RELATIVE_VOLUME", "0.0")),
            max_spread_pct=float(os.getenv("MAX_SPREAD_PCT", "1.0")),
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
            alpaca_api_key=read_alpaca_api_key(),
            alpaca_api_secret=read_alpaca_api_secret(),
            alpaca_base_url=read_alpaca_execution_base_url(),
        )
