"""Tests for deployment/runtime environment validation."""

from __future__ import annotations

import pytest

from src.config.deployment import DeploymentSettings


def test_defaults_keep_trading_disabled() -> None:
    settings = DeploymentSettings()
    assert settings.paper_trading_enabled is False
    assert settings.worker_enable_trading is False


def test_worker_trading_requires_paper_mode() -> None:
    with pytest.raises(ValueError, match="worker_enable_trading requires"):
        DeploymentSettings(worker_enable_trading=True, paper_trading_enabled=False)


def test_production_requires_postgres_database() -> None:
    with pytest.raises(ValueError, match="requires a Postgres DATABASE_URL"):
        DeploymentSettings(app_env="production", database_url="sqlite+pysqlite:///data/theta.db")


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
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://thetadata.onrender.com")
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
