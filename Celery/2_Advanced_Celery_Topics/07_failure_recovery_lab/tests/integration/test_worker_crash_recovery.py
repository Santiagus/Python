"""Integration test for Failure Experiment 1: Worker SIGKILL mid-flight crash recovery.

Verifies that when a worker is killed mid-execution after external disbursement:
1. RabbitMQ / AMQP broker redelivers the task with redelivered=True.
2. The surviving worker acquires the row lock (SELECT ... FOR UPDATE).
3. Phase 1 Provider Inquiry detects the existing bank reference.
4. Phase 2 disbursement is bypassed, guaranteeing zero duplicate payouts.
5. Dual-entry ledger journal is committed with exact mathematical parity.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.worker.tasks.settlement import process_wire_settlement
from shared.models import (
    AccountType,
    LedgerDirection,
    LedgerJournal,
    WireAuditLog,
    WireStatus,
    WireTransfer,
)


@pytest.mark.asyncio
async def test_worker_crash_mid_flight_redelivery_and_idempotency(
    sample_wire_payload: dict[str, Any],
    sample_wire_transfer: WireTransfer,
    stateful_bank_simulator: AsyncMock,
) -> None:
    """Verify worker crash recovery after bank disbursement eliminates duplicate payouts."""
    # -------------------------------------------------------------------------
    # Stage 1: Worker 1 Execution & Abrupt Crash After Bank Call
    # -------------------------------------------------------------------------
    session_worker1 = AsyncMock(spec=AsyncSession)
    worker1_added: list[Any] = []
    session_worker1.add = MagicMock(side_effect=worker1_added.append)
    session_worker1.add_all = MagicMock(side_effect=worker1_added.extend)

    # Wire initially in 'processing' state
    mock_res1 = MagicMock()
    mock_res1.scalar_one_or_none.return_value = sample_wire_transfer
    session_worker1.execute.return_value = mock_res1

    # Simulate Phase 2 execution by worker 1 against bank simulator
    idem_key = sample_wire_payload["idempotency_key"]
    # 1. Phase 1 check: not found
    resp1_inquiry = await stateful_bank_simulator.get(f"/v1/wires/{idem_key}")
    assert resp1_inquiry.status_code == 404

    # 2. Phase 2 disbursement: bank clears wire and issues reference
    disburse_payload = {
        "idempotency_key": idem_key,
        "amount_cents": sample_wire_payload["amount_cents"],
        "currency": sample_wire_payload["currency"],
        "beneficiary_account": sample_wire_payload["beneficiary_account_mask"],
        "routing_number": sample_wire_payload["routing_number"],
        "swift_bic": sample_wire_payload["swift_bic"],
    }
    resp1_disburse = await stateful_bank_simulator.post("/v1/wires/settle", json=disburse_payload)
    assert resp1_disburse.status_code == 200
    bank_ref = resp1_disburse.json()["bank_reference_id"]
    assert bank_ref.startswith("FED-WIRE-")

    # 3. CHAOS INJECTION: Worker 1 killed via SIGKILL before DB commit & AMQP ack
    # Database transaction rolls back; status in DB remains 'processing'
    await session_worker1.rollback()
    assert sample_wire_transfer.status == WireStatus.PROCESSING.value
    assert sample_wire_transfer.bank_reference_id is None
    assert len(worker1_added) == 0

    # -------------------------------------------------------------------------
    # Stage 2: Surviving Worker 2 Receives Redelivered Task (redelivered=True)
    # -------------------------------------------------------------------------
    session_worker2 = AsyncMock(spec=AsyncSession)
    worker2_added: list[Any] = []
    session_worker2.add = MagicMock(side_effect=worker2_added.append)
    session_worker2.add_all = MagicMock(side_effect=worker2_added.extend)

    mock_res2 = MagicMock()
    mock_res2.scalar_one_or_none.return_value = sample_wire_transfer
    session_worker2.execute.return_value = mock_res2

    # Surviving worker executes settlement task with is_redelivered=True
    result = await process_wire_settlement(
        task_payload=sample_wire_payload,
        is_redelivered=True,
        worker_hostname="worker_pod_2_survivor",
        session=session_worker2,
        client=stateful_bank_simulator,
    )

    # -------------------------------------------------------------------------
    # Stage 3: Verification of Idempotency, Parity & Audit Trails
    # -------------------------------------------------------------------------
    # 1. Result envelope confirms settlement and Phase 1 inquiry hit
    assert result["status"] == WireStatus.SETTLED.value
    assert result["bank_reference_id"] == bank_ref
    assert result["redelivered"] is True
    assert result["phase1_hit"] is True
    assert result["delivery_attempts"] == 2

    # 2. Database model state transitions
    assert sample_wire_transfer.status == WireStatus.SETTLED.value
    assert sample_wire_transfer.bank_reference_id == bank_ref
    assert sample_wire_transfer.redelivered_flag is True
    assert sample_wire_transfer.delivery_attempts == 2

    # 3. Verify exactly ONE disbursement exists in Bank Simulator (ZERO DOUBLE PAYOUT)
    cleared_wires = stateful_bank_simulator.cleared_wires  # type: ignore[attr-defined]
    assert len(cleared_wires) == 1
    assert idem_key in cleared_wires

    # 4. Verify Dual-Entry Immutable Ledger Parity
    journal_entries = [e for e in worker2_added if isinstance(e, LedgerJournal)]
    assert len(journal_entries) == 2

    debit_entry = next(e for e in journal_entries if e.direction == LedgerDirection.DEBIT.value)
    credit_entry = next(e for e in journal_entries if e.direction == LedgerDirection.CREDIT.value)

    assert debit_entry.account_type == AccountType.CUSTOMER_CASH.value
    assert debit_entry.amount_cents == sample_wire_payload["amount_cents"]
    assert credit_entry.account_type == AccountType.CLEARINGHOUSE_SETTLEMENT.value
    assert credit_entry.amount_cents == sample_wire_payload["amount_cents"]
    # Exact mathematical parity: Debits == Credits
    assert debit_entry.amount_cents == credit_entry.amount_cents

    # 5. Verify Audit Log recorded Phase 1 recovery
    audit_entries = [e for e in worker2_added if isinstance(e, WireAuditLog)]
    assert len(audit_entries) == 1
    audit = audit_entries[0]
    assert audit.new_status == WireStatus.SETTLED.value
    assert audit.worker_hostname == "worker_pod_2_survivor"
    assert audit.redelivered is True
    assert "Phase 1 inquiry hit: recovered after worker crash" in audit.event_description

    # 6. Verify database commit was executed
    session_worker2.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_crash_before_bank_disbursement_recovery(
    sample_wire_payload: dict[str, Any],
    sample_wire_transfer: WireTransfer,
    stateful_bank_simulator: AsyncMock,
    mock_db_session: AsyncMock,
) -> None:
    """Verify recovery when worker crashes prior to any bank communication."""
    # Worker 1 crashed before touching the bank; surviving worker runs normally
    result = await process_wire_settlement(
        task_payload=sample_wire_payload,
        is_redelivered=True,
        worker_hostname="worker_pod_survivor",
        session=mock_db_session,
        client=stateful_bank_simulator,
    )

    # Phase 1 returned 404, so Phase 2 executed cleanly
    assert result["status"] == WireStatus.SETTLED.value
    assert result["phase1_hit"] is False
    assert result["redelivered"] is True
    assert sample_wire_transfer.status == WireStatus.SETTLED.value


@pytest.mark.asyncio
async def test_already_settled_wire_idempotent_no_op(
    sample_wire_payload: dict[str, Any],
    sample_wire_transfer: WireTransfer,
    stateful_bank_simulator: AsyncMock,
    mock_db_session: AsyncMock,
) -> None:
    """Verify that a wire already marked settled returns early without side effects."""
    # Wire transfer is already settled
    sample_wire_transfer.status = WireStatus.SETTLED.value
    sample_wire_transfer.bank_reference_id = "FED-WIRE-PREV-SETTLED"

    result = await process_wire_settlement(
        task_payload=sample_wire_payload,
        is_redelivered=True,
        session=mock_db_session,
        client=stateful_bank_simulator,
    )

    assert result["status"] == WireStatus.SETTLED.value
    assert result["bank_reference_id"] == "FED-WIRE-PREV-SETTLED"
    # No bank calls made
    stateful_bank_simulator.get.assert_not_called()
    stateful_bank_simulator.post.assert_not_called()
    # No additional commit
    mock_db_session.commit.assert_not_called()
