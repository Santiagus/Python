"""Unit tests for SQLAlchemy 2.0 domain database models in shared/models.py."""

import uuid
from datetime import datetime, timezone

from shared.models import (
    AccountType,
    Base,
    LedgerDirection,
    LedgerJournal,
    WireAuditLog,
    WireStatus,
    WireTransfer,
)


def test_domain_enums() -> None:
    """Verify that domain enums contain required financial lifecycle values."""
    # 1. WireStatus enum values
    assert WireStatus.PROCESSING.value == "processing"
    assert WireStatus.SUBMITTED_TO_BANK.value == "submitted_to_bank"
    assert WireStatus.SETTLED.value == "settled"
    assert WireStatus.FAILED.value == "failed"
    assert WireStatus.DEAD_LETTERED.value == "dead_lettered"

    # 2. LedgerDirection enum values
    assert LedgerDirection.DEBIT.value == "DEBIT"
    assert LedgerDirection.CREDIT.value == "CREDIT"

    # 3. AccountType enum values
    assert AccountType.CUSTOMER_CASH.value == "customer_cash"
    assert AccountType.CLEARINGHOUSE_SETTLEMENT.value == "clearinghouse_settlement"


def test_wire_transfer_model_instantiation() -> None:
    """Verify WireTransfer model field defaults and structure."""
    wire_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    wire = WireTransfer(
        wire_id=wire_id,
        client_id="corp-client-001",
        idempotency_key="idemp-key-100",
        amount_cents=5000000,
        sender_account_mask="******1234",
        beneficiary_account_mask="******5678",
        routing_number="121000358",
        swift_bic="CHASUS33XXX",
        created_at=now,
        updated_at=now,
    )

    # 1. Verify core attributes and default values
    assert wire.wire_id == wire_id
    assert wire.client_id == "corp-client-001"
    assert wire.idempotency_key == "idemp-key-100"
    assert wire.amount_cents == 5000000
    assert wire.currency == "USD"
    assert wire.status == "processing"
    assert wire.delivery_attempts == 1
    assert wire.redelivered_flag is False
    assert wire.bank_reference_id is None
    assert wire.failure_reason is None
    assert wire.settled_at is None
    assert wire.created_at == now
    assert wire.updated_at == now


def test_ledger_journal_model_instantiation() -> None:
    """Verify LedgerJournal model field values and foreign key association."""
    entry_id = uuid.uuid4()
    wire_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    entry = LedgerJournal(
        entry_id=entry_id,
        wire_id=wire_id,
        account_type=AccountType.CUSTOMER_CASH.value,
        direction=LedgerDirection.DEBIT.value,
        amount_cents=5000000,
        created_at=now,
    )

    # 1. Verify attributes
    assert entry.entry_id == entry_id
    assert entry.wire_id == wire_id
    assert entry.account_type == "customer_cash"
    assert entry.direction == "DEBIT"
    assert entry.amount_cents == 5000000
    assert entry.created_at == now


def test_wire_audit_log_model_instantiation() -> None:
    """Verify WireAuditLog model field values and default flags."""
    wire_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    log = WireAuditLog(
        audit_id=1,
        wire_id=wire_id,
        previous_status=WireStatus.PROCESSING.value,
        new_status=WireStatus.SETTLED.value,
        worker_hostname="worker-pod-1",
        redelivered=True,
        event_description="Settled successfully on redelivery",
        occurred_at=now,
    )

    # 1. Verify attributes
    assert log.audit_id == 1
    assert log.wire_id == wire_id
    assert log.previous_status == "processing"
    assert log.new_status == "settled"
    assert log.worker_hostname == "worker-pod-1"
    assert log.redelivered is True
    assert log.event_description == "Settled successfully on redelivery"
    assert log.occurred_at == now


def test_models_relationships() -> None:
    """Verify bidirectional relationships between WireTransfer, LedgerJournal, and WireAuditLog."""
    wire = WireTransfer(
        wire_id=uuid.uuid4(),
        client_id="corp-client-002",
        idempotency_key="idemp-key-200",
        amount_cents=100000,
        sender_account_mask="******1111",
        beneficiary_account_mask="******2222",
        routing_number="121000358",
        swift_bic="BOFAUS3NXXX",
    )

    entry_debit = LedgerJournal(
        entry_id=uuid.uuid4(),
        wire=wire,
        account_type=AccountType.CUSTOMER_CASH.value,
        direction=LedgerDirection.DEBIT.value,
        amount_cents=100000,
    )
    entry_credit = LedgerJournal(
        entry_id=uuid.uuid4(),
        wire=wire,
        account_type=AccountType.CLEARINGHOUSE_SETTLEMENT.value,
        direction=LedgerDirection.CREDIT.value,
        amount_cents=100000,
    )
    audit = WireAuditLog(
        wire=wire,
        previous_status=None,
        new_status=WireStatus.PROCESSING.value,
        event_description="Ingestion accepted",
    )

    # 1. Verify relationships mapped properly
    assert len(wire.ledger_entries) == 2
    assert wire.ledger_entries[0] == entry_debit
    assert wire.ledger_entries[1] == entry_credit
    assert len(wire.audit_logs) == 1
    assert wire.audit_logs[0] == audit
    assert entry_debit.wire == wire
    assert audit.wire == wire


def test_declarative_tables_metadata() -> None:
    """Verify table names, constraints, and column definitions in SQLAlchemy metadata."""
    tables = Base.metadata.tables
    assert "wire_transfers" in tables
    assert "ledger_journal" in tables
    assert "wire_audit_log" in tables

    # 1. Verify wire_transfers table constraints
    wire_table = tables["wire_transfers"]
    constraint_names = {c.name for c in wire_table.constraints}
    assert "uq_wire_idempotency" in constraint_names
    assert "ck_wire_transfers_amount_positive" in constraint_names

    # 2. Verify ledger_journal table constraints
    ledger_table = tables["ledger_journal"]
    ledger_constraints = {c.name for c in ledger_table.constraints}
    assert "ck_ledger_journal_direction" in ledger_constraints
    assert "ck_ledger_journal_amount_positive" in ledger_constraints
