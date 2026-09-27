"""SQLAlchemy 2.0 Declarative ORM models for Card Disputes.

Maps the 'card_disputes' table schema with integer cents constraints,
unique transaction idempotency, and partial status indexing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""

    pass


class CardDispute(Base):
    """Card dispute transaction model mapping to 'card_disputes' table."""

    __tablename__ = "card_disputes"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="chk_card_disputes_amount_cents_positive"),
        CheckConstraint("attempt_count >= 1", name="chk_card_disputes_attempt_count_positive"),
        Index("idx_card_disputes_active_status", "status", postgresql_where="status IN ('pending', 'processing')"),
        Index("idx_card_disputes_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    card_token: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    card_last_four: Mapped[str] = mapped_column(
        String(4),
        nullable=False,
    )
    amount_cents: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        default="USD",
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    evidence_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default="processing",
        nullable=False,
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    network_reference_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
