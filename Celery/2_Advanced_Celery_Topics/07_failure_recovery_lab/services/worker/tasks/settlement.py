"""Celery worker task for two-phase inquiry wholesale wire settlement.

Implements late acknowledgements (acks_late=True), worker lost rejections,
row-level locking (SELECT ... FOR UPDATE), two-phase provider inquiry against
the wholesale bank simulator, and dual-entry ledger balancing in minor-unit cents.
"""

import asyncio
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from celery import Task
from httpx import AsyncClient, Limits, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.worker.celery_app import celery_app
from shared.models import (
    AccountType,
    LedgerDirection,
    LedgerJournal,
    WireAuditLog,
    WireStatus,
    WireTransfer,
)
from shared.schemas import BankDisburseRequest, WireTaskPayload

# 1. Environment and connection configuration
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/settlement_db",
)
BANK_SIMULATOR_URL: str = os.getenv(
    "BANK_SIMULATOR_URL",
    "http://localhost:8010",
)

# 2. Worker connection pool budgeting (pool_size=2, max_overflow=2)
_engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_size=2,
    max_overflow=2,
    pool_pre_ping=True,
)
_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

# 3. Process-level HTTP client singleton with persistent socket pooling
_http_limits = Limits(
    max_keepalive_connections=20,
    max_connections=50,
    keepalive_expiry=30.0,
)
_shared_client: AsyncClient = AsyncClient(
    base_url=BANK_SIMULATOR_URL,
    limits=_http_limits,
    timeout=10.0,
)


