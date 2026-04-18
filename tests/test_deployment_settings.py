"""Tests for deployment/runtime environment validation."""

from __future__ import annotations

import pytest

from src.config.deployment import DeploymentSettings


def test_defaults_keep_trading_disabled() -> None:
    settings = DeploymentSettings()
    assert settings.paper_trading_enabled is False
    assert settings.worker_enable_trading is False
    assert settings.worker_dry_run is True
    assert settings.execution_profile == "conservative"
    assert settings.extended_hours_enabled is False
    assert settings.enable_strategy_gating is False
    assert settings.enable_position_sizing is False
    assert settings.enable_risk_caps is False


def test_worker_trading_requires_paper_mode() -> None:
    with pytest.raises(ValueError, match="worker_enable_trading requires"):
        DeploymentSettings(
            worker_enable_trading=True,
            paper_trading_enabled=False,
            worker_dry_run=False,
        )


def test_worker_trading_allows_dry_run_without_paper() -> None:
    settings = DeploymentSettings(
        worker_enable_trading=True,
        paper_trading_enabled=False,
        worker_dry_run=True,
    )
    assert settings.worker_enable_trading is True
    assert settings.worker_dry_run is True


def test_production_requires_postgres_database() -> None:
    with pytest.raises(ValueError, match="requires a Postgres DATABASE_URL"):
        DeploymentSettings(app_env="production", database_url="sqlite+pysqlite:///data/trauto.db")


def test_from_env_normalizes_render_postgres_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://example.com:5432/theta")
    settings = DeploymentSettings.from_env()
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_strict_mode_requires_explicit_required_env_vars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")

    for env_name in (
        "APP_ENV",
        "DATABASE_URL",
        "WORKER_NAME",
        "PAPER_TRADING",
        "WORKER_ENABLE_TRADING",
        "LIVE_TRADING",
        "CORS_ALLOWED_ORIGINS",
        "AUTH_SESSION_SECRET",
        "AUTH_PASSWORD_PEPPER",
    ):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setenv("STRICT_ENV_VALIDATION", "true")

    with pytest.raises(ValueError, match="Missing required environment variables"):
        DeploymentSettings.from_env(env_path=empty_env)


def test_production_mode_missing_database_url_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    empty_env = tmp_path / "empty.env"
    empty_env.write_text("")

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WORKER_NAME", "main-worker")
    monkeypatch.setenv("PAPER_TRADING", "false")
    monkeypatch.setenv("WORKER_ENABLE_TRADING", "false")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://trauto.onrender.com")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("AUTH_PASSWORD_PEPPER", "y" * 40)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="DATABASE_URL"):
        DeploymentSettings.from_env(env_path=empty_env)


def test_production_rejects_wildcard_cors_origin() -> None:
    with pytest.raises(ValueError, match="Wildcard CORS origin"):
        DeploymentSettings(
            app_env="production",
            database_url="postgresql+psycopg://example.com:5432/theta",
            worker_name="main-worker",
            paper_trading_enabled=False,
            worker_enable_trading=False,
            cors_allowed_origins=("*",),
        )


def test_worker_symbols_default_to_single_symbol() -> None:
    settings = DeploymentSettings()
    assert settings.worker_symbols == ("SPY",)
    assert settings.worker_symbol == "SPY"
    assert settings.worker_universe_mode == "static"


def test_from_env_worker_symbols_overrides_worker_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKER_SYMBOLS", "spy, qqq, SPY")
    monkeypatch.setenv("WORKER_SYMBOL", "iwm")
    settings = DeploymentSettings.from_env()
    assert settings.worker_symbols == ("SPY", "QQQ")
    assert settings.worker_symbol == "SPY"


def test_from_env_reads_universe_scanner_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKER_UNIVERSE_MODE", "high_relative_volume")
    monkeypatch.setenv("WORKER_MAX_CANDIDATES", "7")
    monkeypatch.setenv("MIN_PRICE", "5")
    monkeypatch.setenv("MIN_AVG_VOLUME", "250000")
    monkeypatch.setenv("MIN_RELATIVE_VOLUME", "1.2")
    monkeypatch.setenv("MAX_SPREAD_PCT", "0.05")
    settings = DeploymentSettings.from_env()
    assert settings.worker_universe_mode == "high_relative_volume"
    assert settings.worker_max_candidates == 7
    assert settings.min_price == 5.0
    assert settings.min_avg_volume == 250000.0
    assert settings.min_relative_volume == 1.2
    assert settings.max_spread_pct == 0.05


def test_from_env_reads_selection_warmup_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SELECTION_MIN_RECENT_TRADES", "2")
    monkeypatch.setenv("WORKER_STARTUP_WARMUP_CYCLES", "8")
    settings = DeploymentSettings.from_env()
    assert settings.selection_min_recent_trades == 2
    assert settings.worker_startup_warmup_cycles == 8


def test_from_env_reads_worker_freshness_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONLY_OPEN_NEW_POSITIONS_DURING_MARKET_HOURS", "false")
    monkeypatch.setenv("WORKER_STALE_MARKET_DATA_GRACE_MINUTES", "90")
    monkeypatch.setenv("WORKER_STALE_MARKET_DATA_INTERVAL_MULTIPLIER", "4")

    settings = DeploymentSettings.from_env()

    assert settings.only_open_new_positions_during_market_hours is False
    assert settings.worker_stale_market_data_grace_minutes == 90.0
    assert settings.worker_stale_market_data_interval_multiplier == 4.0


