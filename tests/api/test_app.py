"""Endpoint tests for the backend API layer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture()
def client() -> TestClient:
    """Return a test client with clean API service state."""
    app.state.api_service.reset()
    with TestClient(app) as test_client:
        yield test_client
    app.state.api_service.reset()


def test_get_strategies_returns_registered_strategies(client: TestClient) -> None:
    response = client.get("/api/strategies")
    assert response.status_code == 200
    payload = response.json()
    assert any(strategy["name"] == "moving_average_crossover" for strategy in payload)
    assert any(strategy["name"] == "rsi_mean_reversion" for strategy in payload)


def test_patch_strategy_updates_status_and_parameters(client: TestClient) -> None:
    response = client.patch(
        "/api/strategies/moving_average_crossover",
        json={"status": "disabled", "parameters": {"short_window": 15}},
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["status"] == "disabled"
    assert updated["parameters"]["short_window"] == 15


def test_patch_strategy_rejects_invalid_parameters(client: TestClient) -> None:
    response = client.patch(
        "/api/strategies/moving_average_crossover",
        json={"parameters": {"short_window": 50, "long_window": 20}},
    )
    assert response.status_code == 422
    assert "Invalid parameters" in response.json()["detail"]


def test_run_backtest_endpoint_and_dashboard_summary(client: TestClient) -> None:
    run_response = client.post(
        "/api/backtests/run",
        json={
            "symbol": "SPY",
            "timeframe": "1d",
            "strategy": "moving_average_crossover",
            "strategy_params": {"short_window": 10, "long_window": 30},
        },
    )
    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["run_id"]
    assert "total_return" in run_payload["metrics"]
    assert isinstance(run_payload["equity_curve"], list)
    assert isinstance(run_payload["trades"], list)

    summary_response = client.get("/api/dashboard/summary")
    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["last_run_id"] == run_payload["run_id"]
    assert summary_payload["system_status"] in {"paper_only_ready", "kill_switch_enabled"}

    trades_response = client.get("/api/trades")
    assert trades_response.status_code == 200
    trades_payload = trades_response.json()
    assert trades_payload["total"] >= 0


def test_kill_switch_blocks_backtest(client: TestClient) -> None:
    enable_response = client.post("/api/system/kill-switch", json={"enabled": True})
    assert enable_response.status_code == 200
    assert enable_response.json()["kill_switch_enabled"] is True

    risk_response = client.get("/api/risk/status")
    assert risk_response.status_code == 200
    assert risk_response.json()["kill_switch_enabled"] is True

    run_response = client.post("/api/backtests/run", json={})
    assert run_response.status_code == 409


def test_health_and_system_status_endpoints(client: TestClient) -> None:
    health_response = client.get("/healthz")
    assert health_response.status_code == 200
    health_payload = health_response.json()
    assert health_payload["status"] in {"ok", "degraded"}
    assert health_payload["database"] in {"ok", "error"}

    status_response = client.get("/api/system/status")
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


def test_cors_headers_present_on_get_for_configured_origin(client: TestClient) -> None:
    response = client.get(
        "/api/strategies",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
