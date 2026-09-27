"""Integration tests for payment screening ingestion and atomic idempotency (TC-12, TC-13)."""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest
from app.models import ScreeningModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_create_screening_success(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    mock_dispatcher: MagicMock,
) -> None:
    """TC-12: Ingest transaction, persist status='processing', and trigger canvas."""
    tx_id = f"tx-test-{uuid.uuid4().hex[:8]}"
    payload = {
        "transaction_id": tx_id,
        "account_id": "acct-test-001",
        "amount": 1500.50,
        "currency": "usd",
        "client_ip": "192.168.1.50",
        "entity_name": "Standard Corp LLC",
        "velocity_5m_count": 1,
    }

    # 1. Dispatch request to FastAPI endpoint
    response = await client.post("/api/v1/screenings", json=payload)
    assert response.status_code == 202
    data = response.json()

    # 2. Assert response fields and initial state machine value
    assert data["transaction_id"] == tx_id
    assert data["status"] == "processing"
    assert Decimal(str(data["amount"])) == Decimal("1500.50")
    assert data["currency"] == "USD"
    assert "id" in data
    screening_id = uuid.UUID(data["id"])

    # 3. Assert Celery canvas was dispatched
    mock_dispatcher.assert_called_once()
    assert mock_dispatcher.call_args.kwargs["screening_id"] == screening_id

    # 4. Verify database persistence directly
    stmt = select(ScreeningModel).where(ScreeningModel.id == screening_id)
    res = await db_session.execute(stmt)
    persisted = res.scalar_one()
    assert persisted.status == "processing"
    assert persisted.amount_cents == 150050


@pytest.mark.asyncio
async def test_create_screening_atomic_idempotency_duplicate(
    client: httpx.AsyncClient,
    mock_dispatcher: MagicMock,
) -> None:
    """TC-13: Duplicate transaction submission returns HTTP 200 OK with existing record."""
    tx_id = f"tx-duplicate-{uuid.uuid4().hex[:8]}"
    payload = {
        "transaction_id": tx_id,
        "account_id": "acct-dup-99",
        "amount": 2500.00,
        "currency": "USD",
        "client_ip": "10.0.0.1",
        "entity_name": "Duplicate Trader LLC",
        "velocity_5m_count": 2,
    }

    # 1. First submission (HTTP 202 Accepted)
    res1 = await client.post("/api/v1/screenings", json=payload)
    assert res1.status_code == 202
    id1 = res1.json()["id"]
    assert mock_dispatcher.call_count == 1

    # 2. Second submission with identical transaction_id (HTTP 200 OK)
    res2 = await client.post("/api/v1/screenings", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()

    # 3. Assert idempotent return of the identical screening ID without second dispatch
    assert data2["id"] == id1
    assert data2["transaction_id"] == tx_id
    assert mock_dispatcher.call_count == 1


@pytest.mark.asyncio
async def test_create_screening_validation_errors(client: httpx.AsyncClient) -> None:
    """Verify validation constraints return HTTP 422 Unprocessable Entity."""
    # Negative amount
    res_neg = await client.post(
        "/api/v1/screenings",
        json={
            "transaction_id": "tx-val-01",
            "account_id": "acct-val-01",
            "amount": -50.00,
            "currency": "USD",
            "client_ip": "127.0.0.1",
            "entity_name": "Valid Corp",
        },
    )
    assert res_neg.status_code == 422

    # Short entity name
    res_short = await client.post(
        "/api/v1/screenings",
        json={
            "transaction_id": "tx-val-02",
            "account_id": "acct-val-02",
            "amount": 100.00,
            "currency": "USD",
            "client_ip": "127.0.0.1",
            "entity_name": "A",
        },
    )
    assert res_short.status_code == 422


@pytest.mark.asyncio
async def test_get_screening_not_found(client: httpx.AsyncClient) -> None:
    """Verify querying non-existent screening returns HTTP 404."""
    random_id = uuid.uuid4()
    response = await client.get(f"/api/v1/screenings/{random_id}")
    assert response.status_code == 404
    assert f"'{random_id}' not found" in response.json()["detail"]


def test_dispatch_screening_workflow_unit() -> None:
    """TC-07: Verify Celery canvas assembly, correlation header injection, and errback linkage."""
    from app.dispatcher import dispatch_screening_workflow
    from app.schemas import ScreeningRequest

    req = ScreeningRequest(
        transaction_id="tx-disp-1234",
        account_id="acct-disp-5678",
        amount=Decimal("150.00"),
        currency="USD",
        client_ip="192.168.1.1",
        entity_name="Dispatcher Test Corp",
        velocity_5m_count=1,
    )
    s_id = uuid.uuid4()

    with patch("app.dispatcher.chain") as mock_chain:
        mock_workflow = MagicMock()
        mock_chain.return_value = mock_workflow

        res = dispatch_screening_workflow(
            screening_id=s_id, request=req, correlation_id="trace-abc-123"
        )
        assert res == mock_workflow.apply_async.return_value
        mock_workflow.apply_async.assert_called_once()
        call_kwargs = mock_workflow.apply_async.call_args.kwargs
        assert call_kwargs["headers"] == {"X-Request-ID": "trace-abc-123"}
        assert "link_error" in call_kwargs


@pytest.mark.asyncio
async def test_create_screening_query_minimization_and_zero_refresh(
    client: httpx.AsyncClient,
    query_recorder: list[str],
) -> None:
    """TC-19: Verify exactly 1 SQL INSERT is executed (no speculative SELECT, no post-insert refresh)."""
    tx_id = f"tx-query-min-{uuid.uuid4().hex[:8]}"
    payload = {
        "transaction_id": tx_id,
        "account_id": "acct-test-query-001",
        "amount": 250.00,
        "currency": "usd",
        "client_ip": "10.0.0.1",
        "entity_name": "Minimal Query Corp",
        "velocity_5m_count": 0,
    }

    # 1. Clear any prior statements from initialization
    query_recorder.clear()

    # 2. Dispatch request to FastAPI endpoint
    response = await client.post("/api/v1/screenings", json=payload)
    assert response.status_code == 202

    # 3. Filter out savepoint/transaction management statements if any
    data_queries = [
        q
        for q in query_recorder
        if not q.upper().startswith("SAVEPOINT")
        and not q.upper().startswith("RELEASE")
        and not q.upper().startswith("ROLLBACK")
    ]

    # 4. Assert exactly 1 INSERT query was executed
    assert len(data_queries) == 1
    assert data_queries[0].upper().startswith("INSERT INTO SCREENINGS")
    # Verify no speculative SELECT and no session.refresh() SELECT was issued
    assert not any(q.upper().startswith("SELECT") for q in data_queries)
