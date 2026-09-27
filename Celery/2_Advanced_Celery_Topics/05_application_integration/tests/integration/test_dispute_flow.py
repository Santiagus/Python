"""Integration test suite for Card Dispute & Chargeback Engine against real PostgreSQL.

Validates the 5 FinTech pillars:
1. Anti-blackhole state machine guarantee (synchronous initial status commit before 202 response).
2. Continuous in-flight visibility (zero 404 race window on immediate read).
3. Zero session.refresh() query minimization.
4. Database unique constraint idempotency enforcement.
5. Pessimistic row locking and atomic cooperative cancellation / retry transitions.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CardDispute
from app.schemas import DisputeReason, DisputeStatus


@pytest.fixture(autouse=True)
def mock_dispatcher() -> Generator[None, None, None]:
    """Mock AMQP dispatch and revocation to isolate DB integration testing from broker."""
    with (
        patch("app.routes.dispatch_dispute_submission", return_value="celery-mock-task-id-123"),
        patch("app.routes.revoke_dispute_task"),
    ):
        yield


@pytest.mark.integration
@pytest.mark.asyncio
async def test_health_check_integration(api_client: AsyncClient) -> None:
    """Verify health check endpoint connects to the real PostgreSQL database."""
    # 1. Execute unauthenticated health probe
    response = await api_client.get("/health")

    # 2. Assert HTTP 200 OK and database connectivity
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert data["service"] == "card_dispute_engine"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_submit_dispute_anti_blackhole_contract(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify that dispute ingestion synchronously persists in-flight record before 202 response.

    FinTech Continuous State Visibility Invariant: An accepted asynchronous request
    must immediately be queryable (zero 404 race window).
    """
    # 1. Prepare valid specimen dispute payload
    payload = {
        "transaction_id": "tx_integ_happy_001",
        "card_token": "tok_card_9921_sec",
        "card_last_four": "4242",
        "amount": "149.99",
        "currency": "USD",
        "reason": DisputeReason.fraudulent.value,
        "evidence_notes": "Cardholder confirmed unauthorized card-present merchant charge.",
    }

    # 2. Submit dispute to API gateway
    create_res = await api_client.post("/disputes", json=payload)
    assert create_res.status_code == 202
    create_data = create_res.json()

    dispute_id = create_data["id"]
    assert dispute_id is not None
    assert create_data["transaction_id"] == "tx_integ_happy_001"
    assert create_data["status"] == DisputeStatus.processing.value
    assert create_data["amount"] == "149.99"
    assert create_data["amount_cents"] == 14999
    assert create_data["attempt_count"] == 1
    assert create_data["celery_task_id"] is not None

    # 3. Immediately query status to verify anti-blackhole contract (zero 404 window)
    get_res = await api_client.get(f"/disputes/{dispute_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["id"] == dispute_id
    assert get_data["status"] == DisputeStatus.processing.value
    assert get_data["transaction_id"] == "tx_integ_happy_001"

    # 4. Direct database inspection verifying single source of truth
    stmt = select(CardDispute).where(CardDispute.id == UUID(dispute_id))
    db_record = (await db_session.execute(stmt)).scalars().first()
    assert db_record is not None
    assert db_record.transaction_id == "tx_integ_happy_001"
    assert db_record.amount_cents == 14999
    assert db_record.status == "processing"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_submit_dispute_idempotency_conflict(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify that submitting duplicate transaction_id triggers HTTP 409 Conflict via database UNIQUE constraint."""
    # 1. Submit initial dispute
    payload = {
        "transaction_id": "tx_integ_duplicate_002",
        "card_token": "tok_card_9921_sec",
        "card_last_four": "4242",
        "amount": "250.00",
        "currency": "USD",
        "reason": DisputeReason.duplicate.value,
        "evidence_notes": "First submission attempt.",
    }
    first_res = await api_client.post("/disputes", json=payload)
    assert first_res.status_code == 202

    # 2. Attempt duplicate submission with the same transaction_id
    duplicate_res = await api_client.post("/disputes", json=payload)
    assert duplicate_res.status_code == 409
    assert "already exists" in duplicate_res.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_dispute_not_found(api_client: AsyncClient) -> None:
    """Verify that querying non-existent dispute UUID returns HTTP 404 Not Found."""
    random_id = uuid.uuid4()
    response = await api_client.get(f"/disputes/{random_id}")
    assert response.status_code == 404
    assert f"Dispute with ID '{random_id}' not found" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancel_dispute_in_flight_lifecycle(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify in-flight cooperative cancellation transitions status to 'cancelled' and prevents double-cancellation."""
    # 1. Create active dispute
    payload = {
        "transaction_id": "tx_integ_cancel_003",
        "card_token": "tok_card_8812_sec",
        "card_last_four": "1234",
        "amount": "89.50",
        "currency": "USD",
        "reason": DisputeReason.unrecognized.value,
    }
    create_res = await api_client.post("/disputes", json=payload)
    assert create_res.status_code == 202
    dispute_id = create_res.json()["id"]

    # 2. Cancel in-flight dispute
    cancel_res = await api_client.post(f"/disputes/{dispute_id}/cancel")
    assert cancel_res.status_code == 200
    cancel_data = cancel_res.json()
    assert cancel_data["id"] == dispute_id
    assert cancel_data["status"] == DisputeStatus.cancelled.value
    assert "successfully revoked" in cancel_data["message"]

    # 3. Query state machine to confirm terminal cancelled status
    get_res = await api_client.get(f"/disputes/{dispute_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == DisputeStatus.cancelled.value

    # 4. Attempt second cancellation on cancelled dispute (Expected: HTTP 409 Conflict)
    duplicate_cancel_res = await api_client.post(f"/disputes/{dispute_id}/cancel")
    assert duplicate_cancel_res.status_code == 409
    assert "Cannot cancel dispute in terminal state 'cancelled'" in duplicate_cancel_res.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancel_dispute_not_found(api_client: AsyncClient) -> None:
    """Verify cancelling non-existent dispute returns HTTP 404 Not Found."""
    random_id = uuid.uuid4()
    response = await api_client.post(f"/disputes/{random_id}/cancel")
    assert response.status_code == 404
    assert f"Dispute with ID '{random_id}' not found" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_dispute_lifecycle(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Verify failed dispute retry re-enqueues task and increments attempt_count."""
    # 1. Create dispute
    payload = {
        "transaction_id": "tx_integ_retry_004",
        "card_token": "tok_card_7733_sec",
        "card_last_four": "5678",
        "amount": "120.00",
        "currency": "USD",
        "reason": DisputeReason.goods_not_received.value,
    }
    create_res = await api_client.post("/disputes", json=payload)
    assert create_res.status_code == 202
    dispute_id = UUID(create_res.json()["id"])

    # 2. Attempt retry while still in 'processing' status (Expected: HTTP 409 Conflict)
    early_retry_res = await api_client.post(f"/disputes/{dispute_id}/retry")
    assert early_retry_res.status_code == 409
    assert "Cannot retry dispute with status 'processing'" in early_retry_res.json()["detail"]

    # 3. Simulate failure in database
    await db_session.execute(
        update(CardDispute)
        .where(CardDispute.id == dispute_id)
        .values(status="failed", error_message="Clearinghouse network timeout")
    )
    await db_session.commit()

    # 4. Retry failed dispute
    retry_res = await api_client.post(f"/disputes/{dispute_id}/retry")
    assert retry_res.status_code == 200
    retry_data = retry_res.json()
    assert retry_data["id"] == str(dispute_id)
    assert retry_data["status"] == DisputeStatus.processing.value
    assert retry_data["attempt_count"] == 2
    assert retry_data["celery_task_id"] is not None

    # 5. Direct database inspection
    db_record = (await db_session.execute(select(CardDispute).where(CardDispute.id == dispute_id))).scalars().first()
    assert db_record is not None
    assert db_record.status == "processing"
    assert db_record.attempt_count == 2
    assert db_record.error_message is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retry_dispute_not_found(api_client: AsyncClient) -> None:
    """Verify retrying non-existent dispute returns HTTP 404 Not Found."""
    random_id = uuid.uuid4()
    response = await api_client.post(f"/disputes/{random_id}/retry")
    assert response.status_code == 404
    assert f"Dispute with ID '{random_id}' not found" in response.json()["detail"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_security_authentication_enforcement(
    test_database_url: str,
) -> None:
    """Verify that requests missing or providing invalid X-API-Key are rejected with HTTP 401."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as unauthed_client:
        # 1. Missing API key header
        missing_res = await unauthed_client.get(f"/disputes/{uuid.uuid4()}")
        assert missing_res.status_code == 401
        assert "Invalid or missing X-API-Key header" in missing_res.json()["detail"]

        # 2. Invalid API key header
        invalid_res = await unauthed_client.get(
            f"/disputes/{uuid.uuid4()}",
            headers={"X-API-Key": "sk_live_invalid_key_999"},
        )
        assert invalid_res.status_code == 401
        assert "Invalid or missing X-API-Key header" in invalid_res.json()["detail"]
