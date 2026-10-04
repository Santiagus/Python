"""Celery worker task for wire audit logging and DLQ poison pill quarantining."""

import asyncio
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from celery import Task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from services.worker.celery_app import celery_app
from shared.models import WireAuditLog, WireStatus, WireTransfer
from shared.schemas import WireAuditLogCreate

# 1. Database connection configuration for audit worker
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/settlement_db",
)

_audit_engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_size=2,
    max_overflow=2,
    pool_pre_ping=True,
)
_audit_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _audit_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


def get_audit_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retrieve the audit worker database session factory."""
    return _audit_session_factory


async def process_record_wire_audit(
    audit_data: dict[str, Any],
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Persist an audit event record to PostgreSQL.

    Args:
        audit_data: Serialized WireAuditLogCreate payload.
        session: Optional injected database session.

    Returns:
        dict[str, Any]: Audit record confirmation.
    """
    # 1. Parse and validate schema
    log_create = WireAuditLogCreate.model_validate(audit_data)
    now = datetime.now(timezone.utc)

    # 2. Persist audit log line
    if session is not None:
        return await _insert_audit_log(session, log_create, now)

    async with get_audit_session_factory()() as owned_session:
        return await _insert_audit_log(owned_session, log_create, now)


async def _insert_audit_log(
    session: AsyncSession,
    log_create: WireAuditLogCreate,
    occurred_at: datetime,
) -> dict[str, Any]:
    """Insert and commit audit log entry."""
    audit_entry = WireAuditLog(
        wire_id=log_create.wire_id,
        previous_status=log_create.previous_status,
        new_status=log_create.new_status,
        worker_hostname=log_create.worker_hostname,
        redelivered=log_create.redelivered,
        event_description=log_create.event_description,
        occurred_at=occurred_at,
    )
    session.add(audit_entry)
    await session.commit()
    return {
        "wire_id": str(log_create.wire_id),
        "status": log_create.new_status,
        "recorded": True,
    }


async def process_quarantine_poison_pill(
    wire_id: str,
    failure_reason: str,
    worker_hostname: str | None = None,
    session: AsyncSession | None = None,
) -> dict[str, Any]:
    """Quarantine a poisoned wire transfer and record dead-lettered state.

    Args:
        wire_id: UUID string of the failing wire transfer.
        failure_reason: Description of the fatal error or payload corruption.
        worker_hostname: Hostname of worker child process.
        session: Optional injected database session.

    Returns:
        dict[str, Any]: Result envelope confirming quarantine.

    Raises:
        ValueError: If wire transfer does not exist.
    """
    wire_uuid = uuid.UUID(wire_id)
    hostname = worker_hostname or socket.gethostname()

    if session is not None:
        return await _execute_quarantine(session, wire_uuid, failure_reason, hostname)

    async with get_audit_session_factory()() as owned_session:
        return await _execute_quarantine(owned_session, wire_uuid, failure_reason, hostname)


async def _execute_quarantine(
    session: AsyncSession,
    wire_uuid: uuid.UUID,
    failure_reason: str,
    hostname: str,
) -> dict[str, Any]:
    """Execute state transition to dead_lettered with row lock."""
    stmt = (
        select(WireTransfer)
        .where(WireTransfer.wire_id == wire_uuid)
        .with_for_update()
    )
    result = await session.execute(stmt)
    wire = result.scalar_one_or_none()

    if wire is None:
        raise ValueError(f"Wire transfer '{wire_uuid}' not found for quarantine")

    previous_status = wire.status
    now = datetime.now(timezone.utc)

    # 1. Transition state to dead_lettered and record failure reason
    wire.status = WireStatus.DEAD_LETTERED.value
    wire.failure_reason = failure_reason
    wire.updated_at = now

    # 2. Record DLQ quarantine audit line
    audit = WireAuditLog(
        wire_id=wire.wire_id,
        previous_status=previous_status,
        new_status=WireStatus.DEAD_LETTERED.value,
        worker_hostname=hostname,
        event_description=f"Poison pill quarantined: {failure_reason}",
        occurred_at=now,
    )
    session.add(audit)

    await session.commit()
    return {
        "wire_id": str(wire.wire_id),
        "status": WireStatus.DEAD_LETTERED.value,
        "failure_reason": failure_reason,
        "quarantined": True,
    }


@celery_app.task(
    bind=True,
    name="services.worker.tasks.audit.record_wire_audit",
    acks_late=True,
    reject_on_worker_lost=True,
)
def record_wire_audit(self: Task, audit_data: dict[str, Any]) -> dict[str, Any]:
    """Celery task entrypoint for recording wire lifecycle audit events.

    Args:
        self: Bound Celery task instance.
        audit_data: Serialized WireAuditLogCreate dictionary.

    Returns:
        dict[str, Any]: Confirmation dictionary.
    """
    return asyncio.run(
        process_record_wire_audit(
            audit_data=audit_data,
        )
    )


@celery_app.task(
    bind=True,
    name="services.worker.tasks.audit.quarantine_poison_pill",
    acks_late=True,
    reject_on_worker_lost=True,
)
def quarantine_poison_pill(
    self: Task,
    wire_id: str,
    failure_reason: str,
) -> dict[str, Any]:
    """Celery task entrypoint for dead-lettering unrecoverable poisoned payloads.

    Args:
        self: Bound Celery task instance.
        wire_id: Master wire UUID string.
        failure_reason: Unrecoverable rejection reason.

    Returns:
        dict[str, Any]: Quarantine result envelope.
    """
    worker_hostname = getattr(self.request, "hostname", None) or socket.gethostname()
    return asyncio.run(
        process_quarantine_poison_pill(
            wire_id=wire_id,
            failure_reason=failure_reason,
            worker_hostname=worker_hostname,
        )
    )
