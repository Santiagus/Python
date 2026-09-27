"""Pydantic v2 schemas and minor-unit financial validation models for Card Disputes.

Enforces Decimal financial constraints, minor-unit conversions (cents),
defensive field validations, and realistic specimen defaults for Swagger UI.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Monetary Precision Helpers
# =============================================================================


def to_cents(amount: Decimal) -> int:
    """Convert a Decimal monetary amount in dollars to minor-unit integer cents.

    Uses ROUND_HALF_UP to ensure standard banking rounding behavior.

    Args:
        amount: Monetary amount in major units (e.g. Decimal("149.99")).

    Returns:
        int: Amount in integer cents (e.g. 14999).
    """
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def from_cents(cents: int) -> Decimal:
    """Convert minor-unit integer cents back to major-unit Decimal dollars.

    Args:
        cents: Amount in integer cents (e.g. 14999).

    Returns:
        Decimal: Amount in dollars (e.g. Decimal("149.99")).
    """
    return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))


# =============================================================================
# Domain Enums
# =============================================================================


class DisputeStatus(str, Enum):
    """Lifecycle statuses for a card dispute transaction."""

    pending = "pending"
    processing = "processing"
    submitted_to_network = "submitted_to_network"
    failed = "failed"
    cancelled = "cancelled"


class DisputeReason(str, Enum):
    """Cardholder dispute reason codes conforming to clearinghouse standards."""

    fraudulent = "fraudulent"
    unrecognized = "unrecognized"
    duplicate = "duplicate"
    subscription_cancelled = "subscription_cancelled"
    goods_not_received = "goods_not_received"


# =============================================================================
# Request & Response Schemas
# =============================================================================


class DisputeCreateRequest(BaseModel):
    """Payload for submitting a new card dispute."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "transaction_id": "tx_88a91c2f",
                    "card_token": "tok_card_9921_sec",
                    "card_last_four": "4242",
                    "amount": "149.99",
                    "currency": "USD",
                    "reason": "fraudulent",
                    "evidence_notes": "Cardholder confirmed card was in possession; merchant unrecognized.",
                }
            ]
        }
    )

    transaction_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description="Unique transaction reference identifier being disputed",
        examples=["tx_88a91c2f"],
    )
    card_token: str = Field(
        ...,
        min_length=8,
        max_length=64,
        description="Edge tokenized card identifier",
        examples=["tok_card_9921_sec"],
    )
    card_last_four: str = Field(
        ...,
        pattern=r"^[0-9]{4}$",
        description="Card last 4 digits for receipt display",
        examples=["4242"],
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        description="Dispute amount in major currency units",
        examples=[Decimal("149.99")],
    )
    currency: str = Field(
        default="USD",
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 3-letter currency code",
        examples=["USD"],
    )
    reason: DisputeReason = Field(
        ...,
        description="Cardholder dispute reason code",
        examples=[DisputeReason.fraudulent],
    )
    evidence_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Cardholder written evidence notes",
        examples=["Cardholder confirmed card was in possession; merchant unrecognized."],
    )

    @property
    def amount_cents(self) -> int:
        """Convert the decimal amount to minor-unit integer cents."""
        return to_cents(self.amount)


class DisputeResponse(BaseModel):
    """Full detail response model for a card dispute."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                    "transaction_id": "tx_88a91c2f",
                    "card_token": "tok_card_9921_sec",
                    "card_last_four": "4242",
                    "amount_cents": 14999,
                    "amount": "149.99",
                    "currency": "USD",
                    "reason": "fraudulent",
                    "status": "processing",
                    "celery_task_id": "task-88a91c2f",
                    "network_reference_id": None,
                    "attempt_count": 1,
                    "error_message": None,
                    "created_at": "2026-09-26T18:00:00Z",
                    "updated_at": "2026-09-26T18:00:00Z",
                }
            ]
        },
    )

    id: UUID = Field(
        ...,
        description="Internal dispute UUID primary key",
        examples=[UUID("9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d")],
    )
    transaction_id: str = Field(
        ...,
        description="Unique transaction reference identifier",
        examples=["tx_88a91c2f"],
    )
    card_token: str = Field(
        ...,
        description="Masked/tokenized card identifier",
        examples=["tok_card_9921_sec"],
    )
    card_last_four: str = Field(
        ...,
        description="Card last 4 digits",
        examples=["4242"],
    )
    amount_cents: int = Field(
        ...,
        gt=0,
        description="Dispute amount in minor-unit integer cents",
        examples=[14999],
    )
    amount: Decimal = Field(
        ...,
        description="Dispute amount in major currency units",
        examples=[Decimal("149.99")],
    )
    currency: str = Field(
        default="USD",
        description="ISO 4217 3-letter currency code",
        examples=["USD"],
    )
    reason: str = Field(
        ...,
        description="Cardholder dispute reason code",
        examples=["fraudulent"],
    )
    status: DisputeStatus = Field(
        ...,
        description="Active state machine status",
        examples=[DisputeStatus.processing],
    )
    celery_task_id: str | None = Field(
        default=None,
        description="Celery background task ID for worker tracking and revocation",
        examples=["task-88a91c2f"],
    )
    network_reference_id: str | None = Field(
        default=None,
        description="Card network clearinghouse submission reference identifier",
        examples=["VROL-7A9B1C"],
    )
    attempt_count: int = Field(
        default=1,
        description="Submission attempt count",
        examples=[1],
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if the submission failed",
        examples=[None],
    )
    created_at: datetime = Field(
        ...,
        description="Timestamp when the dispute was registered in UTC",
    )
    updated_at: datetime = Field(
        ...,
        description="Timestamp when the dispute was last updated in UTC",
    )


class DisputeCancelResponse(BaseModel):
    """Response returned upon cancelling an in-flight dispute."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                    "status": "cancelled",
                    "revoked_task_id": "task-88a91c2f",
                    "message": "Card dispute successfully revoked in-flight",
                }
            ]
        }
    )

    id: UUID = Field(
        ...,
        description="Internal dispute UUID",
        examples=[UUID("9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d")],
    )
    status: DisputeStatus = Field(
        default=DisputeStatus.cancelled,
        description="Updated status reflecting cancellation",
        examples=[DisputeStatus.cancelled],
    )
    revoked_task_id: str | None = Field(
        default=None,
        description="Revoked Celery task ID if one was active",
        examples=["task-88a91c2f"],
    )
    message: str = Field(
        default="Card dispute successfully revoked in-flight",
        description="Human-readable outcome description",
        examples=["Card dispute successfully revoked in-flight"],
    )


class DisputeRetryResponse(BaseModel):
    """Response returned upon retrying a failed or cancelled dispute."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
                    "status": "processing",
                    "attempt_count": 2,
                    "celery_task_id": "task-new-retry-uuid",
                    "message": "Dispute re-queued for network submission",
                }
            ]
        }
    )

    id: UUID = Field(
        ...,
        description="Internal dispute UUID",
        examples=[UUID("9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d")],
    )
    status: DisputeStatus = Field(
        default=DisputeStatus.processing,
        description="Updated status transitioning back to processing",
        examples=[DisputeStatus.processing],
    )
    attempt_count: int = Field(
        ...,
        description="Updated submission attempt count",
        examples=[2],
    )
    celery_task_id: str = Field(
        ...,
        description="New Celery task ID dispatched to RabbitMQ",
        examples=["task-new-retry-uuid"],
    )
    message: str = Field(
        default="Dispute re-queued for network submission",
        description="Human-readable outcome description",
        examples=["Dispute re-queued for network submission"],
    )
