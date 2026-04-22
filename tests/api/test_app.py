"""Endpoint tests for the backend API layer."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.auth.security import hash_session_token

TEST_ADMIN_EMAIL = "admin@example.com"
TEST_ADMIN_PASSWORD = "ChangeMeNow123!"


@pytest.fixture()
def client() -> TestClient:
    """Return a test client with clean API service state and bootstrap admin."""
    app.state.api_service.reset()
    app.state.auth_service.bootstrap_admin(
        email=TEST_ADMIN_EMAIL,
        password=TEST_ADMIN_PASSWORD,
    )
    with TestClient(app) as test_client:
        yield test_client
    app.state.api_service.reset()


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    """Return auth headers for an admin session."""
    response = client.post(
        "/api/auth/login",
        json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_login_success_and_session_endpoint(client: TestClient) -> None:
    login_response = client.post(
        "/api/auth/login",
        json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
    )
    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["token"]
    assert login_payload["user"]["email"] == TEST_ADMIN_EMAIL
    assert login_payload["user"]["role"] == "admin"

    session_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {login_payload['token']}"},
    )
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["user"]["email"] == TEST_ADMIN_EMAIL


def test_login_failure_returns_unauthorized(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": TEST_ADMIN_EMAIL, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert "Invalid email or password" in response.json()["detail"]


def test_protected_route_rejects_unauthenticated(client: TestClient) -> None:
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 401


def test_logout_revokes_session(client: TestClient, admin_headers: dict[str, str]) -> None:
    logout_response = client.post("/api/auth/logout", headers=admin_headers)
    assert logout_response.status_code == 200
    assert logout_response.json()["ok"] is True

    session_response = client.get("/api/auth/session", headers=admin_headers)
    assert session_response.status_code == 401


def test_expired_session_is_rejected(client: TestClient, admin_headers: dict[str, str]) -> None:
    token = admin_headers["Authorization"].split(" ", 1)[1]
    token_hash = hash_session_token(
        token=token,
        session_secret=app.state.deployment_settings.auth_session_secret,
    )
    app.state.repository.expire_auth_session(token_hash)

    session_response = client.get("/api/auth/session", headers=admin_headers)
    assert session_response.status_code == 401
    assert "Session expired" in session_response.json()["detail"]


def test_password_change_requires_authenticated_session(client: TestClient) -> None:
    response = client.post(
        "/api/auth/password",
        json={
            "current_password": TEST_ADMIN_PASSWORD,
            "new_password": "UpdatedPass456!",
            "confirm_new_password": "UpdatedPass456!",
        },
    )
    assert response.status_code == 401


def test_password_change_flow_rotates_credentials(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    change_response = client.post(
        "/api/auth/password",
        json={
            "current_password": TEST_ADMIN_PASSWORD,
            "new_password": "UpdatedPass456!",
            "confirm_new_password": "UpdatedPass456!",
        },
        headers=admin_headers,
    )
    assert change_response.status_code == 200
    assert change_response.json()["ok"] is True

    old_login = client.post(
        "/api/auth/login",
        json={"email": TEST_ADMIN_EMAIL, "password": TEST_ADMIN_PASSWORD},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/auth/login",
        json={"email": TEST_ADMIN_EMAIL, "password": "UpdatedPass456!"},
    )
    assert new_login.status_code == 200
    assert new_login.json()["token"]

    events = app.state.repository.recent_log_events(limit=10, event="auth_password_changed")
    assert events
    assert events[0]["payload"]["actor_email"] == TEST_ADMIN_EMAIL


def test_get_strategies_returns_registered_strategies(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.get("/api/strategies", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert any(strategy["name"] == "moving_average_crossover" for strategy in payload)
    assert any(strategy["name"] == "rsi_mean_reversion" for strategy in payload)
    assert any(strategy["name"] == "breakout_momentum" for strategy in payload)
    assert any(strategy["name"] == "vwap_mean_reversion" for strategy in payload)


def test_patch_strategy_updates_status_and_parameters(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.patch(
        "/api/strategies/moving_average_crossover",
        json={"status": "disabled", "parameters": {"short_window": 15}},
        headers=admin_headers,
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "disabled"
    assert updated["parameters"]["short_window"] == 15


def test_patch_strategy_rejects_invalid_parameters(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.patch(
        "/api/strategies/moving_average_crossover",
        json={"parameters": {"short_window": 50, "long_window": 20}},
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert "Invalid parameters" in response.json()["detail"]


def test_run_backtest_endpoint_and_dashboard_summary(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    run_response = client.post(
        "/api/backtests/run",
        json={
            "symbol": "SPY",
            "timeframe": "1d",
            "strategy": "moving_average_crossover",
            "strategy_params": {"short_window": 10, "long_window": 30},
        },
        headers=admin_headers,
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["run_id"]
    assert "total_return" in run_payload["metrics"]
    assert isinstance(run_payload["equity_curve"], list)
    assert isinstance(run_payload["trades"], list)

    summary_response = client.get("/api/dashboard/summary", headers=admin_headers)
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["last_run_id"] == run_payload["run_id"]
    assert summary_payload["system_status"] in {
        "paper_only_idle",
        "paper_only_ready",
        "kill_switch_enabled",
    }

    trades_response = client.get("/api/trades", headers=admin_headers)
    assert trades_response.status_code == 200
    trades_payload = trades_response.json()
    assert trades_payload["total"] >= 0


def test_run_backtest_with_new_strategy_profiles(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.post(
        "/api/backtests/run",
        json={
            "symbol": "SPY",
            "timeframe": "1d",
            "strategy": "breakout_momentum",
        },
        headers=admin_headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["strategy"] == "breakout_momentum"
    assert payload["metrics"]["position_size_pct"] <= 0.25


def test_kill_switch_blocks_backtest(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    enable_response = client.post(
        "/api/system/kill-switch",
        json={"enabled": True},
        headers=admin_headers,
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["kill_switch_enabled"] is True

    risk_response = client.get("/api/risk/status", headers=admin_headers)
    assert risk_response.status_code == 200
    assert risk_response.json()["kill_switch_enabled"] is True

    run_response = client.post(
        "/api/backtests/run",
        json={},
        headers=admin_headers,
    )
    assert run_response.status_code == 409


def test_health_and_system_status_endpoints(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    health_response = client.get("/healthz")
    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["status"] in {"ok", "degraded"}
    assert health_payload["database"] in {"ok", "error"}

    status_response = client.get("/api/system/status", headers=admin_headers)
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert "service_name" in status_payload
    assert "database_ok" in status_payload


def test_cors_preflight_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/dashboard/summary",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    allowed_methods = response.headers.get("access-control-allow-methods", "")
    for method in ("GET", "POST", "PATCH", "OPTIONS"):
        assert method in allowed_methods

    allowed_headers = response.headers.get("access-control-allow-headers", "").lower()
    assert "content-type" in allowed_headers


def test_cors_headers_present_on_get_for_configured_origin(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.get(
        "/api/strategies",
        headers={
            **admin_headers,
            "Origin": "http://localhost:3000",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_analytics_and_selection_endpoints_return_typed_shapes(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    strategies_response = client.get("/api/analytics/strategies", headers=admin_headers)
    assert strategies_response.status_code == 200
    strategies_payload = strategies_response.json()
    assert isinstance(strategies_payload["generated_at"], str)
    assert strategies_payload["data_source"] == "execution"
    assert strategies_payload["aggregation_scope"] in {"single_run", "multi_run_aggregate"}
    assert isinstance(strategies_payload["run_count"], int)
    assert isinstance(strategies_payload["strategies"], list)

    portfolio_response = client.get("/api/analytics/portfolio", headers=admin_headers)
    assert portfolio_response.status_code == 200
    portfolio_payload = portfolio_response.json()
    assert isinstance(portfolio_payload["generated_at"], str)
    assert portfolio_payload["data_source"] == "execution"
    assert isinstance(portfolio_payload["equity_curve"], list)
    assert isinstance(portfolio_payload["daily_pnl"], list)
    assert isinstance(portfolio_payload["rolling_drawdown"], list)
    assert isinstance(portfolio_payload["strategy_contribution"], list)

    context_response = client.get("/api/analytics/context", headers=admin_headers)
    assert context_response.status_code == 200
    context_payload = context_response.json()
    assert isinstance(context_payload["generated_at"], str)
    assert context_payload["data_source"] == "execution"
    assert isinstance(context_payload["by_symbol"], list)
    assert isinstance(context_payload["by_regime"], list)

    selection_response = client.get("/api/selection/status", headers=admin_headers)
    assert selection_response.status_code == 200
    selection_payload = selection_response.json()
    assert "selected_strategy" in selection_payload
    assert isinstance(selection_payload["candidates"], list)


def test_strategy_analytics_populates_after_backtest_run(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    run_response = client.post(
        "/api/backtests/run",
        json={
            "symbol": "SPY",
            "timeframe": "1d",
            "strategy": "moving_average_crossover",
            "strategy_params": {"short_window": 10, "long_window": 30},
        },
        headers=admin_headers,
    )
    assert run_response.status_code == 200

    backtest_analytics_response = client.get(
        "/api/analytics/strategies?source=backtest",
        headers=admin_headers,
    )
    assert backtest_analytics_response.status_code == 200
    backtest_payload = backtest_analytics_response.json()
    assert isinstance(backtest_payload["generated_at"], str)
    assert backtest_payload["data_source"] == "backtest"
    assert backtest_payload["aggregation_scope"] in {"single_run", "multi_run_aggregate"}
    assert isinstance(backtest_payload["run_count"], int)
    assert any(
        item["strategy"] == "moving_average_crossover"
        for item in backtest_payload["strategies"]
    )

    paper_analytics_response = client.get(
        "/api/analytics/strategies?source=paper",
        headers=admin_headers,
    )
    assert paper_analytics_response.status_code == 200
    paper_payload = paper_analytics_response.json()
    assert paper_payload["data_source"] == "paper"
    assert isinstance(paper_payload["strategies"], list)


def test_worker_execution_status_endpoint_exposes_universe_and_symbol_rows(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    response = client.get("/api/worker/execution-status", headers=admin_headers)
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["generated_at"], str)
    assert isinstance(payload["worker_name"], str)
    assert isinstance(payload["timeframe"], str)
    assert isinstance(payload["universe_mode"], str)
    assert isinstance(payload["dry_run_enabled"], bool)
    assert isinstance(payload["universe_symbols"], list)
    assert isinstance(payload["scanned_symbols"], list)
    assert isinstance(payload["shortlisted_symbols"], list)
    assert isinstance(payload["allow_multi_strategy_per_symbol"], bool)
    assert payload["selected_symbol"] is None or isinstance(payload["selected_symbol"], str)
    assert payload["selected_strategy"] is None or isinstance(payload["selected_strategy"], str)
    assert payload["last_selected_symbol"] is None or isinstance(payload["last_selected_symbol"], str)
    assert payload["last_selected_strategy"] is None or isinstance(payload["last_selected_strategy"], str)
    assert payload["last_no_trade_reason"] is None or isinstance(payload["last_no_trade_reason"], str)
    assert isinstance(payload["symbol_filter_reasons"], dict)
    assert isinstance(payload["active_strategy_by_symbol"], dict)
    assert isinstance(payload["symbols"], list)


def test_worker_status_and_selection_ignore_mismatched_timeframe_runs(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    service = app.state.api_service
    repository = service.repository
    deployment_settings = service.deployment_settings
    assert repository is not None
    assert deployment_settings is not None

    worker_name = deployment_settings.worker_name
    expected_timeframe = deployment_settings.worker_timeframe
    worker_service = f"worker:{worker_name}"
    current_run_id = f"worker-current-timeframe-run-{uuid4().hex}"
    mismatch_run_id = f"worker-mismatched-timeframe-run-{uuid4().hex}"

    repository.start_run(
        run_id=current_run_id,
        service=worker_service,
        cycle_key=f"SPY:{expected_timeframe}:{current_run_id}",
        symbol="SPY",
        timeframe=expected_timeframe,
        strategy="strategy_selector",
        details={
            "selection": {
                "selected_strategy": "moving_average_crossover",
                "selected_score": 0.5,
                "minimum_score_threshold": 0.05,
                "sizing_multiplier": 1.0,
                "allocation_fraction": 1.0,
                "regime": "trending",
                "regime_signals": {},
                "candidates": [],
            }
        },
    )
    repository.finish_run(run_id=current_run_id, status="completed")

    repository.start_run(
        run_id=mismatch_run_id,
        service=worker_service,
        cycle_key=f"QQQ:15m:{mismatch_run_id}",
        symbol="QQQ",
        timeframe="15m",
        strategy="strategy_selector",
        details={
            "selection": {
                "selected_strategy": "breakout_momentum",
                "selected_score": 0.9,
                "minimum_score_threshold": 0.05,
                "sizing_multiplier": 1.0,
                "allocation_fraction": 1.0,
                "regime": "trending",
                "regime_signals": {},
                "candidates": [],
            }
        },
    )
    repository.finish_run(run_id=mismatch_run_id, status="completed")

    selection_response = client.get("/api/selection/status", headers=admin_headers)
    assert selection_response.status_code == 200
    selection_payload = selection_response.json()
    assert selection_payload["selected_strategy"] == "moving_average_crossover"

    worker_status_response = client.get("/api/worker/execution-status", headers=admin_headers)
    assert worker_status_response.status_code == 200
    worker_payload = worker_status_response.json()
    assert worker_payload["timeframe"] == expected_timeframe
    assert all(
        symbol_row["timeframe"] == expected_timeframe
        for symbol_row in worker_payload["symbols"]
        if symbol_row["run_id"] is not None
    )


def test_backtest_missing_alpaca_credentials_returns_clear_error(
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_PROVIDER", "alpaca")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    response = client.post(
        "/api/backtests/run",
        json={
            "symbol": "SPY",
            "timeframe": "1d",
            "start": "2025-01-01",
            "end": "2025-12-31",
            "strategy": "moving_average_crossover",
        },
        headers=admin_headers,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "ALPACA_API_KEY" in detail
    assert "ALPACA_API_SECRET" in detail
    assert "web service" in detail


def test_sensitive_actions_write_audit_events(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    strategy_response = client.patch(
        "/api/strategies/moving_average_crossover",
        json={"status": "enabled"},
        headers=admin_headers,
    )
    assert strategy_response.status_code == 200

    kill_switch_response = client.post(
        "/api/system/kill-switch",
        json={"enabled": True},
        headers=admin_headers,
    )
    assert kill_switch_response.status_code == 200

    strategy_events = app.state.repository.recent_log_events(
        limit=20,
        event="api_strategy_updated",
    )
    assert strategy_events
    assert strategy_events[0]["payload"]["actor_email"] == TEST_ADMIN_EMAIL

    kill_switch_events = app.state.repository.recent_log_events(
        limit=20,
        event="api_kill_switch_toggled",
    )
    assert kill_switch_events
    assert kill_switch_events[0]["payload"]["actor_email"] == TEST_ADMIN_EMAIL
