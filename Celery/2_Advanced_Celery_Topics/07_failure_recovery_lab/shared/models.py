"""SQLAlchemy 2.0 domain database models for the Wire Settlement Gateway.

Maps the PostgreSQL 16 relational DDL defined in init.sql, covering master wire transfers,
dual-entry immutable ledger journal lines, and comprehensive audit logs.
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class WireStatus(str, Enum):
    """Enumeration of valid states for a wire transfer lifecycle."""

    PROCESSING = "processing"
    SUBMITTED_TO_BANK = "submitted_to_bank"
    SETTLED = "settled"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class LedgerDirection(str, Enum):
    """Enumeration of ledger balancing directions."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(str, Enum):
    """Enumeration of double-entry ledger account classifications."""

    CUSTOMER_CASH = "customer_cash"
    CLEARINGHOUSE_SETTLEMENT = "clearinghouse_settlement"


class Base(DeclarativeBase):
    """Base declarative class for all domain models."""


class WireTransfer(Base):
    """Master wire transfer entity tracking lifecycle, attempts, and references.

    Enforces relational uniqueness on (client_id, idempotency_key) to prevent
    duplicate wire ingestion, and uses integer cents for zero-loss financial math.
    """

    __tablename__ = "wire_transfers"

    wire_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    client_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    sender_account_mask: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    beneficiary_account_mask: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    routing_number: Mapped[str] = mapped_column(
        String(9),
        nullable=False,
    )
    swift_bic: Mapped[str] = mapped_column(
        String(11),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=WireStatus.PROCESSING.value,
    )
    delivery_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    redelivered_flag: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    bank_reference_id: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("client_id", "idempotency_key", name="uq_wire_idempotency"),
        CheckConstraint("amount_cents > 0", name="ck_wire_transfers_amount_positive"),
    )

    # Relationships
    ledger_entries: Mapped[list["LedgerJournal"]] = relationship(
        back_populates="wire",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["WireAuditLog"]] = relationship(
        back_populates="wire",
        cascade="all, delete-orphan",
    )

    def __init__(
        self,
        *,
        wire_id: uuid.UUID | None = None,
        client_id: str,
        idempotency_key: str,
        amount_cents: int,
        currency: str = "USD",
        sender_account_mask: str,
        beneficiary_account_mask: str,
        routing_number: str,
        swift_bic: str,
        status: str = WireStatus.PROCESSING.value,
        delivery_attempts: int = 1,
        redelivered_flag: bool = False,
        bank_reference_id: str | None = None,
        failure_reason: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        settled_at: datetime | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize WireTransfer domain entity with sensible financial defaults."""
        now = datetime.now(timezone.utc)
        self.wire_id = wire_id or uuid.uuid4()
        self.client_id = client_id
        self.idempotency_key = idempotency_key
        self.amount_cents = amount_cents
        self.currency = currency
        self.sender_account_mask = sender_account_mask
        self.beneficiary_account_mask = beneficiary_account_mask
        self.routing_number = routing_number
        self.swift_bic = swift_bic
        self.status = status
        self.delivery_attempts = delivery_attempts
        self.redelivered_flag = redelivered_flag
        self.bank_reference_id = bank_reference_id
        self.failure_reason = failure_reason
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.settled_at = settled_at
        super().__init__(**kwargs)


class LedgerJournal(Base):
    """Immutable double-entry ledger journal lines for financial auditability.

    Every wire transfer generates matching DEBIT and CREDIT lines in minor units.
    """

    __tablename__ = "ledger_journal"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    wire_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wire_transfers.wire_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    account_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint("direction IN ('DEBIT', 'CREDIT')", name="ck_ledger_journal_direction"),
        CheckConstraint("amount_cents > 0", name="ck_ledger_journal_amount_positive"),
    )

    # Relationship back to master wire transfer
    wire: Mapped["WireTransfer"] = relationship(
        back_populates="ledger_entries",
    )

    def __init__(
        self,
        *,
        entry_id: uuid.UUID | None = None,
        wire_id: uuid.UUID | None = None,
        account_type: str,
        direction: str,
        amount_cents: int,
        created_at: datetime | None = None,
        wire: WireTransfer | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize LedgerJournal domain entity."""
        self.entry_id = entry_id or uuid.uuid4()
        if wire is not None:
            self.wire = wire
            self.wire_id = wire.wire_id
        elif wire_id is not None:
            self.wire_id = wire_id
        self.account_type = account_type
        self.direction = direction
        self.amount_cents = amount_cents
        self.created_at = created_at or datetime.now(timezone.utc)
        super().__init__(**kwargs)


class WireAuditLog(Base):
    """Audit log capturing worker lifecycle events, crashes, and status transitions."""

    __tablename__ = "wire_audit_log"

    audit_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    wire_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("wire_transfers.wire_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    previous_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    new_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    worker_hostname: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    redelivered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    event_description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationship back to master wire transfer
    wire: Mapped["WireTransfer"] = relationship(
        back_populates="audit_logs",
    )

    def __init__(
        self,
        *,
        audit_id: int | None = None,
        wire_id: uuid.UUID | None = None,
        previous_status: str | None = None,
        new_status: str,
        worker_hostname: str | None = None,
        redelivered: bool = False,
        event_description: str,
        occurred_at: datetime | None = None,
        wire: WireTransfer | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize WireAuditLog domain entity."""
        if audit_id is not None:
            self.audit_id = audit_id
        if wire is not None:
            self.wire = wire
            self.wire_id = wire.wire_id
        elif wire_id is not None:
            self.wire_id = wire_id
        self.previous_status = previous_status
        self.new_status = new_status
        self.worker_hostname = worker_hostname
        self.redelivered = redelivered
        self.event_description = event_description
        self.occurred_at = occurred_at or datetime.now(timezone.utc)
        super().__init__(**kwargs)
