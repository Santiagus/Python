"""Unit tests for standalone Sanctions Watchlist Simulator API (TC-14, TC-15)."""

import pytest
from starlette.testclient import TestClient

from services.sanctions_api.main import _simulation_state, app


@pytest.fixture(autouse=True)
def reset_simulator_state() -> None:
    """Ensure simulator state is reset to normal before each test."""
    _simulation_state.reset()


def test_sanctions_api_health_and_metrics() -> None:
    """Verify health and Prometheus metrics endpoints on the Sanctions API."""
    with TestClient(app) as client:
        # Health
        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"status": "ok", "service": "sanctions_api"}

        # Metrics
        res_metrics = client.get("/metrics")
        assert res_metrics.status_code == 200
        assert "sanctions_api_requests_total" in res_metrics.text


def test_sanctions_check_clean_entity() -> None:
    """TC-14: Verify check returns no matches for clean corporate entities."""
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/watchlists/check",
            json={"entity_name": "Global Logistic Services LLC"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["entity_name"] == "Global Logistic Services LLC"
        assert data["is_sanctioned"] is False
        assert data["matches"] == []


def test_sanctions_check_positive_match() -> None:
    """TC-14: Verify check identifies OFAC sanctioned individuals."""
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/watchlists/check",
            json={"entity_name": "Vladimir Rostov"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_sanctioned"] is True
        assert len(data["matches"]) >= 1
        assert data["matches"][0]["watchlist_type"] == "OFAC_SDN"
        assert data["matches"][0]["match_confidence"] == 99.20


def test_sanctions_simulation_timeout_mode() -> None:
    """TC-15: Verify simulator returns HTTP 504 when chaos timeout mode is active."""
    with TestClient(app) as client:
        res_mode = client.post(
            "/api/v1/simulate/mode",
            json={"mode": "timeout", "latency_seconds": 0.0},
        )
        assert res_mode.status_code == 200
        assert res_mode.json()["mode"] == "timeout"

        res_check = client.post(
            "/api/v1/watchlists/check",
            json={"entity_name": "Any Corp"},
        )
        assert res_check.status_code == 504
        assert "Simulated partner gateway timeout" in res_check.json()["detail"]


def test_sanctions_simulation_error_mode() -> None:
    """TC-15: Verify simulator returns HTTP 500 when chaos error mode is active."""
    with TestClient(app) as client:
        res_mode = client.post(
            "/api/v1/simulate/mode",
            json={"mode": "error", "latency_seconds": 0.0},
        )
        assert res_mode.status_code == 200

        res_check = client.post(
            "/api/v1/watchlists/check",
            json={"entity_name": "Any Corp"},
        )
        assert res_check.status_code == 500
        assert "Simulated internal upstream error" in res_check.json()["detail"]


def test_sanctions_simulation_latency_mode() -> None:
    """Verify latency injection executes cleanly."""
    with TestClient(app) as client:
        client.post(
            "/api/v1/simulate/mode",
            json={"mode": "normal", "latency_seconds": 0.01},
        )

        res = client.post(
            "/api/v1/watchlists/check",
            json={"entity_name": "Quick Corp"},
        )
        assert res.status_code == 200
        assert res.json()["is_sanctioned"] is False


def test_sanctions_validation_failure() -> None:
    """Verify validation constraint on entity name."""
    with TestClient(app) as client:
        res = client.post(
            "/api/v1/watchlists/check",
            json={"entity_name": "A"},
        )
        assert res.status_code == 422


def test_sanctions_simulation_reset() -> None:
    """Verify reset endpoint restores simulation state to normal."""
    with TestClient(app) as client:
        # First set to timeout mode
        client.post(
            "/api/v1/simulate/mode",
            json={"mode": "timeout", "latency_seconds": 1.0},
        )
        # Reset back
        res = client.post("/api/v1/simulate/reset")
        assert res.status_code == 200
        assert res.json() == {"status": "reset", "mode": "normal"}
