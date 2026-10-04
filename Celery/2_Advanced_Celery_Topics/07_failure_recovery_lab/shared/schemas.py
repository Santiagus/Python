"""Pydantic v2 domain schemas and wire transfer validation models.

Enforces zero-knowledge broker tokenization, strict monetary validation with
minor-unit integer cents, and realistic OpenAPI documentation examples.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def mask_account_number(account: str) -> str:
    """Mask a bank account number preserving only the final 4 digits.

    Args:
        account: Raw unmasked bank account string.

    Returns:
        str: Masked representation (e.g., '******7890').
    """
    clean_account = account.strip()
    if len(clean_account) <= 4:
        return f"******{clean_account}"
    return f"******{clean_account[-4:]}"


class WireCreateRequest(BaseModel):
    """Client wire ingestion payload with monetary and banking rail validation."""

    client_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Unique corporate client identifier",
        examples=["CORP-TREASURY-001"],
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        max_digits=14,
        decimal_places=2,
        description="Wire transfer amount in major currency units (strict Decimal)",
        examples=[Decimal("2500000.00")],
    )
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="ISO 4217 3-letter currency code",
        examples=["USD"],
    )
    beneficiary_account: str = Field(
        ...,
        min_length=4,
        max_length=34,
        description="Raw beneficiary account number (masked before broker dispatch)",
        examples=["9876543210"],
    )
    routing_number: str = Field(
        ...,
        pattern=r"^\d{9}$",
        description="9-digit Fedwire ABA routing transit number",
        examples=["121000358"],
    )
    swift_bic: str = Field(
        ...,
        pattern=r"^[A-Z0-9]{8}([A-Z0-9]{3})?$",
        description="8 or 11 character ISO 9362 SWIFT BIC",
        examples=["CHASUS33XXX"],
    )

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency_uppercase(cls, v: Any) -> Any:
        """Enforce uppercase ISO currency code."""
        return v.upper() if isinstance(v, str) else v

    @field_validator("swift_bic", mode="before")
    @classmethod
    def validate_swift_bic_uppercase(cls, v: Any) -> Any:
        """Enforce uppercase SWIFT BIC."""
        return v.upper() if isinstance(v, str) else v

    @property
    def amount_cents(self) -> int:
        """Convert Decimal major units to integer minor units (cents)."""
        return int(self.amount * 100)

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "client_id": "CORP-TREASURY-001",
                "amount": "2500000.00",
                "currency": "USD",
                "beneficiary_account": "9876543210",
                "routing_number": "121000358",
                "swift_bic": "CHASUS33XXX",
            }
        },
    )


class WireResponse(BaseModel):
    """Public wire transfer state representation for treasury read queries."""

    wire_id: uuid.UUID = Field(
        ...,
        description="System-generated unique wire transaction identifier",
    )
    client_id: str = Field(
        ...,
        description="Originating corporate client identifier",
    )
    amount_cents: int = Field(
        ...,
        gt=0,
        description="Transfer amount in integer minor units (cents)",
    )
    currency: str = Field(
        default="USD",
        description="ISO 4217 currency code",
    )
    sender_account_mask: str = Field(
        ...,
        description="Masked sender account number",
    )
    beneficiary_account_mask: str = Field(
        ...,
        description="Masked beneficiary account number",
    )
    routing_number: str = Field(
        ...,
        description="Fedwire ABA routing transit number",
    )
    swift_bic: str = Field(
        ...,
        description="SWIFT BIC code",
    )
    status: str = Field(
        ...,
        description="Current state machine status",
    )
    delivery_attempts: int = Field(
        default=1,
        ge=1,
        description="Number of worker delivery attempts",
    )
    redelivered_flag: bool = Field(
        default=False,
        description="True if delivered with AMQP redelivered flag",
    )
    bank_reference_id: str | None = Field(
        default=None,
        description="External clearinghouse reference identifier",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Terminal failure or dead-letter reason if applicable",
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp of ingestion acceptance",
    )
    updated_at: datetime = Field(
        ...,
        description="Timestamp of latest state transition",
    )
    settled_at: datetime | None = Field(
        default=None,
        description="Timestamp of clearinghouse settlement confirmation",
    )

    model_config = ConfigDict(from_attributes=True)


class WireTaskPayload(BaseModel):
    """AMQP broker message payload serialized across Celery queues.

    Contains zero unmasked financial PII, using edge-masked accounts
    and isolated disbursement tokens.
    """

    wire_id: str = Field(
        ...,
        description="UUID string of the master wire record",
    )
    client_id: str = Field(
        ...,
        description="Client identifier",
    )
    idempotency_key: str = Field(
        ...,
        description="Client-provided idempotency key",
    )
    amount_cents: int = Field(
        ...,
        gt=0,
        description="Transfer amount in cents",
    )
    currency: str = Field(
        default="USD",
        description="ISO 4217 currency code",
    )
    sender_account_mask: str = Field(
        ...,
        description="Masked sender account",
    )
    beneficiary_account_mask: str = Field(
        ...,
        description="Masked beneficiary account",
    )
    routing_number: str = Field(
        ...,
        pattern=r"^\d{9}$",
        description="9-digit Fedwire routing number",
    )
    swift_bic: str = Field(
        ...,
        pattern=r"^[A-Z0-9]{8}([A-Z0-9]{3})?$",
        description="SWIFT BIC",
    )
    disbursement_token: str = Field(
        ...,
        description="Tokenized disbursement handle for bank provider",
    )

    model_config = ConfigDict(extra="ignore")


class BankDisburseRequest(BaseModel):
    """Request payload for wholesale bank settlement disbursement."""

    idempotency_key: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Wire transfer idempotency key",
    )
    amount_cents: int = Field(
        ...,
        gt=0,
        description="Amount in integer minor units (cents)",
    )
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="ISO 4217 currency code",
    )
    beneficiary_account_mask: str = Field(
        ...,
        min_length=4,
        max_length=32,
        description="Masked beneficiary account",
    )
    routing_number: str = Field(
        ...,
        pattern=r"^\d{9}$",
        description="9-digit Fedwire routing number",
    )
    swift_bic: str = Field(
        ...,
        pattern=r"^[A-Z0-9]{8}([A-Z0-9]{3})?$",
        description="SWIFT BIC",
    )
    disbursement_token: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Tokenized settlement handle",
    )

    model_config = ConfigDict(extra="ignore")


class BankDisburseResponse(BaseModel):
    """Response payload returned by Wholesale Bank Simulator on settlement."""

    status: str = Field(
        default="CONFIRMED",
        description="Settlement status from clearinghouse",
    )
    bank_reference_id: str = Field(
        ...,
        description="Unique bank clearing reference identifier",
    )
    idempotency_key: str = Field(
        ...,
        description="Correlated idempotency key",
    )
    amount_cents: int = Field(
        ...,
        gt=0,
        description="Settled amount in minor units",
    )
    currency: str = Field(
        default="USD",
        description="Settled currency",
    )
    settled_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Clearinghouse settlement timestamp",
    )

    model_config = ConfigDict(extra="ignore")


class LedgerEntryCreate(BaseModel):
    """Internal schema for recording balanced double-entry ledger lines."""

    wire_id: uuid.UUID = Field(
        ...,
        description="Foreign key to master wire transfer",
    )
    account_type: str = Field(
        ...,
        description="Account classification (customer_cash or clearinghouse_settlement)",
    )
    direction: str = Field(
        ...,
        pattern=r"^(DEBIT|CREDIT)$",
        description="Entry direction: DEBIT or CREDIT",
    )
    amount_cents: int = Field(
        ...,
        gt=0,
        description="Entry amount in integer minor units (cents)",
    )


class WireAuditLogCreate(BaseModel):
    """Internal schema for recording state transitions and recovery events."""

    wire_id: uuid.UUID = Field(
        ...,
        description="Foreign key to master wire transfer",
    )
    previous_status: str | None = Field(
        default=None,
        description="Previous lifecycle state before transition",
    )
    new_status: str = Field(
        ...,
        description="New lifecycle state after transition",
    )
    worker_hostname: str | None = Field(
        default=None,
        description="Hostname of worker child process",
    )
    redelivered: bool = Field(
        default=False,
        description="True if event occurred on redelivered task",
    )
    event_description: str = Field(
        ...,
        min_length=1,
        description="Detailed description of lifecycle transition",
    )
