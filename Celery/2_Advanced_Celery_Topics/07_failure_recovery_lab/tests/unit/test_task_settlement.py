"""Unit tests for the Celery settlement task and Two-Phase Provider Inquiry pattern."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from services.worker.tasks.settlement import (
    get_session_factory,
    get_shared_client,
    process_wire_settlement,
    settle_wire_transfer,
)
from shared.models import LedgerJournal, WireAuditLog, WireStatus, WireTransfer


@pytest.fixture
def specimen_wire() -> WireTransfer:
    """Create a sample WireTransfer in processing state."""
    wire_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    return WireTransfer(
        wire_id=wire_id,
        client_id="CORP-CLIENT-001",
        idempotency_key="idemp-key-555",
        amount_cents=2500000,
        currency="USD",
        sender_account_mask="******1111",
        beneficiary_account_mask="******2222",
        routing_number="121000358",
        swift_bic="CHASUS33XXX",
        status=WireStatus.PROCESSING.value,
        delivery_attempts=1,
        redelivered_flag=False,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def specimen_task_payload(specimen_wire: WireTransfer) -> dict[str, object]:
    """Create a sample AMQP task payload matching the specimen wire."""
    return {
        "wire_id": str(specimen_wire.wire_id),
        "client_id": specimen_wire.client_id,
        "idempotency_key": specimen_wire.idempotency_key,
        "amount_cents": specimen_wire.amount_cents,
        "currency": specimen_wire.currency,
        "sender_account_mask": specimen_wire.sender_account_mask,
        "beneficiary_account_mask": specimen_wire.beneficiary_account_mask,
        "routing_number": specimen_wire.routing_number,
        "swift_bic": specimen_wire.swift_bic,
        "disbursement_token": "tok_fedwire_settle_999",
    }


def test_client_and_session_factory_accessors() -> None:
    """Verify singletons returned by get_shared_client and get_session_factory."""
    client = get_shared_client()
    session_factory = get_session_factory()
    assert client is not None
    assert session_factory is not None


@pytest.mark.asyncio
async def test_settlement_happy_path(
    specimen_wire: WireTransfer,
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify standard settlement: Phase 1 returns 404, Phase 2 disburses, DB commits."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire
    mock_session.execute.return_value = mock_result

    mock_client = AsyncMock()
    # Phase 1: 404 Not Found
    req_get = Request("GET", "http://test/v1/wires/idemp-key-555")
    mock_client.get.return_value = Response(404, request=req_get)
    # Phase 2: 200 OK
    req_post = Request("POST", "http://test/v1/wires/settle")
    mock_client.post.return_value = Response(
        200,
        json={"bank_reference_id": "FED-WIRE-SUCCESS-001"},
        request=req_post,
    )

    result = await process_wire_settlement(
        task_payload=specimen_task_payload,
        is_redelivered=False,
        worker_hostname="worker-node-1",
        session=mock_session,
        client=mock_client,
    )

    # 1. Assert result envelope
    assert result["status"] == "settled"
    assert result["bank_reference_id"] == "FED-WIRE-SUCCESS-001"
    assert result["delivery_attempts"] == 1
    assert result["redelivered"] is False
    assert result["phase1_hit"] is False

    # 2. Assert WireTransfer updated
    assert specimen_wire.status == "settled"
    assert specimen_wire.bank_reference_id == "FED-WIRE-SUCCESS-001"
    assert specimen_wire.settled_at is not None

    # 3. Assert double-entry ledger lines added
    assert mock_session.add_all.called
    added_lines = mock_session.add_all.call_args[0][0]
    assert len(added_lines) == 2
    assert isinstance(added_lines[0], LedgerJournal)
    assert added_lines[0].direction == "DEBIT"
    assert added_lines[0].amount_cents == specimen_wire.amount_cents
    assert isinstance(added_lines[1], LedgerJournal)
    assert added_lines[1].direction == "CREDIT"
    assert added_lines[1].amount_cents == specimen_wire.amount_cents

    # 4. Assert audit log added
    assert mock_session.add.called
    audit_entry = mock_session.add.call_args[0][0]
    assert isinstance(audit_entry, WireAuditLog)
    assert audit_entry.new_status == "settled"

    # 5. Assert database committed
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_settlement_redelivery_phase1_hit(
    specimen_wire: WireTransfer,
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify crash recovery: Phase 1 returns 200 CONFIRMED, Phase 2 is bypassed."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire
    mock_session.execute.return_value = mock_result

    mock_client = AsyncMock()
    # Phase 1: 200 OK (Wire was already disbursed before worker crashed)
    req_get = Request("GET", "http://test/v1/wires/idemp-key-555")
    mock_client.get.return_value = Response(
        200,
        json={"bank_reference_id": "FED-WIRE-PREVIOUS-999"},
        request=req_get,
    )

    result = await process_wire_settlement(
        task_payload=specimen_task_payload,
        is_redelivered=True,
        worker_hostname="surviving-worker-2",
        session=mock_session,
        client=mock_client,
    )

    # 1. Assert result envelope
    assert result["status"] == "settled"
    assert result["bank_reference_id"] == "FED-WIRE-PREVIOUS-999"
    assert result["delivery_attempts"] == 2
    assert result["redelivered"] is True
    assert result["phase1_hit"] is True

    # 2. Phase 2 must NOT have been called (Anti-Double-Disbursement Invariant)
    mock_client.post.assert_not_called()

    # 3. State committed
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_settlement_idempotent_skip_when_already_settled(
    specimen_wire: WireTransfer,
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify that if wire is already settled, settlement task exits cleanly."""
    specimen_wire.status = WireStatus.SETTLED.value
    specimen_wire.bank_reference_id = "FED-WIRE-EXISTING-111"

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire
    mock_session.execute.return_value = mock_result

    mock_client = AsyncMock()

    result = await process_wire_settlement(
        task_payload=specimen_task_payload,
        session=mock_session,
        client=mock_client,
    )

    assert result["status"] == "settled"
    assert result["idempotent_skip"] is True
    mock_client.get.assert_not_called()
    mock_client.post.assert_not_called()
    mock_session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_settlement_aborted_when_failed_or_dead_lettered(
    specimen_wire: WireTransfer,
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify that terminal failed or dead_lettered wires abort immediately."""
    specimen_wire.status = WireStatus.DEAD_LETTERED.value
    specimen_wire.failure_reason = "Sanction check violation"

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire
    mock_session.execute.return_value = mock_result

    mock_client = AsyncMock()

    result = await process_wire_settlement(
        task_payload=specimen_task_payload,
        session=mock_session,
        client=mock_client,
    )

    assert result["status"] == "dead_lettered"
    assert result["aborted"] is True
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_settlement_wire_not_found_raises_value_error(
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify ValueError is raised if wire does not exist in database."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    mock_client = AsyncMock()

    with pytest.raises(ValueError, match="not found in database"):
        await process_wire_settlement(
            task_payload=specimen_task_payload,
            session=mock_session,
            client=mock_client,
        )


@pytest.mark.asyncio
async def test_settlement_phase1_unhandled_error_raises_runtime_error(
    specimen_wire: WireTransfer,
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify RuntimeError is raised when Phase 1 returns unexpected status (e.g. 500)."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire
    mock_session.execute.return_value = mock_result

    mock_client = AsyncMock()
    req = Request("GET", "http://test/v1/wires/idemp-key-555")
    mock_client.get.return_value = Response(500, text="Internal Error", request=req)

    with pytest.raises(RuntimeError, match="Clearinghouse inquiry error: HTTP 500"):
        await process_wire_settlement(
            task_payload=specimen_task_payload,
            session=mock_session,
            client=mock_client,
        )


@pytest.mark.asyncio
async def test_settlement_phase2_bank_rejection_raises_runtime_error(
    specimen_wire: WireTransfer,
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify RuntimeError is raised when Phase 2 disbursement fails with 503."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire
    mock_session.execute.return_value = mock_result

    mock_client = AsyncMock()
    req_get = Request("GET", "http://test/v1/wires/idemp-key-555")
    mock_client.get.return_value = Response(404, request=req_get)
    req_post = Request("POST", "http://test/v1/wires/settle")
    mock_client.post.return_value = Response(503, text="Outage", request=req_post)

    with pytest.raises(RuntimeError, match="Bank clearinghouse rejected settlement: HTTP 503"):
        await process_wire_settlement(
            task_payload=specimen_task_payload,
            session=mock_session,
            client=mock_client,
        )


@pytest.mark.asyncio
async def test_settlement_using_managed_session_context(
    specimen_wire: WireTransfer,
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify execution when session=None triggers the session factory context manager."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire
    mock_session.execute.return_value = mock_result

    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session_factory.return_value.__aexit__.return_value = None

    mock_client = AsyncMock()
    req_get = Request("GET", "http://test/v1/wires/idemp-key-555")
    mock_client.get.return_value = Response(200, json={"bank_reference_id": "FED-WIRE-CTX-1"}, request=req_get)

    with patch("services.worker.tasks.settlement.get_session_factory", return_value=mock_session_factory):
        result = await process_wire_settlement(
            task_payload=specimen_task_payload,
            session=None,
            client=mock_client,
        )
        assert result["status"] == "settled"
        assert result["bank_reference_id"] == "FED-WIRE-CTX-1"


def test_celery_task_wrapper_execution(
    specimen_task_payload: dict[str, object],
) -> None:
    """Verify that Celery task wrapper unpacks request context and invokes async core."""
    settle_wire_transfer.request.delivery_info = {"redelivered": True}
    settle_wire_transfer.request.hostname = "celery@worker-node-4"

    expected_return = {
        "wire_id": str(specimen_task_payload["wire_id"]),
        "status": "settled",
        "bank_reference_id": "FED-WIRE-CELERY-OK",
    }

    with patch("services.worker.tasks.settlement.process_wire_settlement", return_value=expected_return) as mock_async:
        result = settle_wire_transfer(specimen_task_payload)
        assert result["status"] == "settled"
        assert mock_async.called
        kwargs = mock_async.call_args[1]
        assert kwargs["is_redelivered"] is True
        assert kwargs["worker_hostname"] == "celery@worker-node-4"
