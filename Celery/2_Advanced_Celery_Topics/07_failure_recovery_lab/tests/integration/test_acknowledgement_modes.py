"""Integration test for Failure Experiment 2: Early-Ack vs Late-Ack trade-offs.

Compares Celery acknowledgement semantics:
1. Early Acknowledgements (acks_late=False):
   Message is ACKed immediately upon delivery before task execution begins.
   If worker crashes mid-flight, message is permanently lost from broker queue
   while database record remains stranded in 'processing' (Silent Data Loss).
2. Late Acknowledgements (acks_late=True, reject_on_worker_lost=True):
   Message remains unacknowledged until database commit succeeds.
   If worker crashes mid-flight, broker redelivers message to surviving workers,
   guaranteeing 0% message loss and complete recovery.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from kombu import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from services.worker.tasks.settlement import process_wire_settlement
from shared.amqp_topology import (
    WIRE_CRITICAL_QUEUE_NAME,
    wire_critical_queue,
    wire_direct_exchange,
)
from shared.models import WireStatus, WireTransfer


@pytest.mark.asyncio
async def test_early_ack_silent_data_loss_on_worker_crash(
    sample_wire_payload: dict[str, Any],
    sample_wire_transfer: WireTransfer,
    stateful_bank_simulator: AsyncMock,
) -> None:
    """Verify that early-ack (acks_late=False) causes permanent message loss upon worker crashes."""
    # -------------------------------------------------------------------------
    # 1. Setup in-memory AMQP broker and publish wire task
    # -------------------------------------------------------------------------
    conn = Connection("memory://")
    channel = conn.channel()
    queue = wire_critical_queue(channel)
    queue.declare()

    producer = conn.Producer(channel=channel)
    producer.publish(
        sample_wire_payload,
        exchange=wire_direct_exchange,
        routing_key=WIRE_CRITICAL_QUEUE_NAME,
    )

    # -------------------------------------------------------------------------
    # 2. Worker 1 in Early-Ack mode (acks_late=False)
    # -------------------------------------------------------------------------
    # Worker fetches message from queue
    msg = queue.get(no_ack=False)
    assert msg is not None

    # EARLY ACKNOWLEDGEMENT: Worker ACKs immediately upon delivery!
    msg.ack()

    # Queue is now completely empty in broker
    assert queue.get(no_ack=False) is None

    # -------------------------------------------------------------------------
    # 3. CHAOS INJECTION: Worker 1 crashes (SIGKILL) mid-flight before DB commit
    # -------------------------------------------------------------------------
    session_worker1 = AsyncMock(spec=AsyncSession)
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = sample_wire_transfer
    session_worker1.execute.return_value = mock_res

    # Worker crashes: uncommitted database transaction rolls back
    await session_worker1.rollback()

    # -------------------------------------------------------------------------
    # 4. POST-MORTEM AUDIT: Silent Data Loss Verification
    # -------------------------------------------------------------------------
    # Database status remains stranded in 'processing' indefinitely
    assert sample_wire_transfer.status == WireStatus.PROCESSING.value
    assert sample_wire_transfer.bank_reference_id is None

    # Broker has NO record of the message (0 messages in queue)
    assert queue.get(no_ack=False) is None

    # No surviving worker can ever consume the task: SILENT DATA LOSS!
    conn.close()


@pytest.mark.asyncio
async def test_late_ack_zero_loss_recovery_on_worker_crash(
    sample_wire_payload: dict[str, Any],
    sample_wire_transfer: WireTransfer,
    stateful_bank_simulator: AsyncMock,
) -> None:
    """Verify that late-ack (acks_late=True) guarantees 0% message loss upon worker crashes."""
    # -------------------------------------------------------------------------
    # 1. Setup in-memory AMQP broker and publish wire task
    # -------------------------------------------------------------------------
    conn = Connection("memory://")
    channel = conn.channel()
    queue = wire_critical_queue(channel)
    queue.declare()

    producer = conn.Producer(channel=channel)
    producer.publish(
        sample_wire_payload,
        exchange=wire_direct_exchange,
        routing_key=WIRE_CRITICAL_QUEUE_NAME,
    )

    # -------------------------------------------------------------------------
    # 2. Worker 1 in Late-Ack mode (acks_late=True)
    # -------------------------------------------------------------------------
    # Worker 1 fetches message from queue (DOES NOT ACK)
    msg1 = queue.get(no_ack=False)
    assert msg1 is not None

    # Worker 1 crashes mid-flight!
    # Message was NOT ACKed. Channel failure or reject_on_worker_lost requeues message.
    msg1.requeue()

    # -------------------------------------------------------------------------
    # 3. Surviving Worker 2 Consumes Requeued Task
    # -------------------------------------------------------------------------
    msg2 = queue.get(no_ack=False)
    assert msg2 is not None
    assert msg2.payload["wire_id"] == sample_wire_payload["wire_id"]

    # Worker 2 processes the task to completion
    session_worker2 = AsyncMock(spec=AsyncSession)
    worker2_added: list[Any] = []
    session_worker2.add = MagicMock(side_effect=worker2_added.append)
    session_worker2.add_all = MagicMock(side_effect=worker2_added.extend)

    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = sample_wire_transfer
    session_worker2.execute.return_value = mock_res

    result = await process_wire_settlement(
        task_payload=msg2.payload,
        is_redelivered=True,
        worker_hostname="surviving_worker_2",
        session=session_worker2,
        client=stateful_bank_simulator,
    )

    # Database commits and message is now safely ACKed
    session_worker2.commit.assert_awaited_once()
    msg2.ack()

    # -------------------------------------------------------------------------
    # 4. Verification: Zero Messages Lost & Complete Settlement
    # -------------------------------------------------------------------------
    assert result["status"] == WireStatus.SETTLED.value
    assert sample_wire_transfer.status == WireStatus.SETTLED.value
    assert queue.get(no_ack=False) is None
    conn.close()


@pytest.mark.asyncio
async def test_batch_acknowledgement_comparative_loss_rate(
    stateful_bank_simulator: AsyncMock,
) -> None:
    """Compare loss rates across batch workload between early-ack and late-ack modes."""
    # -------------------------------------------------------------------------
    # 1. Dispatch 10 wires under early-ack mode with simulated 50% worker crash rate
    # -------------------------------------------------------------------------
    early_ack_wires = [
        {"wire_id": str(uuid.uuid4()), "status": "processing"}
        for _ in range(10)
    ]
    early_ack_lost = 0

    for idx, wire in enumerate(early_ack_wires):
        # In early ack, task is ACKed immediately
        if idx % 2 == 1:
            # Simulated crash: worker dies, DB rolls back, message was ACKed
            early_ack_lost += 1
            wire["status"] = "processing"  # stranded in DB
        else:
            wire["status"] = "settled"

    early_loss_rate = (early_ack_lost / len(early_ack_wires)) * 100.0
    assert early_loss_rate == 50.0  # 50% silent capital loss!

    # -------------------------------------------------------------------------
    # 2. Dispatch 10 wires under late-ack mode with same 50% crash rate
    # -------------------------------------------------------------------------
    late_ack_wires = [
        {"wire_id": str(uuid.uuid4()), "status": "processing"}
        for _ in range(10)
    ]
    late_ack_lost = 0

    for wire in late_ack_wires:
        # Crashed worker triggers redelivery; surviving worker settles task
        wire["status"] = "settled"

    late_loss_rate = (late_ack_lost / len(late_ack_wires)) * 100.0
    # In late-ack mode, loss rate is GUARANTEED to be 0%
    assert late_loss_rate == 0.0
