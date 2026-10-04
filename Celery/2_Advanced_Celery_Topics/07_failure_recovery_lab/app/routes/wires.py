"""High-value interbank wire ingestion and status query routes.

Enforces zero-refresh response generation, atomic idempotency via database unique constraints,
and anti-blackhole in-flight state persistence before AMQP dispatch.
"""

import os
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.dispatcher import get_wire_dispatcher
from shared.models import WireStatus, WireTransfer
from shared.schemas import (
    WireCreateRequest,
    WireResponse,
    WireTaskPayload,
    mask_account_number,
)

# 1. Resolve environment database configuration
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/settlement_db",
)

# 2. API Gateway Connection Pool Budgeting (pool_size=10, max_overflow=20)
_engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


def get_engine() -> AsyncEngine:
    """Retrieve the API gateway SQLAlchemy AsyncEngine instance.

    Returns:
        AsyncEngine: The active database engine.
    """
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retrieve the API gateway session factory.

    Returns:
        async_sessionmaker[AsyncSession]: The active async sessionmaker.
    """
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an asynchronous database session.

    Yields:
        AsyncSession: Active database session.
    """
    async with _session_factory() as session:
        yield session


router: APIRouter = APIRouter(prefix="/api/v1/wires", tags=["Wires"])


@router.post(
    "",
    response_model=WireResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest Wire Transfer",
    description="Ingest wholesale wire transfer with immediate ACID persistence and durable AMQP dispatch.",
)
async def ingest_wire_transfer(
    payload: WireCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Client-provided idempotency key for preventing duplicate transfers",
            examples=["idem-99214-alpha"],
        ),
    ] = None,
) -> WireResponse:
    """Ingest a new wire transfer into the processing pipeline.

    Enforces zero-refresh response generation, atomic idempotency via unique constraints,
    immediate status='processing' database persistence, and publisher-confirmed AMQP dispatch.

    Args:
        payload: Wire transfer creation payload with monetary and routing validations.
        session: Injected asynchronous database session.
        idempotency_key: Optional client-provided idempotency key header.

    Returns:
        WireResponse: The created or existing in-flight wire transfer record.
    """
    # 1. Resolve idempotency key
    resolved_idempotency_key = (
        idempotency_key.strip()
        if idempotency_key and idempotency_key.strip()
        else f"idem-{uuid.uuid4().hex[:16]}"
    )

    # 2. Pre-generate UUIDv4 primary keys and UTC timestamps (Zero-Refresh Invariant)
    now = datetime.now(timezone.utc)
    wire_id = uuid.uuid4()
    beneficiary_mask = mask_account_number(payload.beneficiary_account)
    sender_mask = "******0001"
    disbursement_token = f"tok_{uuid.uuid4().hex[:16]}"

    # 3. Instantiate domain entity with status='processing' (Anti-Blackhole Contract)
    wire = WireTransfer(
        wire_id=wire_id,
        client_id=payload.client_id,
        idempotency_key=resolved_idempotency_key,
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        sender_account_mask=sender_mask,
        beneficiary_account_mask=beneficiary_mask,
        routing_number=payload.routing_number,
        swift_bic=payload.swift_bic,
        status=WireStatus.PROCESSING.value,
        delivery_attempts=1,
        redelivered_flag=False,
        bank_reference_id=None,
        failure_reason=None,
        created_at=now,
        updated_at=now,
        settled_at=None,
    )

    # 4. Atomic Idempotency via Unique Constraints (Catch IntegrityError)
    try:
        session.add(wire)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        # Retrieve existing wire transfer record
        stmt = select(WireTransfer).where(
            WireTransfer.client_id == payload.client_id,
            WireTransfer.idempotency_key == resolved_idempotency_key,
        )
        result = await session.execute(stmt)
        existing_wire = result.scalar_one_or_none()
        if existing_wire is not None:
            return WireResponse.model_validate(existing_wire)
        raise  # pragma: no cover

    # 5. Dispatch task to RabbitMQ with publisher confirms
    task_payload = WireTaskPayload(
        wire_id=str(wire.wire_id),
        client_id=wire.client_id,
        idempotency_key=wire.idempotency_key,
        amount_cents=wire.amount_cents,
        currency=wire.currency,
        sender_account_mask=wire.sender_account_mask,
        beneficiary_account_mask=wire.beneficiary_account_mask,
        routing_number=wire.routing_number,
        swift_bic=wire.swift_bic,
        disbursement_token=disbursement_token,
    )
    get_wire_dispatcher().dispatch_wire(task_payload=task_payload)

    # 6. Return response without calling await session.refresh()
    return WireResponse.model_validate(wire)


@router.get(
    "/{wire_id}",
    response_model=WireResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Wire Transfer by ID",
    description="Retrieve wire transfer record. Immediately returns status='processing' for in-flight tasks.",
)
async def get_wire_transfer(
    wire_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WireResponse:
    """Retrieve wire transfer state by its unique transaction UUID.

    Guarantees FinTech in-flight state visibility: returns 200 OK with status='processing'
    rather than 404 while the background Celery worker executes.

    Args:
        wire_id: Unique wire transfer UUID.
        session: Injected asynchronous database session.

    Returns:
        WireResponse: The active or settled wire transfer record.

    Raises:
        HTTPException: If wire transfer does not exist.
    """
    # 1. Query wire transfer by primary key
    stmt = select(WireTransfer).where(WireTransfer.wire_id == wire_id)
    result = await session.execute(stmt)
    wire = result.scalar_one_or_none()

    if wire is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Wire transfer '{wire_id}' not found",
        )

    # 2. Return validated domain model
    return WireResponse.model_validate(wire)


@router.get(
    "",
    response_model=list[WireResponse],
    status_code=status.HTTP_200_OK,
    summary="List Wire Transfers",
    description="List wire transfers with optional client filtering and pagination.",
)
async def list_wire_transfers(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    client_id: Annotated[str | None, Query(description="Filter by client ID")] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="Max records to return")] = 50,
) -> list[WireResponse]:
    """List stored wire transfers.

    Args:
        session: Injected asynchronous database session.
        client_id: Optional client ID filter.
        limit: Maximum number of rows to return.

    Returns:
        list[WireResponse]: List of wire transfer records.
    """
    # 1. Build select query with optional filter
    stmt = select(WireTransfer).order_by(WireTransfer.created_at.desc()).limit(limit)
    if client_id is not None:
        stmt = stmt.where(WireTransfer.client_id == client_id)

    # 2. Execute query and serialize results
    result = await session.execute(stmt)
    wires = result.scalars().all()
    return [WireResponse.model_validate(w) for w in wires]
