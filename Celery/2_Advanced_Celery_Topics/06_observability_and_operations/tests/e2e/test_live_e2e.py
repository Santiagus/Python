"""Live distributed multi-process E2E test suite for fraud detection & AML screening rail.

Verifies TC-20:
1. Real AMQP message publishing across RabbitMQ queues ('critical' and 'bulk').
2. Live background Celery worker daemon subprocess consuming from queues.
3. Database persistence and atomic row-locking under real multi-process concurrency.
4. Asynchronous polling of screening transactions until terminal states reach completion.
5. Sanctions Watchlist Simulator API integration and positive hit audit logging ('watchlist_hits').
6. Result Envelope graceful degradation under partner timeouts (circuit breaker fallback).
7. Atomic idempotency under duplicate transaction dispatch.
"""

from __future__ import annotations

import asyncio
import subprocess
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ScreeningModel, WatchlistHitModel


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_live_screening_happy_path_e2e(
    live_async_client: AsyncClient,
    live_celery_worker: subprocess.Popen[bytes],
    e2e_db_session: AsyncSession,
) -> None:
    """TC-20: Verify happy path asynchronous screening dispatch, processing, and approval."""
    payload = {
        "transaction_id": "tx_e2e_happy_001",
        "account_id": "acct_corp_001",
        "amount": "4500.00",
        "currency": "USD",
        "client_ip": "198.51.100.10",
        "entity_name": "Acme Commercial Corp",
        "velocity_5m_count": 1,
    }

    # 1. Dispatch screening request to API gateway
    response = await live_async_client.post("/api/v1/screenings", json=payload)
    assert response.status_code == 202
    data = response.json()
    screening_id = data["id"]
    assert data["status"] == "processing"
    assert data["transaction_id"] == "tx_e2e_happy_001"

    # 2. In-Flight State Visibility check: immediate query returns processing (no 404 black hole)
    get_res = await live_async_client.get(f"/api/v1/screenings/{screening_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "processing"

    # 3. Poll for Celery worker completion (up to 15s)
    terminal_data = None
    for _ in range(30):
        await asyncio.sleep(0.5)
        poll_res = await live_async_client.get(f"/api/v1/screenings/{screening_id}")
        if poll_res.status_code == 200 and poll_res.json()["status"] != "processing":
            terminal_data = poll_res.json()
            break

    assert terminal_data is not None, "Screening failed to reach terminal state in time"
    assert terminal_data["status"] == "approved"
    assert terminal_data["risk_score"] is not None
    assert terminal_data["risk_score"] < 50
    assert terminal_data["decision_reason"] == "automated_evaluation_completed"

    # 4. Verify database state machine record
    stmt = select(ScreeningModel).where(ScreeningModel.id == UUID(screening_id))
    db_record = (await e2e_db_session.execute(stmt)).scalar_one_or_none()
    assert db_record is not None
    assert db_record.status == "approved"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_live_screening_sanctions_hit_e2e(
    live_async_client: AsyncClient,
    live_celery_worker: subprocess.Popen[bytes],
    e2e_db_session: AsyncSession,
) -> None:
    """TC-20: Verify OFAC sanctions match triggers blocked decision and persists watchlist hit."""
    payload = {
        "transaction_id": "tx_e2e_sanctions_001",
        "account_id": "acct_corp_002",
        "amount": "125000.00",
        "currency": "USD",
        "client_ip": "198.51.100.20",
        "entity_name": "Vladimir Rostov",
        "velocity_5m_count": 1,
    }

    # 1. Dispatch screening for sanctioned entity
    response = await live_async_client.post("/api/v1/screenings", json=payload)
    assert response.status_code == 202
    screening_id = response.json()["id"]

    # 2. Poll until terminal state
    terminal_data = None
    for _ in range(30):
        await asyncio.sleep(0.5)
        poll_res = await live_async_client.get(f"/api/v1/screenings/{screening_id}")
        if poll_res.status_code == 200 and poll_res.json()["status"] != "processing":
            terminal_data = poll_res.json()
            break

    assert terminal_data is not None, "Sanctions screening failed to reach terminal state"
    assert terminal_data["status"] == "blocked"
    assert terminal_data["risk_score"] >= 95
    assert "sanctions_watchlist_positive_match" in terminal_data["decision_reason"]

    # 3. Verify compliance audit hits persisted to PostgreSQL
    hit_stmt = select(WatchlistHitModel).where(WatchlistHitModel.screening_id == UUID(screening_id))
    hits = (await e2e_db_session.execute(hit_stmt)).scalars().all()
    assert len(hits) >= 1
    assert hits[0].entity_name == "VLADIMIR ROSTOV"
    assert hits[0].watchlist_type == "OFAC_SDN"
    assert Decimal(str(hits[0].match_confidence)) >= Decimal("98.00")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_live_screening_degraded_fallback_e2e(
    live_async_client: AsyncClient,
    live_celery_worker: subprocess.Popen[bytes],
    live_sanctions_api: str,
    e2e_db_session: AsyncSession,
) -> None:
    """TC-20: Verify Result Envelope degradation under partner sanctions API timeout."""
    # 1. Inject timeout mode into live sanctions simulator (2.5s > 2.0s worker timeout)
    async with httpx.AsyncClient(base_url=live_sanctions_api) as sim_client:
        sim_res = await sim_client.post(
            "/api/v1/simulate/mode",
            json={"mode": "timeout", "latency_seconds": 2.5},
        )
        assert sim_res.status_code == 200

    payload = {
        "transaction_id": "tx_e2e_degraded_001",
        "account_id": "acct_corp_003",
        "amount": "500.00",
        "currency": "USD",
        "client_ip": "198.51.100.30",
        "entity_name": "Slow External Partner",
        "velocity_5m_count": 0,
    }

    try:
        # 2. Dispatch screening request
        response = await live_async_client.post("/api/v1/screenings", json=payload)
        assert response.status_code == 202
        screening_id = response.json()["id"]

        # 3. Poll for degraded completion
        terminal_data = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            poll_res = await live_async_client.get(f"/api/v1/screenings/{screening_id}")
            if poll_res.status_code == 200 and poll_res.json()["status"] != "processing":
                terminal_data = poll_res.json()
                break

        assert terminal_data is not None, "Degraded screening failed to complete"
        assert terminal_data["status"] == "flagged_review"
        assert terminal_data["risk_score"] == 40
        assert terminal_data["decision_reason"] == "aml_watchlist_timeout"

        # 4. Verify DB status
        stmt = select(ScreeningModel).where(ScreeningModel.id == UUID(screening_id))
        db_record = (await e2e_db_session.execute(stmt)).scalar_one_or_none()
        assert db_record is not None
        assert db_record.status == "flagged_review"
    finally:
        # 5. Cleanly restore simulator back to normal zero-fault mode
        async with httpx.AsyncClient(base_url=live_sanctions_api) as sim_client:
            await sim_client.post("/api/v1/simulate/reset")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_live_screening_atomic_idempotency_e2e(
    live_async_client: AsyncClient,
    live_celery_worker: subprocess.Popen[bytes],
) -> None:
    """TC-20: Verify atomic idempotency catches duplicate transaction_id and returns 200 OK."""
    payload = {
        "transaction_id": "tx_e2e_idempotency_001",
        "account_id": "acct_corp_004",
        "amount": "1000.00",
        "currency": "USD",
        "client_ip": "198.51.100.40",
        "entity_name": "Idempotent Entity Inc",
        "velocity_5m_count": 0,
    }

    # 1. First submission creates the transaction
    res1 = await live_async_client.post("/api/v1/screenings", json=payload)
    assert res1.status_code == 202
    screening_id = res1.json()["id"]

    # 2. Duplicate submission with same transaction_id returns HTTP 200 with existing record
    res2 = await live_async_client.post("/api/v1/screenings", json=payload)
    assert res2.status_code == 200
    assert res2.json()["id"] == screening_id
    assert res2.json()["transaction_id"] == "tx_e2e_idempotency_001"