def test_from_env_reads_trade_control_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_STRATEGY_GATING", "true")
    monkeypatch.setenv("ENABLE_POSITION_SIZING", "true")
    monkeypatch.setenv("ENABLE_RISK_CAPS", "true")
    monkeypatch.setenv("RISK_PER_TRADE_PCT", "0.0075")
    monkeypatch.setenv("MAX_CONCURRENT_POSITIONS", "4")
    monkeypatch.setenv("MAX_PORTFOLIO_EXPOSURE_PCT", "0.35")
    monkeypatch.setenv("DAILY_DRAWDOWN_LIMIT_PCT", "0.03")
    monkeypatch.setenv("MARKET_REGIME_THRESHOLD_PCT", "0.002")
    monkeypatch.setenv("ALLOW_RSI_IN_BULLISH_REGIME", "true")
    monkeypatch.setenv("ALLOW_BEARISH_MEAN_REVERSION", "true")
    monkeypatch.setenv("DEFAULT_STOP_LOSS_PCT_FOR_SIZING", "0.025")

    settings = DeploymentSettings.from_env()

    assert settings.enable_strategy_gating is True
    assert settings.enable_position_sizing is True
    assert settings.enable_risk_caps is True
    assert settings.risk_per_trade_pct == 0.0075
    assert settings.max_concurrent_positions == 4
    assert settings.max_portfolio_exposure_pct == 0.35
    assert settings.daily_drawdown_limit_pct == 0.03
    assert settings.market_regime_threshold_pct == 0.002
    assert settings.allow_rsi_in_bullish_regime is True
    assert settings.allow_bearish_mean_reversion is True
    assert settings.default_stop_loss_pct_for_sizing == 0.025


def test_from_env_reads_active_day_trader_profile_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXECUTION_PROFILE", "active_day_trader")

    settings = DeploymentSettings.from_env()

    assert settings.execution_profile == "active_day_trader"
    assert settings.worker_timeframe == "1m"
    assert settings.worker_max_candidates == 25
    assert settings.selection_min_recent_trades == 0
    assert settings.worker_startup_warmup_cycles == 0
    assert settings.min_avg_volume == 25_000.0
    assert settings.risk_per_trade_pct == 0.0025
    assert settings.max_concurrent_positions == 5
    assert settings.max_trades_per_day == 20
    assert settings.symbol_cooldown_seconds == 300
    assert settings.strategy_cooldown_seconds == 180
    assert settings.force_flatten_before_session_end is True


def test_from_env_reads_balanced_profile_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXECUTION_PROFILE", "balanced")

    settings = DeploymentSettings.from_env()

    assert settings.execution_profile == "balanced"
    assert settings.worker_timeframe == "5m"
    assert settings.worker_poll_seconds == 300
    assert settings.worker_max_candidates == 15
    assert settings.selection_min_recent_trades == 3
    assert settings.worker_startup_warmup_cycles == 10
    assert settings.min_avg_volume == 50_000.0
    assert settings.risk_per_trade_pct == 0.0035
    assert settings.max_concurrent_positions == 4
    assert settings.max_trades_per_day == 15


def test_from_env_reads_extended_hours_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EXTENDED_HOURS_ENABLED", "true")
    monkeypatch.setenv("BROKER_EXTENDED_HOURS_SUPPORTED", "true")
    monkeypatch.setenv("OVERNIGHT_TRADING_ENABLED", "true")
    monkeypatch.setenv("ALLOW_OVERNIGHT_POSITIONS", "true")
    monkeypatch.setenv("USE_LIMIT_ORDERS_IN_EXTENDED_HOURS", "false")
    monkeypatch.setenv("LIMIT_ORDER_AGGRESSIVENESS_PCT", "0.002")
    monkeypatch.setenv("ENFORCE_RELATIVE_VOLUME_FILTER", "true")

    settings = DeploymentSettings.from_env()

    assert settings.extended_hours_enabled is True
    assert settings.broker_extended_hours_supported is True
    assert settings.overnight_trading_enabled is True
    assert settings.allow_overnight_positions is True
    assert settings.use_limit_orders_in_extended_hours is False
    assert settings.limit_order_aggressiveness_pct == 0.002
    assert settings.enforce_relative_volume_filter is True


def test_negative_selection_warmup_settings_are_rejected() -> None:
    with pytest.raises(ValueError, match="selection_min_recent_trades"):
        DeploymentSettings(selection_min_recent_trades=-1)
    with pytest.raises(ValueError, match="worker_startup_warmup_cycles"):
        DeploymentSettings(worker_startup_warmup_cycles=-1)


def test_invalid_universe_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="worker_universe_mode"):
        DeploymentSettings(worker_universe_mode="unsupported-mode")


def test_from_env_reads_alpaca_execution_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    settings = DeploymentSettings.from_env()
    assert settings.alpaca_base_url == "https://paper-api.alpaca.markets"


def test_from_env_supports_legacy_alpaca_secret_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.setenv("ALPACA_SECRET_KEY", "legacy-secret")
    settings = DeploymentSettings.from_env()
    assert settings.alpaca_api_secret == "legacy-secret"


def test_production_rejects_short_auth_secrets() -> None:
    with pytest.raises(ValueError, match="auth_session_secret"):
        DeploymentSettings(
            app_env="production",
            database_url="postgresql+psycopg://example.com:5432/theta",
            worker_name="main-worker",
            paper_trading_enabled=False,
            worker_enable_trading=False,
            cors_allowed_origins=("https://trauto.onrender.com",),
            auth_session_secret="short",
            auth_password_pepper="p" * 40,
        )
