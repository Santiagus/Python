"""SQLAlchemy 2.0 Declarative ORM models for accounts, payments, and batch settlements.

Enforces strict relational integrity, minor-unit financial storage in BigInteger cents,
check constraints, and optimized index layouts for high-throughput payment rails.
"""

from __future__ import annotations

from datetime import datetime
import uuid
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class for all application ORM models."""
    pass


class Account(Base):
    """Enterprise funding source account holding liquidity in minor-unit cents."""

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
    balance_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("balance_cents >= 0", name="chk_account_balance_positive"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    payments: Mapped[list[Payment]] = relationship(
        "Payment",
        back_populates="source_account",
        lazy="selectin",
    )
    batch_settlements: Mapped[list[BatchSettlement]] = relationship(
        "BatchSettlement",
        back_populates="source_account",
        lazy="selectin",
    )


class Payment(Base):
    """Real-time instant payout or single payment transaction record."""

    __tablename__ = "payments"

    payment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
    )
    source_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.account_id"),
        nullable=False,
        index=True,
    )
    destination_account_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    destination_routing_number: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("amount_cents > 0", name="chk_payment_amount_positive"),
        nullable=False,
    )
    rail: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )  # 'fednow', 'rtp', 'ach'
    priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )  # 'critical', 'default', 'bulk'
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )  # 'pending', 'processing', 'settled', 'failed', 'rejected'
    cleared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    source_account: Mapped[Account] = relationship(
        "Account",
        back_populates="payments",
    )


class BatchSettlement(Base):
    """High-volume batch payroll or supplier disbursement parent file metadata."""

    __tablename__ = "batch_settlements"

    batch_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    file_reference: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    source_account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("accounts.account_id"),
        nullable=False,
        index=True,
    )
    total_items: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("total_items > 0", name="chk_batch_total_items_positive"),
        nullable=False,
    )
    total_amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("total_amount_cents > 0", name="chk_batch_total_amount_positive"),
        nullable=False,
    )
    processed_items: Mapped[int] = mapped_column(
        Integer,
        CheckConstraint("processed_items >= 0", name="chk_batch_processed_items_non_negative"),
        nullable=False,
        default=0,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )  # 'pending', 'processing', 'completed', 'partially_failed', 'failed'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    source_account: Mapped[Account] = relationship(
        "Account",
        back_populates="batch_settlements",
    )
    disbursements: Mapped[list[Disbursement]] = relationship(
        "Disbursement",
        back_populates="batch",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Disbursement(Base):
    """Individual disbursement item within a high-volume batch settlement."""

    __tablename__ = "disbursements"

    disbursement_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    batch_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("batch_settlements.batch_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    account_number: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    routing_number: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        CheckConstraint("amount_cents > 0", name="chk_disbursement_amount_positive"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )  # 'pending', 'processing', 'settled', 'failed', 'rejected'
    error_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    external_reference: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    batch: Mapped[BatchSettlement] = relationship(
        "BatchSettlement",
        back_populates="disbursements",
    )

