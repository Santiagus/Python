"""Unit tests for the wire audit log and DLQ poison pill quarantine Celery tasks."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.worker.tasks.audit import (
    get_audit_session_factory,
    process_quarantine_poison_pill,
    process_record_wire_audit,
    quarantine_poison_pill,
    record_wire_audit,
)
from shared.models import WireAuditLog, WireStatus, WireTransfer


def test_audit_session_factory_accessor() -> None:
    """Verify get_audit_session_factory returns a valid sessionmaker instance."""
    factory = get_audit_session_factory()
    assert factory is not None


@pytest.mark.asyncio
async def test_process_record_wire_audit_with_session() -> None:
    """Verify recording an audit event directly with an injected session."""
    wire_id = uuid.uuid4()
    mock_session = AsyncMock(spec=AsyncSession)

    audit_data = {
        "wire_id": wire_id,
        "previous_status": "processing",
        "new_status": "settled",
        "worker_hostname": "audit-node-1",
        "redelivered": False,
        "event_description": "Normal wire settlement completed",
    }

    result = await process_record_wire_audit(audit_data, session=mock_session)

    assert result["recorded"] is True
    assert result["status"] == "settled"
    assert result["wire_id"] == str(wire_id)

    mock_session.add.assert_called_once()
    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, WireAuditLog)
    assert added_obj.new_status == "settled"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_record_wire_audit_managed_session() -> None:
    """Verify recording an audit event using the managed session factory context."""
    wire_id = uuid.uuid4()
    mock_session = AsyncMock(spec=AsyncSession)

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__.return_value = None

    audit_data = {
        "wire_id": wire_id,
        "new_status": "submitted_to_bank",
        "event_description": "Dispatched to bank",
    }

    with patch("services.worker.tasks.audit.get_audit_session_factory", return_value=mock_factory):
        result = await process_record_wire_audit(audit_data, session=None)
        assert result["recorded"] is True
        assert result["status"] == "submitted_to_bank"


@pytest.mark.asyncio
async def test_process_quarantine_poison_pill_success() -> None:
    """Verify poison pill quarantining: status set to dead_lettered and audit log recorded."""
    wire_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    wire = WireTransfer(
        wire_id=wire_id,
        client_id="CORP-BAD-001",
        idempotency_key="idemp-poison-1",
        amount_cents=100000,
        sender_account_mask="******1111",
        beneficiary_account_mask="******2222",
        routing_number="121000358",
        swift_bic="CHASUS33XXX",
        status=WireStatus.PROCESSING.value,
        created_at=now,
        updated_at=now,
    )

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = wire
    mock_session.execute.return_value = mock_result

    result = await process_quarantine_poison_pill(
        wire_id=str(wire_id),
        failure_reason="Malformed ISO 20022 message block",
        worker_hostname="quarantine-worker-1",
        session=mock_session,
    )

    assert result["quarantined"] is True
    assert result["status"] == "dead_lettered"
    assert result["failure_reason"] == "Malformed ISO 20022 message block"

    # Verify wire updated
    assert wire.status == "dead_lettered"
    assert wire.failure_reason == "Malformed ISO 20022 message block"

    # Verify audit entry added
    mock_session.add.assert_called_once()
    audit_entry = mock_session.add.call_args[0][0]
    assert isinstance(audit_entry, WireAuditLog)
    assert audit_entry.new_status == "dead_lettered"
    assert "Poison pill quarantined" in audit_entry.event_description

    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_quarantine_poison_pill_wire_not_found() -> None:
    """Verify ValueError is raised if wire to quarantine does not exist."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    with pytest.raises(ValueError, match="not found for quarantine"):
        await process_quarantine_poison_pill(
            wire_id=str(uuid.uuid4()),
            failure_reason="Unknown poison pill",
            session=mock_session,
        )


@pytest.mark.asyncio
async def test_process_quarantine_using_managed_session() -> None:
    """Verify quarantine execution using managed session factory context."""
    wire_id = uuid.uuid4()
    wire = WireTransfer(
        wire_id=wire_id,
        client_id="CORP-BAD-002",
        idempotency_key="idemp-poison-2",
        amount_cents=200000,
        sender_account_mask="******1111",
        beneficiary_account_mask="******2222",
        routing_number="121000358",
        swift_bic="CHASUS33XXX",
    )

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = wire
    mock_session.execute.return_value = mock_result

    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session
    mock_factory.return_value.__aexit__.return_value = None

    with patch("services.worker.tasks.audit.get_audit_session_factory", return_value=mock_factory):
        result = await process_quarantine_poison_pill(
            wire_id=str(wire_id),
            failure_reason="Corrupted payload",
            session=None,
        )
        assert result["quarantined"] is True
        assert result["status"] == "dead_lettered"


def test_celery_task_audit_wrappers() -> None:
    """Verify Celery task wrappers record_wire_audit and quarantine_poison_pill."""
    record_wire_audit.request.hostname = "celery@audit-node"
    quarantine_poison_pill.request.hostname = "celery@audit-node"

    # 1. Test record_wire_audit wrapper
    with patch("services.worker.tasks.audit.process_record_wire_audit", return_value={"recorded": True}) as mock_record:
        res = record_wire_audit({"wire_id": str(uuid.uuid4()), "new_status": "settled", "event_description": "test"})
        assert res["recorded"] is True
        assert mock_record.called

    # 2. Test quarantine_poison_pill wrapper
    with patch("services.worker.tasks.audit.process_quarantine_poison_pill", return_value={"quarantined": True}) as mock_quarantine:
        res2 = quarantine_poison_pill(str(uuid.uuid4()), "poison pill")
        assert res2["quarantined"] is True
        assert mock_quarantine.called
