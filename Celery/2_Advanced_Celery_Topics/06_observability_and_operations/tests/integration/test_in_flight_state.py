"""Integration test verifying FinTech In-Flight State Visibility contract (TC-12).

Guarantees zero observable black holes: immediately after receiving HTTP 202 Accepted,
querying GET /api/v1/screenings/{id} returns HTTP 200 OK with status="processing".
"""

import uuid

import httpx
import pytest


@pytest.mark.asyncio
async def test_fintech_in_flight_state_visibility(client: httpx.AsyncClient) -> None:
    """Verify in-flight state is immediately observable without any 404 race window."""
    tx_id = f"tx-inflight-{uuid.uuid4().hex[:8]}"
    payload = {
        "transaction_id": tx_id,
        "account_id": "acct-treasury-009",
        "amount": 9990.00,
        "currency": "USD",
        "client_ip": "10.50.0.12",
        "entity_name": "Treasury Holdings AG",
        "velocity_5m_count": 1,
    }

    # 1. Trigger asynchronous ingestion
    res_post = await client.post("/api/v1/screenings", json=payload)
    assert res_post.status_code == 202
    screening_id = res_post.json()["id"]

    # 2. Immediately execute read query before worker completes
    res_get = await client.get(f"/api/v1/screenings/{screening_id}")

    # 3. Mandate: must return HTTP 200 OK, not HTTP 404
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["id"] == screening_id
    assert data["status"] == "processing"
    assert data["transaction_id"] == tx_id
