"""Unit tests for the Wholesale Bank Simulator API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from services.bank_simulator_api.main import app, clear_simulator_store


@pytest.fixture(autouse=True)
def reset_store_before_each_test() -> None:
    """Ensure in-memory settlement store is pristine before each test execution."""
    clear_simulator_store()


@pytest.mark.asyncio
async def test_health_and_ready_endpoints() -> None:
    """Verify health and readiness probes return 200 OK."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok"}

        ready_resp = await client.get("/ready")
        assert ready_resp.status_code == 200
        assert ready_resp.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_chaos_reset_endpoint() -> None:
    """Verify resetting the simulator state via the chaos endpoint."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        reset_resp = await client.post("/v1/chaos/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json() == {"status": "cleared"}


@pytest.mark.asyncio
async def test_two_phase_inquiry_and_settlement_flow() -> None:
    """Verify the Two-Phase Provider Inquiry pattern (404 on Phase 1, 200 on Phase 2, 200 on redelivery)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        idempotency_key = "idemp-corp-test-100"

        # 1. Phase 1 Inquiry: Wire not yet disbursed -> Expect 404 NOT FOUND
        inquiry_404 = await client.get(f"/v1/wires/{idempotency_key}")
        assert inquiry_404.status_code == 404
        assert "not found" in inquiry_404.json()["detail"].lower()

        # 2. Phase 2 Settlement: Execute disbursement
        payload = {
            "idempotency_key": idempotency_key,
            "amount_cents": 5000000,
            "currency": "USD",
            "beneficiary_account_mask": "******8888",
            "routing_number": "121000358",
            "swift_bic": "CHASUS33XXX",
            "disbursement_token": "tok_fedwire_123",
        }
        settle_resp = await client.post("/v1/wires/settle", json=payload)
        assert settle_resp.status_code == 200
        data1 = settle_resp.json()
        assert data1["status"] == "CONFIRMED"
        assert data1["idempotency_key"] == idempotency_key
        assert data1["amount_cents"] == 5000000
        assert data1["bank_reference_id"].startswith("FED-WIRE-")

        # 3. Phase 1 Inquiry: Now returns 200 OK with confirmed settlement
        inquiry_200 = await client.get(f"/v1/wires/{idempotency_key}")
        assert inquiry_200.status_code == 200
        inquiry_data = inquiry_200.json()
        assert inquiry_data["bank_reference_id"] == data1["bank_reference_id"]

        # 4. Phase 2 Duplicate Settlement: Returns identical cached record (idempotency guarantee)
        settle_dup_resp = await client.post("/v1/wires/settle", json=payload)
        assert settle_dup_resp.status_code == 200
        data2 = settle_dup_resp.json()
        assert data2["bank_reference_id"] == data1["bank_reference_id"]
        assert data2["settled_at"] == data1["settled_at"]


@pytest.mark.asyncio
async def test_aliased_fedwire_endpoints() -> None:
    """Verify legacy or alternate Fedwire path aliases work identically."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        idempotency_key = "idemp-alias-test-200"

        # 1. Alias settle endpoint: /api/v1/fedwire/disburse
        payload = {
            "idempotency_key": idempotency_key,
            "amount_cents": 1000000,
            "currency": "USD",
            "beneficiary_account_mask": "******9999",
            "routing_number": "121000358",
            "swift_bic": "BOFAUS3NXXX",
            "disbursement_token": "tok_alias_456",
        }
        settle_resp = await client.post("/api/v1/fedwire/disburse", json=payload)
        assert settle_resp.status_code == 200
        assert settle_resp.json()["bank_reference_id"].startswith("FED-WIRE-")

        # 2. Alias inquiry endpoint: /api/v1/fedwire/disburse/{key}
        inquiry_resp = await client.get(f"/api/v1/fedwire/disburse/{idempotency_key}")
        assert inquiry_resp.status_code == 200
        assert inquiry_resp.json()["idempotency_key"] == idempotency_key


@pytest.mark.asyncio
async def test_chaos_outage_simulation() -> None:
    """Verify artificial 503 outage injection via headers and query parameters."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "idempotency_key": "idemp-chaos-test-300",
            "amount_cents": 750000,
            "currency": "USD",
            "beneficiary_account_mask": "******3333",
            "routing_number": "121000358",
            "swift_bic": "CHASUS33XXX",
            "disbursement_token": "tok_chaos_789",
        }

        # 1. Via X-Simulate-Outage header
        resp_hdr = await client.post(
            "/v1/wires/settle",
            json=payload,
            headers={"X-Simulate-Outage": "true"},
        )
        assert resp_hdr.status_code == 503
        assert resp_hdr.headers.get("retry-after") == "5"

        # 2. Via simulate_failure query param
        resp_param = await client.post(
            "/v1/wires/settle?simulate_failure=true",
            json=payload,
        )
        assert resp_param.status_code == 503
        assert resp_param.headers.get("retry-after") == "5"
