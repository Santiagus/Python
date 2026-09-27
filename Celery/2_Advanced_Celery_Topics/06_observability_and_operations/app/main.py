"""FastAPI Ingestion Gateway for real-time fraud scoring and AML sanctions screening.

Provides asynchronous ingestion, atomic idempotency, in-flight visibility, and health probes.
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import close_database_pool, get_session, warm_database_pool
from app.dispatcher import dispatch_screening_workflow
from app.logging_config import setup_logging
from app.middlewares import register_middlewares
from app.models import ScreeningModel
from app.schemas import (
    LivenessResponse,
    ReadinessResponse,
    ScreeningRequest,
    ScreeningResponse,
)

# 1. Initialize development logging
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup warmup and graceful shutdown resource disposal."""
    # Pre-warm connection pool with ping ping
    await warm_database_pool()
    logger.info("ingestion_gateway_started", extra={"environment": settings.environment})
    yield
    # Dispose connection pools on shutdown
    await close_database_pool()
    logger.info("ingestion_gateway_stopped")


app = FastAPI(
    title="Real-Time Fraud & AML Screening Gateway",
    description="Asynchronous ingestion gateway with distributed tracing.",
    version="1.0.0",
    lifespan=lifespan,
)

# 2. Register modular middlewares (ErrorHandling -> Profiling -> CorrelationId)
register_middlewares(app)


# ==============================================================================
# Domain API Endpoints
# ==============================================================================


@app.post(
    "/api/v1/screenings",
    response_model=ScreeningResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest Payment for Fraud & AML Screening",
    tags=["Screening Gateway"],
)
async def create_screening(
    payload: ScreeningRequest,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Ingest payment transaction, persist in-flight state, and trigger Celery canvas.

    Enforces FinTech In-Flight State Visibility:
    Persists an initial row with status='processing' before returning HTTP 202 Accepted.
    Under duplicate transaction submission, captures unique constraint collision and returns
    the existing record with HTTP 200 OK (Atomic Idempotency).

    Args:
        payload: Validated payment transaction screening request.
        session: Active asynchronous SQLAlchemy session.

    Returns:
        ScreeningResponse: Initial in-flight or existing idempotent screening record.
    """
    # 1. Zero-Refresh Response Generation: Pre-generate UUID and timestamp
    screening_id = uuid.uuid4()
    now_utc = datetime.now(timezone.utc)

    screening = ScreeningModel(
        id=screening_id,
        transaction_id=payload.transaction_id,
        account_id=payload.account_id,
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        client_ip=payload.client_ip,
        status="processing",
        risk_score=None,
        decision_reason=None,
        created_at=now_utc,
        updated_at=now_utc,
    )

    try:
        # 2. Atomic Idempotency: Attempt insert within transaction savepoint
        session.add(screening)
        await session.commit()
    except IntegrityError:
        # Collision on uq_screenings_tx: fetch existing record and return HTTP 200 OK
        await session.rollback()
        stmt = select(ScreeningModel).where(ScreeningModel.transaction_id == payload.transaction_id)
        result = await session.execute(stmt)
        existing = result.scalar_one()

        amount_major = Decimal(existing.amount_cents) / Decimal("100.00")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=ScreeningResponse(
                id=existing.id,
                transaction_id=existing.transaction_id,
                account_id=existing.account_id,
                amount=amount_major,
                currency=existing.currency,
                status=cast(Any, existing.status),
                risk_score=existing.risk_score,
                decision_reason=existing.decision_reason,
                created_at=existing.created_at,
            ).model_dump(mode="json"),
        )

    # 3. Asynchronously dispatch Celery canvas workflow
    dispatch_screening_workflow(screening_id=screening_id, request=payload)

    # 4. Construct response directly from in-memory state (Zero-Refresh)
    return ScreeningResponse(
        id=screening_id,
        transaction_id=payload.transaction_id,
        account_id=payload.account_id,
        amount=payload.amount,
        currency=payload.currency,
        status="processing",
        risk_score=None,
        decision_reason="Workflow dispatched for real-time scoring",
        created_at=now_utc,
    )


@app.get(
    "/api/v1/screenings/{screening_id}",
    response_model=ScreeningResponse,
    summary="Query Screening State Machine Status",
    tags=["Screening Gateway"],
)
async def get_screening(
    screening_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ScreeningResponse:
    """Retrieve current state machine status and risk scoring for a screening.

    Args:
        screening_id: Persistent UUID assigned to the screening ledger record.
        session: Active asynchronous SQLAlchemy session.

    Returns:
        ScreeningResponse: Active or terminal state machine record.

    Raises:
        HTTPException: 404 Not Found if record does not exist.
    """
    stmt = select(ScreeningModel).where(ScreeningModel.id == screening_id)
    result = await session.execute(stmt)
    screening = result.scalar_one_or_none()

    if screening is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Screening record '{screening_id}' not found",
        )

    amount_major = Decimal(screening.amount_cents) / Decimal("100.00")
    return ScreeningResponse(
        id=screening.id,
        transaction_id=screening.transaction_id,
        account_id=screening.account_id,
        amount=amount_major,
        currency=screening.currency,
        status=cast(Any, screening.status),
        risk_score=screening.risk_score,
        decision_reason=screening.decision_reason,
        created_at=screening.created_at,
    )


# ==============================================================================
# Health Probes & Telemetry Endpoints
# ==============================================================================


@app.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness Probe",
    tags=["Observability"],
)
async def liveness_probe() -> LivenessResponse:
    """Lightweight process liveness check verifying the event loop is active."""
    return LivenessResponse(status="alive")


@app.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness Probe",
    tags=["Observability"],
)
async def readiness_probe(
    session: AsyncSession = Depends(get_session),
) -> Any:
    """Deep readiness probe actively validating PostgreSQL, Redis, and broker reachability.

    Returns:
        ReadinessResponse: System readiness status and subsystem diagnostics.
    """
    db_status = "connected"
    redis_status = "connected"
    rabbitmq_status = "connected"
    is_healthy = True

    # 1. Validate PostgreSQL connection pool
    try:
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {exc}"
        is_healthy = False

    # 2. Validate Redis cache connectivity
    try:
        r = aioredis.from_url(settings.redis_url, socket_timeout=1.0)
        await r.ping()
        await r.aclose()
    except Exception as exc:
        redis_status = f"error: {exc}"
        is_healthy = False

    # 3. Validate Celery broker connectivity
    try:
        from services.worker.celery_app import celery_app

        with celery_app.connection_for_read() as conn:
            conn.ensure_connection(max_retries=1)
    except Exception as exc:
        rabbitmq_status = f"error: {exc}"
        is_healthy = False

    response_payload = {
        "status": "ready" if is_healthy else "unhealthy",
        "database": db_status,
        "redis": redis_status,
        "rabbitmq": rabbitmq_status,
    }

    if not is_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response_payload,
        )

    return ReadinessResponse(**response_payload)


@app.get(
    "/metrics",
    summary="Prometheus Telemetry Scrape Endpoint",
    tags=["Observability"],
)
async def metrics_endpoint() -> Response:
    """Expose application and task telemetry in standard Prometheus text exposition format."""
    metric_bytes = generate_latest()
    return Response(
        content=metric_bytes,
        media_type=CONTENT_TYPE_LATEST,
    )