def get_shared_client() -> AsyncClient:
    """Retrieve the shared process-level HTTP client."""
    return _shared_client


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retrieve the worker database session factory."""
    return _session_factory


async def process_wire_settlement(
    task_payload: dict[str, Any],
    is_redelivered: bool = False,
    worker_hostname: str | None = None,
    session: AsyncSession | None = None,
    client: AsyncClient | None = None,
) -> dict[str, Any]:
    """Execute two-phase wire settlement with row locking and balanced ledger entry.

    Args:
        task_payload: Deserialized AMQP wire task dictionary.
        is_redelivered: Flag indicating whether this delivery is a redelivery.
        worker_hostname: Hostname of worker child process.
        session: Optional injected database session (for unit testing).
        client: Optional injected HTTP client (for unit testing).

    Returns:
        dict[str, Any]: Result envelope containing settlement status and references.

    Raises:
        ValueError: If wire transfer record cannot be found in database.
        RuntimeError: If clearinghouse reports an unhandled failure.
    """
    # 1. Validate payload using Pydantic contract
    payload = WireTaskPayload.model_validate(task_payload)
    wire_uuid = uuid.UUID(payload.wire_id)
    hostname = worker_hostname or socket.gethostname()
    http_client = client or get_shared_client()

    # 2. Determine session lifecycle
    if session is not None:
        return await _execute_settlement_transaction(
            session=session,
            payload=payload,
            wire_uuid=wire_uuid,
            is_redelivered=is_redelivered,
            hostname=hostname,
            http_client=http_client,
        )

    async with get_session_factory()() as owned_session:
        return await _execute_settlement_transaction(
            session=owned_session,
            payload=payload,
            wire_uuid=wire_uuid,
            is_redelivered=is_redelivered,
            hostname=hostname,
            http_client=http_client,
        )


async def _execute_settlement_transaction(
    session: AsyncSession,
    payload: WireTaskPayload,
    wire_uuid: uuid.UUID,
    is_redelivered: bool,
    hostname: str,
    http_client: AsyncClient,
) -> dict[str, Any]:
    """Execute settlement transaction within an active database session."""
    # 1. Acquire row-level lock on master wire transfer
    stmt = (
        select(WireTransfer)
        .where(WireTransfer.wire_id == wire_uuid)
        .with_for_update()
    )
    result = await session.execute(stmt)
    wire = result.scalar_one_or_none()

    if wire is None:
        raise ValueError(f"Wire transfer '{wire_uuid}' not found in database")

    # 2. Guard against duplicate execution (Idempotent Abort)
    if wire.status == WireStatus.SETTLED.value:
        return {
            "wire_id": str(wire.wire_id),
            "status": WireStatus.SETTLED.value,
            "bank_reference_id": wire.bank_reference_id,
            "idempotent_skip": True,
            "phase1_hit": True,
        }

    if wire.status in (WireStatus.FAILED.value, WireStatus.DEAD_LETTERED.value):
        return {
            "wire_id": str(wire.wire_id),
            "status": wire.status,
            "aborted": True,
            "failure_reason": wire.failure_reason,
        }

    # 3. Two-Phase Provider Inquiry (Anti-Double-Disbursement Invariant)
    # Phase 1: Query clearinghouse by idempotency key
    inquiry_url = f"/v1/wires/{payload.idempotency_key}"
    inquiry_resp: Response = await http_client.get(inquiry_url)

    bank_reference_id: str
    phase1_hit: bool = False

    if inquiry_resp.status_code == 200:
        # Bank already settled this wire before a previous crash or timeout
        bank_data = inquiry_resp.json()
        bank_reference_id = bank_data["bank_reference_id"]
        phase1_hit = True
    elif inquiry_resp.status_code == 404:
        # Phase 2: Wire was never disbursed to bank -> execute settlement
        disburse_payload = BankDisburseRequest(
            idempotency_key=payload.idempotency_key,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            beneficiary_account_mask=payload.beneficiary_account_mask,
            routing_number=payload.routing_number,
            swift_bic=payload.swift_bic,
            disbursement_token=payload.disbursement_token,
        )
        disburse_resp: Response = await http_client.post(
            "/v1/wires/settle",
            json=disburse_payload.model_dump(),
        )
        if disburse_resp.status_code != 200:
            raise RuntimeError(
                f"Bank clearinghouse rejected settlement: HTTP {disburse_resp.status_code} - {disburse_resp.text}"
            )
        bank_data = disburse_resp.json()
        bank_reference_id = bank_data["bank_reference_id"]
    else:
        raise RuntimeError(
            f"Clearinghouse inquiry error: HTTP {inquiry_resp.status_code} - {inquiry_resp.text}"
        )

    # 4. Advance wire state and update delivery metadata
    previous_status = wire.status
    now = datetime.now(timezone.utc)

    wire.status = WireStatus.SETTLED.value
    wire.bank_reference_id = bank_reference_id
    wire.redelivered_flag = is_redelivered
    if is_redelivered:
        wire.delivery_attempts += 1
    wire.settled_at = now
    wire.updated_at = now

    # 5. Dual-Entry Immutable Ledger Journal Insertion (Zero Drift Guarantee)
    debit_entry = LedgerJournal(
        wire_id=wire.wire_id,
        account_type=AccountType.CUSTOMER_CASH.value,
        direction=LedgerDirection.DEBIT.value,
        amount_cents=wire.amount_cents,
        created_at=now,
    )
    credit_entry = LedgerJournal(
        wire_id=wire.wire_id,
        account_type=AccountType.CLEARINGHOUSE_SETTLEMENT.value,
        direction=LedgerDirection.CREDIT.value,
        amount_cents=wire.amount_cents,
        created_at=now,
    )
    session.add_all([debit_entry, credit_entry])

    # 6. Audit Trail Recording
    event_desc = (
        "Wire settled via Fedwire (Phase 1 inquiry hit: recovered after worker crash)"
        if phase1_hit
        else "Wire settled via Fedwire wholesale clearinghouse"
    )
    audit_log = WireAuditLog(
        wire_id=wire.wire_id,
        previous_status=previous_status,
        new_status=WireStatus.SETTLED.value,
        worker_hostname=hostname,
        redelivered=is_redelivered,
        event_description=event_desc,
        occurred_at=now,
    )
    session.add(audit_log)

    # 7. ACID Commit to PostgreSQL
    await session.commit()

    # 8. Return Result Envelope (Celery will ACK message after this point)
    return {
        "wire_id": str(wire.wire_id),
        "status": WireStatus.SETTLED.value,
        "bank_reference_id": bank_reference_id,
        "amount_cents": wire.amount_cents,
        "delivery_attempts": wire.delivery_attempts,
        "redelivered": is_redelivered,
        "phase1_hit": phase1_hit,
    }


@celery_app.task(
    bind=True,
    name="services.worker.tasks.settlement.settle_wire_transfer",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def settle_wire_transfer(self: Task, task_payload: dict[str, Any]) -> dict[str, Any]:
    """Celery task entrypoint for durable interbank wire settlement.

    Args:
        self: Bound Celery task instance.
        task_payload: WireTaskPayload serialized dictionary.

    Returns:
        dict[str, Any]: Result envelope.
    """
    delivery_info = getattr(self.request, "delivery_info", {}) or {}
    is_redelivered = bool(delivery_info.get("redelivered", False))
    worker_hostname = getattr(self.request, "hostname", None) or socket.gethostname()

    return asyncio.run(
        process_wire_settlement(
            task_payload=task_payload,
            is_redelivered=is_redelivered,
            worker_hostname=worker_hostname,
        )
    )
