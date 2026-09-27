"""Pydantic v2 schemas and validation models for the screening API gateway.

Enforces Decimal financial precision, minor-unit conversion, and realistic Swagger specimens.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScreeningRequest(BaseModel):
    """Incoming payment transaction screening request payload."""

    transaction_id: str = Field(
        ...,
        min_length=4,
        max_length=64,
        description="Globally unique transaction idempotency identifier.",
        examples=["tx-88392-corp-99"],
    )
    account_id: str = Field(
        ...,
        min_length=4,
        max_length=64,
        description="Originating customer or corporate account ID.",
        examples=["acct-us-99214"],
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        description="Monetary transaction volume expressed in major financial units.",
        examples=[Decimal("4500.00")],
    )
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        description="Three-letter ISO 4217 currency code.",
        examples=["USD"],
    )
    client_ip: str = Field(
        ...,
        min_length=7,
        max_length=45,
        description="Originating IPv4 or IPv6 client network address.",
        examples=["192.168.1.100"],
    )
    entity_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Legal counterparty entity name to verify against watchlists.",
        examples=["Global Trading Ltd"],
    )
    velocity_5m_count: int = Field(
        default=1,
        ge=0,
        description="Number of transactions initiated in the trailing 5 minutes.",
        examples=[1],
    )

    @field_validator("currency")
    @classmethod
    def validate_currency_uppercase(cls, val: str) -> str:
        """Enforce standard uppercase formatting for ISO currency strings."""
        return val.upper()

    @property
    def amount_cents(self) -> int:
        """Convert Decimal major units to minor-unit integer cents."""
        return int((self.amount * 100).to_integral_value())


class ScreeningResponse(BaseModel):
    """Normalized response schema for in-flight and evaluated screening records."""

    id: UUID = Field(
        ...,
        description="Persistent UUID primary key in the screening ledger.",
        examples=["b8d1b111-2222-4a0e-a123-abcdef012345"],
    )
    transaction_id: str = Field(
        ...,
        description="Idempotency transaction identifier.",
        examples=["tx-88392-corp-99"],
    )
    account_id: str = Field(
        ...,
        description="Account identifier.",
        examples=["acct-us-99214"],
    )
    amount: Decimal = Field(
        ...,
        description="Monetary value in major units.",
        examples=[Decimal("4500.00")],
    )
    currency: str = Field(
        ...,
        description="ISO currency code.",
        examples=["USD"],
    )
    status: Literal["pending", "processing", "approved", "flagged_review", "blocked", "failed"] = (
        Field(
            ...,
            description="Current state machine status of the screening.",
            examples=["processing"],
        )
    )
    risk_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Heuristic composite fraud score [0, 100].",
        examples=[15],
    )
    decision_reason: str | None = Field(
        default=None,
        description="Diagnostic explanation of final screening determination.",
        examples=["Automated evaluation completed"],
    )
    created_at: datetime = Field(
        ...,
        description="UTC creation timestamp.",
        examples=[datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)],
    )

    model_config = ConfigDict(from_attributes=True)


class LivenessResponse(BaseModel):
    """Container liveness probe response schema."""

    status: str = Field(default="alive", examples=["alive"])


class ReadinessResponse(BaseModel):
    """Container readiness probe dependency check response schema."""

    status: str = Field(..., examples=["ready"])
    database: str = Field(..., examples=["connected"])
    redis: str = Field(..., examples=["connected"])
    rabbitmq: str = Field(..., examples=["connected"])
