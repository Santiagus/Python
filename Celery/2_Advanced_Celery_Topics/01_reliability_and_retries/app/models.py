from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TransactionStatus(StrEnum):
    PENDING = "pending"
    SYNCING = "syncing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    external_reference: Mapped[str] = mapped_column(String(255), unique=True)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="transactions_amount_positive"),
        Index("transactions_status_retry_idx", "status", "next_retry_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"))
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[TransactionStatus] = mapped_column(String(32), default=TransactionStatus.PENDING)
    provider_status: Mapped[str | None] = mapped_column(String(64))
    sync_attempts: Mapped[int] = mapped_column(default=0)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    account: Mapped[Account] = relationship(back_populates="transactions")


class SyncAttempt(Base):
    __tablename__ = "sync_attempts"
    __table_args__ = (
        Index("sync_attempts_transaction_idx", "transaction_id"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("transactions.id"))
    celery_task_id: Mapped[str] = mapped_column(String(255))
    attempt_number: Mapped[int] = mapped_column()
    outcome: Mapped[str] = mapped_column(String(32))
    provider_http_status: Mapped[int | None] = mapped_column()
    error_type: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
