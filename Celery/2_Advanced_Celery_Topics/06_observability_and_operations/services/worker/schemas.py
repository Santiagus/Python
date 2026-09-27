"""Domain schemas and result envelopes for Celery worker tasks.

Enforces strict minor-unit monetary integer precision, Pydantic v2 validation,
and normalized result envelopes across distributed task boundaries.
"""

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScreeningPayload(BaseModel):
    """Normalized payload representing a financial transaction screening request."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "screening_id": "99887766-5544-3322-1100-aabbccddeeff",
                    "transaction_id": "tx_20260927_001",
                    "account_id": "acc_corporate_99",
                    "entity_name": "Acme Commercial Corp",
                    "amount": "12500.50",
                    "currency": "USD",
                    "client_ip": "198.51.100.42",
                    "velocity_5m_count": 2,
                }
            ]
        },
    )

    screening_id: str = Field(
        ...,
        description="Unique UUID string identifying this screening ledger entry.",
        examples=["99887766-5544-3322-1100-aabbccddeeff"],
    )
    transaction_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="External transaction identifier for idempotency enforcement.",
        examples=["tx_20260927_001"],
    )
    account_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Originating customer or corporate treasury account ID.",
        examples=["acc_corporate_99"],
    )
    entity_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Name of recipient or counterparty entity to screen against watchlists.",
        examples=["Acme Commercial Corp"],
    )
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Monetary amount in standard major units (converted to minor cents).",
        examples=[Decimal("12500.50")],
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
        description="Originating IPv4 or IPv6 network address.",
        examples=["198.51.100.42"],
    )
    velocity_5m_count: int = Field(
        default=0,
        ge=0,
        description="Transactions initiated by account in rolling 5-minute window.",
        examples=[2],
    )

    @field_validator("screening_id")
    @classmethod
    def validate_uuid_format(cls, v: str) -> str:
        """Validate that screening_id is a valid UUID string.

        Args:
            v: Input string to validate.

        Returns:
            str: Validated UUID string.

        Raises:
            ValueError: If string is not a parseable UUID.
        """
        try:
            UUID(v)
            return v
        except ValueError as err:
            raise ValueError(f"screening_id '{v}' is not a valid UUID format") from err

    @property
    def amount_cents(self) -> int:
        """Convert standard decimal amount to minor units (integer cents).

        Returns:
            int: Amount in integer cents without floating point drift.
        """
        return int((self.amount * 100).to_integral_value())


class ScoringResult(BaseModel):
    """Result of real-time velocity and heuristic fraud scoring."""

    model_config = ConfigDict(from_attributes=True)

    risk_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Calculated composite risk score bounded between 0 (safe) and 100 (critical).",
    )
    decision: Literal["approved", "flagged_review", "blocked"] = Field(
        ...,
        description="Triage decision derived from risk thresholds.",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Diagnostic explanation for points added during heuristic evaluation.",
    )


class WatchlistResult(BaseModel):
    """Result of sanctions and PEP watchlist screening."""

    model_config = ConfigDict(from_attributes=True)

    is_sanctioned: bool = Field(..., description="Whether positive matches were found.")
    matches: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Detailed list of matched entity names and confidence ratings.",
    )
    decision: Literal["approved", "flagged_review", "blocked"] = Field(
        ...,
        description="Compliance screening outcome.",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Explanations for sanctions decision.",
    )


class ResultEnvelope(BaseModel):
    """Resilient task execution result envelope.

    Prevents Celery chords and canvases from crashing on non-fatal external failures
    by capturing partial degradation and diagnostic error payloads.
    """

    model_config = ConfigDict(from_attributes=True)

    status: Literal["ok", "degraded", "failed"] = Field(
        ...,
        description="Execution status of the task.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Primary task output payload.",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Captured warnings, timeouts, or non-fatal exception details.",
    )
