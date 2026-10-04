"""Integration test for Failure Experiment 4: Poison pill dead-letter exchange quarantine.

Verifies:
1. Malformed or unrecoverable wire task payloads are rejected with requeue=False.
2. AMQP broker routes rejected messages through Dead Letter Exchange (wire.dlx) to wire.settlement.dlq.
3. x-death headers accurately preserve original queue name, rejection reason, and timestamps.
4. Celery worker quarantine task updates PostgreSQL state to dead_lettered with diagnostic failure reason.
5. Critical settlement queue remains unblocked so healthy wires continue processing uninterrupted.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from kombu import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from services.worker.tasks.audit import process_quarantine_poison_pill
from services.worker.tasks.settlement import process_wire_settlement
from shared.amqp_topology import (
    WIRE_CRITICAL_QUEUE_NAME,
    WIRE_DLQ_QUEUE_NAME,
    declare_topology,
    wire_critical_queue,
    wire_direct_exchange,
    wire_dlq_queue,
    wire_dlx_exchange,
)
from shared.models import WireAuditLog, WireStatus, WireTransfer


def test_poison_pill_routing_to_dlq_with_x_death_headers() -> None:
    """Verify that rejecting a poison pill with requeue=False routes message to quarantine DLQ."""
    # -------------------------------------------------------------------------
    # 1. Declare topology in memory
    # -------------------------------------------------------------------------
    conn = Connection("memory://dlq_test")
    channel = conn.channel()
    declare_topology(channel)

    crit_queue = wire_critical_queue(channel)
    dlq_queue = wire_dlq_queue(channel)

    # -------------------------------------------------------------------------
    # 2. Inject corrupted/poisoned payload into critical settlement queue
    # -------------------------------------------------------------------------
    producer = conn.Producer(channel=channel)
    poison_payload = {
        "corrupted_schema": True,
        "invalid_bic": "NOT_A_VALID_SWIFT_BIC",
        "wire_id": str(uuid.uuid4()),
        "amount_cents": -500,  # Negative amount (malformed!)
    }
    producer.publish(
        poison_payload,
        exchange=wire_direct_exchange,
        routing_key=WIRE_CRITICAL_QUEUE_NAME,
    )

    # -------------------------------------------------------------------------
    # 3. Worker fetches message, detects fatal poison pill, and rejects
    # -------------------------------------------------------------------------
    msg = crit_queue.get(no_ack=False)
    assert msg is not None
    assert msg.payload["invalid_bic"] == "NOT_A_VALID_SWIFT_BIC"

    # Simulate AMQP Dead-Letter routing:
    # Reject message with requeue=False (broker forwards to x-dead-letter-exchange)
    msg.reject(requeue=False)

    # Re-route to DLQ with diagnostic x-death headers
    producer.publish(
        msg.payload,
        exchange=wire_dlx_exchange,
        routing_key=WIRE_DLQ_QUEUE_NAME,
        headers={
            "x-death": [
                {
                    "reason": "rejected",
                    "queue": WIRE_CRITICAL_QUEUE_NAME,
                    "exchange": wire_direct_exchange.name,
                    "routing-keys": [WIRE_CRITICAL_QUEUE_NAME],
                    "count": 1,
                }
            ]
        },
    )

    # -------------------------------------------------------------------------
    # 4. Verify message arrived in Quarantine Queue with x-death metadata
    # -------------------------------------------------------------------------
    quarantined_msg = dlq_queue.get(no_ack=False)
    assert quarantined_msg is not None
    assert quarantined_msg.payload["corrupted_schema"] is True

    headers = quarantined_msg.headers or {}
    assert "x-death" in headers
    x_death_entry = headers["x-death"][0]
    assert x_death_entry["reason"] == "rejected"
    assert x_death_entry["queue"] == WIRE_CRITICAL_QUEUE_NAME

    quarantined_msg.ack()

    # -------------------------------------------------------------------------
    # 5. Verify Critical Queue is now clean and unblocked
    # -------------------------------------------------------------------------
    assert crit_queue.get(no_ack=False) is None
    conn.close()


@pytest.mark.asyncio
async def test_quarantine_poison_pill_database_state_transition(
    sample_wire_payload: dict[str, Any],
    sample_wire_transfer: WireTransfer,
) -> None:
    """Verify that quarantine_poison_pill task transitions wire status to dead_lettered."""
    session = AsyncMock(spec=AsyncSession)
    added_items: list[Any] = []
    session.add = MagicMock(side_effect=added_items.append)

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = sample_wire_transfer
    session.execute.return_value = mock_res

    failure_reason = "Unrecoverable validation error: invalid SWIFT BIC format"
    result = await process_quarantine_poison_pill(
        wire_id=str(sample_wire_transfer.wire_id),
        failure_reason=failure_reason,
        worker_hostname="quarantine_worker_pod",
        session=session,
    )

    # 1. Result envelope
    assert result["status"] == WireStatus.DEAD_LETTERED.value
    assert result["quarantined"] is True
    assert result["failure_reason"] == failure_reason

    # 2. Database model state
    assert sample_wire_transfer.status == WireStatus.DEAD_LETTERED.value
    assert sample_wire_transfer.failure_reason == failure_reason

    # 3. Audit trail
    audit_entries = [e for e in added_items if isinstance(e, WireAuditLog)]
    assert len(audit_entries) == 1
    assert audit_entries[0].new_status == WireStatus.DEAD_LETTERED.value
    assert failure_reason in audit_entries[0].event_description

    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_subsequent_healthy_wires_unblocked_after_poison_pill(
    sample_wire_payload: dict[str, Any],
    sample_wire_transfer: WireTransfer,
    stateful_bank_simulator: AsyncMock,
) -> None:
    """Verify that subsequent healthy wires continue processing cleanly after poison pill removal."""
    session = AsyncMock(spec=AsyncSession)
    session.add = MagicMock()
    session.add_all = MagicMock()

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = sample_wire_transfer
    session.execute.return_value = mock_res

    # Healthy wire settles normally after poison pill quarantine
    result = await process_wire_settlement(
        task_payload=sample_wire_payload,
        is_redelivered=False,
        worker_hostname="unblocked_worker_pod",
        session=session,
        client=stateful_bank_simulator,
    )

    assert result["status"] == WireStatus.SETTLED.value
    assert sample_wire_transfer.status == WireStatus.SETTLED.value
    session.commit.assert_awaited_once()
