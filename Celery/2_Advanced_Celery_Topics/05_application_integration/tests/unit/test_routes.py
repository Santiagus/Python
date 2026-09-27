"""Unit tests for FastAPI card dispute routes and lifecycle transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.models import CardDispute
from app.routes import cancel_dispute, create_dispute, get_dispute, health_check, retry_dispute
from app.schemas import DisputeCreateRequest, DisputeReason, DisputeStatus


def _create_mock_session(dispute: CardDispute | None = None) -> AsyncMock:
    """Build an AsyncMock database session returning a pre-configured dispute."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    mock_scalars = MagicMock()
    mock_scalars.first.return_value = dispute

    mock_res = MagicMock()
    mock_res.scalars.return_value = mock_scalars

    mock_session.execute = AsyncMock(return_value=mock_res)
    return mock_session


@pytest.mark.asyncio
async def test_health_check() -> None:
    """Verify health_check endpoint pings database and returns 200 OK."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()
    result = await health_check(session=mock_session)
    assert result["status"] == "ok"
    assert result["database"] == "connected"
    assert mock_session.execute.called


@pytest.mark.asyncio
async def test_create_dispute_happy_path() -> None:
    """Verify create_dispute commits in-flight record, dispatches task, and returns 202."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock()

    payload = DisputeCreateRequest(
        transaction_id="tx_test_12345",
        card_token="tok_card_test_999",
        card_last_four="4242",
        amount=Decimal("150.00"),
        currency="USD",
        reason=DisputeReason.fraudulent,
        evidence_notes="Fraudulent transaction notes",
    )

    with patch("app.routes.dispatch_dispute_submission", return_value="celery-task-123") as mock_dispatch:
        response = await create_dispute(
            payload=payload,
            session=mock_session,
            _="valid_key",
            simulate_failure=False,
        )

    assert response.status == DisputeStatus.processing
    assert response.transaction_id == "tx_test_12345"
    assert response.celery_task_id == "celery-task-123"
    assert response.amount == Decimal("150.00")
    assert response.amount_cents == 15000
    assert mock_dispatch.called
    assert mock_session.add.called
    assert mock_session.commit.call_count == 2


@pytest.mark.asyncio
async def test_create_dispute_idempotency_conflict() -> None:
    """Verify create_dispute raises HTTP 409 Conflict when transaction_id is already disputed."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock(side_effect=IntegrityError("duplicate key", params={}, orig=Exception()))
    mock_session.rollback = AsyncMock()

    payload = DisputeCreateRequest(
        transaction_id="tx_test_duplicate",
        card_token="tok_card_test_999",
        card_last_four="4242",
        amount=Decimal("50.00"),
        currency="USD",
        reason=DisputeReason.duplicate,
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_dispute(
            payload=payload,
            session=mock_session,
            _="valid_key",
            simulate_failure=False,
        )

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in exc_info.value.detail
    assert mock_session.rollback.called


@pytest.mark.asyncio
async def test_get_dispute_found() -> None:
    """Verify get_dispute retrieves and maps active dispute record."""
    dispute_id = uuid4()
    mock_dispute = CardDispute(
        id=dispute_id,
        transaction_id="tx_test_found",
        card_token="tok_card_123",
        card_last_four="1234",
        amount_cents=10000,
        currency="USD",
        reason="fraudulent",
        status="processing",
        celery_task_id="task-123",
        network_reference_id=None,
        attempt_count=1,
        error_message=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mock_session = _create_mock_session(mock_dispute)
    response = await get_dispute(dispute_id=dispute_id, session=mock_session, _="valid_key")
    assert response.id == dispute_id
    assert response.amount == Decimal("100.00")
    assert response.status == DisputeStatus.processing


@pytest.mark.asyncio
async def test_get_dispute_not_found() -> None:
    """Verify get_dispute raises HTTP 404 when dispute does not exist."""
    mock_session = _create_mock_session(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_dispute(dispute_id=uuid4(), session=mock_session, _="valid_key")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_cancel_dispute_happy_path() -> None:
    """Verify cancel_dispute transitions in-flight status to cancelled and revokes worker task."""
    dispute_id = uuid4()
    mock_dispute = CardDispute(
        id=dispute_id,
        status="processing",
        celery_task_id="task-in-flight-999",
        updated_at=datetime.now(timezone.utc),
    )

    mock_session = _create_mock_session(mock_dispute)

    with patch("app.routes.revoke_dispute_task") as mock_revoke:
        response = await cancel_dispute(dispute_id=dispute_id, session=mock_session, _="valid_key")

    assert response.id == dispute_id
    assert response.status == DisputeStatus.cancelled
    assert response.revoked_task_id == "task-in-flight-999"
    assert mock_dispute.status == "cancelled"
    assert mock_revoke.called
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_cancel_dispute_not_found() -> None:
    """Verify cancel_dispute raises HTTP 404 when dispute is missing."""
    mock_session = _create_mock_session(None)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_dispute(dispute_id=uuid4(), session=mock_session, _="valid_key")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_cancel_dispute_terminal_conflict() -> None:
    """Verify cancel_dispute raises HTTP 409 Conflict if dispute reached terminal state."""
    mock_dispute = CardDispute(
        id=uuid4(),
        status="submitted_to_network",
        celery_task_id="task-done-111",
    )
    mock_session = _create_mock_session(mock_dispute)

    with pytest.raises(HTTPException) as exc_info:
        await cancel_dispute(dispute_id=mock_dispute.id, session=mock_session, _="valid_key")

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "Cannot cancel dispute in terminal state" in exc_info.value.detail


@pytest.mark.asyncio
async def test_retry_dispute_happy_path() -> None:
    """Verify retry_dispute increments attempt count, enqueues fresh task, and returns 200."""
    dispute_id = uuid4()
    mock_dispute = CardDispute(
        id=dispute_id,
        status="failed",
        attempt_count=1,
        celery_task_id="task-old-failed",
        error_message="clearinghouse timeout",
        updated_at=datetime.now(timezone.utc),
    )
    mock_session = _create_mock_session(mock_dispute)

    with patch("app.routes.dispatch_dispute_submission", return_value="task-new-retry") as mock_dispatch:
        response = await retry_dispute(
            dispute_id=dispute_id,
            session=mock_session,
            _="valid_key",
            simulate_failure=False,
        )

    assert response.id == dispute_id
    assert response.status == DisputeStatus.processing
    assert response.attempt_count == 2
    assert response.celery_task_id == "task-new-retry"
    assert mock_dispute.error_message is None
    assert mock_dispatch.called
    assert mock_session.commit.called


@pytest.mark.asyncio
async def test_retry_dispute_not_found() -> None:
    """Verify retry_dispute raises HTTP 404 if dispute ID does not exist."""
    mock_session = _create_mock_session(None)

    with pytest.raises(HTTPException) as exc_info:
        await retry_dispute(dispute_id=uuid4(), session=mock_session, _="valid_key")

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_retry_dispute_non_failed_conflict() -> None:
    """Verify retry_dispute raises HTTP 409 Conflict if dispute status is not failed."""
    mock_dispute = CardDispute(
        id=uuid4(),
        status="processing",
        attempt_count=1,
    )
    mock_session = _create_mock_session(mock_dispute)

    with pytest.raises(HTTPException) as exc_info:
        await retry_dispute(dispute_id=mock_dispute.id, session=mock_session, _="valid_key")

    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "Only failed disputes can be retried" in exc_info.value.detail
