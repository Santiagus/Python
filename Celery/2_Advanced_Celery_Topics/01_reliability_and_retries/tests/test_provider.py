"""Regression tests for the unreliable provider simulator's retry and idempotency behavior."""

from fastapi.testclient import TestClient

from services.provider_api.app import app, attempts, transactions


def test_default_provider_sequence_retries_then_succeeds():
    """The default provider mode should fail twice before succeeding and replay the same result."""
    attempts.clear()
    transactions.clear()
    client = TestClient(app)
    headers = {"Idempotency-Key": "sequence-test"}
    payload = {"amount": 100, "currency": "usd"}

    first = client.post("/provider/transactions", headers=headers, json=payload)
    second = client.post("/provider/transactions", headers=headers, json=payload)
    third = client.post("/provider/transactions", headers=headers, json=payload)
    replay = client.post("/provider/transactions", headers=headers, json=payload)

    assert first.status_code == 503
    assert second.status_code == 503
    assert third.status_code == 201
    assert replay.status_code == 201
    assert replay.json() == third.json()


def test_success_mode_skips_failure_sequence():
    """A success mode request should skip the failure sequence and complete immediately."""
    attempts.clear()
    transactions.clear()
    client = TestClient(app)

    response = client.post(
        "/provider/transactions",
        headers={"Idempotency-Key": "success-test"},
        json={"amount": 100, "currency": "usd", "failure_mode": "success"},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"