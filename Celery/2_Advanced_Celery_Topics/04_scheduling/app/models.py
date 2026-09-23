"""SQLAlchemy 2.0 Declarative ORM models for accounts, ledger entries, and reconciliation reports.

Enforces strict relational integrity, minor-unit financial storage in BigInteger cents,
check constraints, and optimized index layouts for scheduled reconciliation.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for all application ORM models."""


class Account(Base):
    """Internal corporate or treasury ledger account holding balances in minor-unit cents."""

    __tablename__ = "accounts"

    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_number: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        nullable=False,
    )
    account_mask: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    account_type: Mapped[str] = mapped_column(
        String(32),
        CheckConstraint(
            "account_type IN ('operating', 'settlement', 'reserve', 'clearing')",
            name="chk_account_type_valid",
        ),
        nullable=False,
        default="operating",
    )
    balance_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("balance_cents >= 0", name="chk_account_balance_non_negative"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    entries: Mapped[list[LedgerEntry]] = relationship(
        "LedgerEntry",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        """Return developer-friendly string representation."""
        return (
            f"<Account(id={self.account_id}, number={self.account_number}, "
            f"type={self.account_type}, balance_cents={self.balance_cents})>"
        )


class LedgerEntry(Base):
    """Double-entry posted financial transaction assigned to a banking business period."""

    __tablename__ = "ledger_entries"

    entry_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.account_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("amount_cents > 0", name="chk_ledger_amount_positive"),
        nullable=False,
    )
    direction: Mapped[str] = mapped_column(
        String(8),
        CheckConstraint("direction IN ('credit', 'debit')", name="chk_ledger_direction_valid"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        CheckConstraint(
            "status IN ('pending', 'posted', 'cleared', 'cancelled')",
            name="chk_ledger_status_valid",
        ),
        nullable=False,
        default="posted",
    )
    period_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Composite Index for high-velocity daily cut-off queries
    __table_args__ = (Index("idx_ledger_entries_period_status", "period_date", "status"),)

    # Relationships
    account: Mapped[Account] = relationship(
        "Account",
        back_populates="entries",
        lazy="joined",
    )

    def __repr__(self) -> str:
        """Return developer-friendly string representation."""
        return (
            f"<LedgerEntry(id={self.entry_id}, date={self.period_date}, "
            f"direction={self.direction}, amount_cents={self.amount_cents})>"
        )


class ReconciliationReport(Base):
    """Immutable daily financial reconciliation report enforcing UNIQUE (period_date)."""

    __tablename__ = "reconciliation_reports"

    report_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    period_date: Mapped[date] = mapped_column(
        Date,
        unique=True,
        nullable=False,
        index=True,
    )
    total_credits_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("total_credits_cents >= 0", name="chk_report_credits_non_negative"),
        nullable=False,
        default=0,
    )
    total_debits_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("total_debits_cents >= 0", name="chk_report_debits_non_negative"),
        nullable=False,
        default=0,
    )
    net_movement_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=0,
    )
    discrepancy_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("discrepancy_cents >= 0", name="chk_report_discrepancy_non_negative"),
        nullable=False,
        default=0,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        CheckConstraint(
            "status IN ('pending', 'processing', 'balanced', 'discrepancy_detected', 'failed')",
            name="chk_report_status_valid",
        ),
        nullable=False,
        default="pending",
    )
    verification_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
    )
    reconciled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        """Return developer-friendly string representation."""
        return (
            f"<ReconciliationReport(id={self.report_id}, date={self.period_date}, "
            f"status={self.status}, discrepancy_cents={self.discrepancy_cents})>"
        )


class IdempotencyRecord(Base):
    """Tracks ephemeral request idempotency keys and TTLs for scheduled purging."""

    __tablename__ = "idempotency_records"

    key: Mapped[str] = mapped_column(
        String(128),
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="general",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        """Return developer-friendly string representation."""
        return f"<IdempotencyRecord(key={self.key}, scope={self.scope}, expires_at={self.expires_at})>"
