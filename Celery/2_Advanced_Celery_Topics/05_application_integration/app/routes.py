"""Card dispute lifecycle FastAPI endpoints.

Implements the 5 FinTech architectural pillars:
1. Anti-blackhole state machine (synchronous initial status commit before 202 response).
2. Query minimization (zero session.refresh() calls, application-layer response instantiation).
3. Minor-unit integer cents arithmetic.
4. Race-free cooperative cancellation and atomic state transitions.
5. Constant-time API Key security.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Security, status
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.dispatcher import dispatch_dispute_submission, revoke_dispute_task
from app.models import CardDispute
from app.schemas import (
    DisputeCancelResponse,
    DisputeCreateRequest,
    DisputeResponse,
    DisputeRetryResponse,
    DisputeStatus,
    from_cents,
)
from app.security import get_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Disputes"])


@router.post(
    "/disputes",
    response_model=DisputeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a card transaction dispute",
    description=(
        "Ingests a card dispute, validates payload constraints, synchronously persists an initial "
        "'processing' state record to eliminate the 404 race window (anti-blackhole contract), "
        "and dispatches a background worker task to transmit evidence to the clearinghouse."
    ),
)
async def create_dispute(
    payload: DisputeCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[str, Security(get_api_key)],
    simulate_failure: Annotated[
        bool,
        Query(
            description="Diagnostic flag to simulate clearinghouse network timeout in worker",
        ),
    ] = False,
) -> DisputeResponse:
    """Submit a card transaction dispute for asynchronous processing.

    Args:
        payload: Dispute creation parameters with minor-unit financial precision.
        session: Active asynchronous database session.
        _: Validated API key security dependency.
        simulate_failure: Diagnostic flag to test failure and retry workflows.

    Returns:
        DisputeResponse: Immediate in-flight state machine representation with HTTP 202.

    Raises:
        HTTPException: HTTP 409 Conflict if transaction_id is already disputed.
    """
    # 1. Pre-generate primary key and UTC timestamp in application memory
    dispute_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    amount_cents = payload.amount_cents

    # 2. Construct ORM model with initial processing status
    dispute = CardDispute(
        id=dispute_id,
        transaction_id=payload.transaction_id,
        card_token=payload.card_token,
        card_last_four=payload.card_last_four,
        amount_cents=amount_cents,
        currency=payload.currency.upper(),
        reason=payload.reason.value,
        evidence_notes=payload.evidence_notes,
        status="processing",
        attempt_count=1,
        created_at=now,
        updated_at=now,
    )
    session.add(dispute)

    # 3. Synchronously commit initial state to enforce anti-blackhole contract
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        logger.warning(
            "dispute_idempotency_conflict",
            extra={"transaction_id": str(payload.transaction_id)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dispute already exists for transaction_id '{payload.transaction_id}'",
        )

    # 4. Dispatch AMQP message to Celery worker fleet with correlation context
    task_id = dispatch_dispute_submission(
        dispute_id=str(dispute_id),
        simulate_failure=simulate_failure,
    )

    # 5. Persist Celery task ID in background without re-fetching full row
    await session.execute(
        update(CardDispute)
        .where(CardDispute.id == dispute_id)
        .values(celery_task_id=task_id, updated_at=datetime.now(timezone.utc))
    )
    await session.commit()

    # 6. Instantiate response directly from application memory (zero session.refresh())
    return DisputeResponse(
        id=dispute_id,
        transaction_id=payload.transaction_id,
        card_token=payload.card_token,
        card_last_four=payload.card_last_four,
        amount_cents=amount_cents,
        amount=payload.amount,
        currency=payload.currency.upper(),
        reason=payload.reason.value,
        status=DisputeStatus.processing,
        celery_task_id=task_id,
        network_reference_id=None,
        attempt_count=1,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


@router.get(
    "/disputes/{dispute_id}",
    response_model=DisputeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get dispute status and details",
    description="Queries the single source of truth database record for active or terminal dispute state.",
)
async def get_dispute(
    dispute_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[str, Security(get_api_key)],
) -> DisputeResponse:
    """Retrieve current state machine status and attributes of a dispute.

    Args:
        dispute_id: UUID of the dispute to inspect.
        session: Active asynchronous database session.
        _: Validated API key security dependency.

    Returns:
        DisputeResponse: Populated dispute state machine data.

    Raises:
        HTTPException: HTTP 404 Not Found if dispute does not exist.
    """
    stmt = select(CardDispute).where(CardDispute.id == dispute_id)
    result = await session.execute(stmt)
    dispute = result.scalars().first()

    if not dispute:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispute with ID '{dispute_id}' not found",
        )

    return DisputeResponse(
        id=dispute.id,
        transaction_id=dispute.transaction_id,
        card_token=dispute.card_token,
        card_last_four=dispute.card_last_four,
        amount_cents=dispute.amount_cents,
        amount=from_cents(dispute.amount_cents),
        currency=dispute.currency,
        reason=dispute.reason,
        status=DisputeStatus(dispute.status),
        celery_task_id=dispute.celery_task_id,
        network_reference_id=dispute.network_reference_id,
        attempt_count=dispute.attempt_count,
        error_message=dispute.error_message,
        created_at=dispute.created_at,
        updated_at=dispute.updated_at,
    )


@router.post(
    "/disputes/{dispute_id}/cancel",
    response_model=DisputeCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an in-flight dispute",
    description=(
        "Cancels an active dispute prior to network transmission, transitioning status to 'cancelled' "
        "and broadcasting a SIGTERM revocation to the worker executing the task."
    ),
)
async def cancel_dispute(
    dispute_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[str, Security(get_api_key)],
) -> DisputeCancelResponse:
    """Cancel an in-flight dispute and revoke its Celery worker task.

    Args:
        dispute_id: UUID of the dispute to cancel.
        session: Active asynchronous database session.
        _: Validated API key security dependency.

    Returns:
        DisputeCancelResponse: Cancellation confirmation and timestamp.

    Raises:
        HTTPException: HTTP 404 if not found, or HTTP 409 if already in terminal state.
    """
    # 1. Query with row-level lock to prevent concurrent worker state transition
    stmt = select(CardDispute).where(CardDispute.id == dispute_id).with_for_update()
    result = await session.execute(stmt)
    dispute = result.scalars().first()

    if not dispute:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispute with ID '{dispute_id}' not found",
        )

    # 2. Validate that dispute has not reached terminal state
    if dispute.status in ("submitted_to_network", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel dispute in terminal state '{dispute.status}'",
        )

    # 3. Transition status to cancelled and commit
    now = datetime.now(timezone.utc)
    dispute.status = "cancelled"
    dispute.updated_at = now
    await session.commit()

    # 4. Broadcast task revocation to Celery worker fleet
    if dispute.celery_task_id:
        revoke_dispute_task(dispute.celery_task_id)

    logger.info("dispute_cancelled", extra={"dispute_id": str(dispute_id)})

    return DisputeCancelResponse(
        id=dispute.id,
        status=DisputeStatus.cancelled,
        revoked_task_id=dispute.celery_task_id,
        message="Card dispute successfully revoked in-flight",
    )


@router.post(
    "/disputes/{dispute_id}/retry",
    response_model=DisputeRetryResponse,
    status_code=status.HTTP_200_OK,
    summary="Retry a failed dispute submission",
    description="Re-enqueues a previously failed dispute with incremented attempt count and new Celery task ID.",
)
async def retry_dispute(
    dispute_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[str, Security(get_api_key)],
    simulate_failure: Annotated[
        bool,
        Query(
            description="Diagnostic flag to simulate clearinghouse network timeout in worker",
        ),
    ] = False,
) -> DisputeRetryResponse:
    """Retry submission for a dispute currently in 'failed' status.

    Args:
        dispute_id: UUID of the failed dispute to retry.
        session: Active asynchronous database session.
        _: Validated API key security dependency.
        simulate_failure: Diagnostic flag to test repeated failures.

    Returns:
        DisputeRetryResponse: Updated attempt count and new Celery task ID.

    Raises:
        HTTPException: HTTP 404 if not found, or HTTP 409 if status is not 'failed'.
    """
    # 1. Query with row-level lock
    stmt = select(CardDispute).where(CardDispute.id == dispute_id).with_for_update()
    result = await session.execute(stmt)
    dispute = result.scalars().first()

    if not dispute:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dispute with ID '{dispute_id}' not found",
        )

    # 2. Only failed disputes can be re-submitted
    if dispute.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry dispute with status '{dispute.status}'. Only failed disputes can be retried.",
        )

    # 3. Dispatch fresh Celery task message
    task_id = dispatch_dispute_submission(
        dispute_id=str(dispute_id),
        simulate_failure=simulate_failure,
    )

    # 4. Increment attempt count, reset failure reason, and transition back to processing
    now = datetime.now(timezone.utc)
    dispute.attempt_count += 1
    dispute.status = "processing"
    dispute.celery_task_id = task_id
    dispute.error_message = None
    dispute.updated_at = now
    await session.commit()

    logger.info(
        "dispute_retried",
        extra={
            "dispute_id": str(dispute_id),
            "attempt_count": dispute.attempt_count,
            "new_celery_task_id": task_id,
        },
    )

    return DisputeRetryResponse(
        id=dispute.id,
        status=DisputeStatus.processing,
        attempt_count=dispute.attempt_count,
        celery_task_id=task_id,
        message="Dispute re-queued for network submission",
    )


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint",
    description="Probes database connectivity without requiring authentication.",
)
async def health_check(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Inspect system health and database connection pool availability.

    Args:
        session: Active asynchronous database session.

    Returns:
        dict[str, Any]: Service health status dictionary.
    """
    await session.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "connected",
        "service": "card_dispute_engine",
    }
