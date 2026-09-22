"""Pydantic v2 schemas and minor-unit financial validation models.

Enforces Decimal financial calculations, minor-unit conversions (cents),
defensive field validations, and realistic specimen defaults for Swagger UI.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Monetary Precision Helpers
# =============================================================================

def to_cents(amount: Decimal) -> int:
    """Convert a Decimal monetary amount in dollars to minor-unit integer cents.

    Uses ROUND_HALF_UP to ensure standard banking rounding behavior.

    Args:
        amount: Monetary amount in major units (e.g. Decimal("12.34")).

    Returns:
        int: Amount in integer cents (e.g. 1234).
    """
    cents = (amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def from_cents(cents: int) -> Decimal:
    """Convert minor-unit integer cents back to major-unit Decimal dollars.

    Args:
        cents: Amount in integer cents (e.g. 1234).

    Returns:
        Decimal: Amount in dollars (e.g. Decimal("12.34")).
    """
    return (Decimal(cents) / Decimal("100")).quantize(Decimal("0.01"))


# =============================================================================
# Domain Enums
# =============================================================================

class PaymentRail(str, Enum):
    """Supported clearing and settlement payment rails."""
    fednow = "fednow"
    rtp = "rtp"
    ach = "ach"


class PaymentPriority(str, Enum):
    """Priority tiers mapped directly to isolated broker queues."""
    critical = "critical"
    default = "default"
    bulk = "bulk"


class PaymentStatus(str, Enum):
    """Lifecycle statuses for individual payments."""
    pending = "pending"
    processing = "processing"
    settled = "settled"
    failed = "failed"
    rejected = "rejected"


class BatchStatus(str, Enum):
    """Lifecycle statuses for high-volume batch disbursements."""
    pending = "pending"
    processing = "processing"
    completed = "completed"
    partially_failed = "partially_failed"
    failed = "failed"


# =============================================================================
# Payment Schemas
# =============================================================================

class InstantPaymentRequest(BaseModel):
    """Inbound request payload for real-time instant payouts (FedNow/RTP)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "idempotency_key": "idemp_instant_fednow_2026_001",
                    "source_account_id": "a0000000-0000-0000-0000-000000000001",
                    "destination_account_number": "987654321098",
                    "destination_routing_number": "021000021",
                    "amount": "2500.00",
                    "rail": "rtp",
                    "description": "Executive compensation instant payout",
                }
            ]
        }
    )

    idempotency_key: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Unique client-generated idempotency key to prevent duplicate dispatch",
        examples=["idemp_instant_fednow_2026_001"],
    )
    source_account_id: UUID = Field(
        ...,
        description="UUID of the funding source account in PostgreSQL",
        examples=["a0000000-0000-0000-0000-000000000001"],
    )
    destination_account_number: str = Field(
        ...,
        min_length=4,
        max_length=32,
        description="Target counterparty bank account number",
        examples=["987654321098"],
    )
    destination_routing_number: str = Field(
        ...,
        pattern=r"^\d{9}$",
        description="9-digit Fed/ABA routing transit number",
        examples=["021000021"],
    )
    amount: Decimal = Field(
        ...,
        gt=Decimal("0.00"),
        decimal_places=2,
        description="Monetary transfer amount in USD (major units)",
        examples=[Decimal("2500.00")],
    )
    rail: PaymentRail = Field(
        default=PaymentRail.rtp,
        description="Real-time clearing rail: 'rtp' or 'fednow'",
        examples=["rtp"],
    )
    description: str = Field(
        default="Instant payout transfer",
        max_length=255,
        description="Human-readable memo or description",
        examples=["Executive compensation instant payout"],
    )

    @field_validator("rail")
    @classmethod
    def validate_realtime_rail(cls, v: PaymentRail) -> PaymentRail:
        """Ensure instant payment uses FedNow or RTP."""
        if v not in (PaymentRail.fednow, PaymentRail.rtp):
            raise ValueError("Instant payments must use 'fednow' or 'rtp' rails")
        return v


class InstantPaymentResponse(BaseModel):
    """Response returned upon accepting an instant payout request."""

    model_config = ConfigDict(from_attributes=True)

    payment_id: UUID = Field(..., description="Unique payment transaction UUID")
    idempotency_key: str = Field(..., description="Echoed client idempotency key")
    source_account_id: UUID = Field(..., description="Funding source account UUID")
    destination_account_mask: str = Field(..., description="Masked destination account (e.g. ******1098)")
    destination_routing_number: str = Field(..., description="9-digit routing number")
    amount: Decimal = Field(..., description="Monetary transfer amount in USD")
    amount_cents: int = Field(..., description="Amount in minor-unit integer cents")
    rail: PaymentRail = Field(..., description="Clearing rail utilized")
    priority: PaymentPriority = Field(..., description="Worker queue priority assigned")
    status: PaymentStatus = Field(..., description="Current payment lifecycle status")
    created_at: datetime = Field(..., description="Submission timestamp")
    cleared_at: datetime | None = Field(default=None, description="Clearing confirmation timestamp")
    external_reference: str | None = Field(default=None, description="Clearing network transaction ID")
    error_detail: str | None = Field(default=None, description="Error reason if failed or rejected")


# =============================================================================
# Batch Disbursement Schemas
# =============================================================================

class DisbursementItem(BaseModel):
    """Individual disbursement item within a high-volume batch."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "recipient_name": "Jane Doe",
                    "account_number": "112233445566",
                    "routing_number": "021000021",
                    "amount": "1250.50",
                }
            ]
        }
    )

    recipient_name: str = Field(..., min_length=2, max_length=128, examples=["Jane Doe"])
    account_number: str = Field(..., min_length=4, max_length=32, examples=["112233445566"])
    routing_number: str = Field(..., pattern=r"^\d{9}$", examples=["021000021"])
    amount: Decimal = Field(..., gt=Decimal("0.00"), decimal_places=2, examples=[Decimal("1250.50")])


class BatchDisbursementRequest(BaseModel):
    """Inbound request payload for batch disbursement (e.g. payroll, supplier sweep)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "file_reference": "batch_payroll_2026_sep_q3_01",
                    "source_account_id": "a0000000-0000-0000-0000-000000000002",
                    "disbursements": [
                        {
                            "recipient_name": "Alice Smith",
                            "account_number": "111122223333",
                            "routing_number": "021000021",
                            "amount": "3500.00",
                        },
                        {
                            "recipient_name": "Bob Johnson",
                            "account_number": "444455556666",
                            "routing_number": "021000021",
                            "amount": "2800.00",
                        },
                    ],
                }
            ]
        }
    )

    file_reference: str = Field(
        ...,
        min_length=4,
        max_length=128,
        description="Unique batch file reference or identifier",
        examples=["batch_payroll_2026_sep_q3_01"],
    )
    source_account_id: UUID = Field(
        ...,
        description="UUID of the funding payroll account in PostgreSQL",
        examples=["a0000000-0000-0000-0000-000000000002"],
    )
    disbursements: list[DisbursementItem] = Field(
        ...,
        min_length=1,
        description="List of disbursement line items to process in batch",
    )


class BatchDisbursementResponse(BaseModel):
    """Response returned upon ingesting and scheduling a batch settlement."""

    model_config = ConfigDict(from_attributes=True)

    batch_id: UUID = Field(..., description="Unique batch settlement UUID")
    file_reference: str = Field(..., description="External batch file reference")
    source_account_id: UUID = Field(..., description="Funding payroll account UUID")
    total_items: int = Field(..., description="Total line items in batch")
    total_amount: Decimal = Field(..., description="Total gross disbursement in USD")
    total_amount_cents: int = Field(..., description="Total gross disbursement in minor cents")
    processed_items: int = Field(..., description="Number of items successfully processed")
    status: BatchStatus = Field(..., description="Batch lifecycle status")
    created_at: datetime = Field(..., description="Ingestion timestamp")


# =============================================================================
# Account & Operational Schemas
# =============================================================================

class AccountResponse(BaseModel):
    """Account balance and details representation."""

    model_config = ConfigDict(from_attributes=True)

    account_id: UUID = Field(..., description="Unique account UUID")
    account_number_mask: str = Field(..., description="Masked account number (e.g. ******5501)")
    balance: Decimal = Field(..., description="Current available balance in USD")
    balance_cents: int = Field(..., description="Current balance in minor-unit integer cents")
    currency: str = Field(..., description="ISO currency code (e.g. USD)")


class QueueMetric(BaseModel):
    """Real-time metric for an isolated Celery broker queue."""

    name: str = Field(..., description="Queue name (e.g. critical, default, bulk)")
    messages_ready: int = Field(..., description="Messages pending consumption in queue")
    messages_unacknowledged: int = Field(..., description="Messages currently held by workers")
    consumers: int = Field(..., description="Active consumer worker channels attached")


class QueueMetricsResponse(BaseModel):
    """Aggregate broker queue status report."""

    queues: list[QueueMetric] = Field(..., description="Per-queue depth telemetry")
    total_ready: int = Field(..., description="Sum total of ready messages across all queues")


class DLQRedriveRequest(BaseModel):
    """Request payload to redrive dead-lettered messages back into production queues."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "source_queue": "rejected_payments",
                    "destination_queue": "critical",
                    "max_messages": 100,
                }
            ]
        }
    )

    source_queue: str = Field(default="rejected_payments", description="DLQ source queue name")
    destination_queue: str = Field(default="critical", description="Target destination queue")
    max_messages: int = Field(default=100, ge=1, le=1000, description="Max messages to redrive")


class DLQRedriveResponse(BaseModel):
    """Result of DLQ message redrive operation."""

    messages_redriven: int = Field(..., description="Number of messages re-queued")
    source_queue: str = Field(..., description="Source DLQ name")
    destination_queue: str = Field(..., description="Destination queue name")


class HealthResponse(BaseModel):
    """Comprehensive system health and service connectivity status."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "healthy",
                    "service": "api_instant",
                    "environment": "development",
                    "database": "connected",
                    "rabbitmq": "connected",
                    "redis": "connected",
                }
            ]
        }
    )

    status: str = Field(..., examples=["healthy"])
    service: str = Field(default="api", examples=["api_instant"], description="Service instance or SLA pool identifier")
    environment: str = Field(..., examples=["development"])
    database: str = Field(..., examples=["connected"])
    rabbitmq: str = Field(..., examples=["connected"])
    redis: str = Field(..., examples=["connected"])


class ServiceMetricsResponse(BaseModel):
    """Service-level runtime, database pool, and operational metrics."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "service": "api_instant",
                    "environment": "development",
                    "status": "healthy",
                    "db_pool": {
                        "pool_size": 10,
                        "checked_in": 10,
                        "checked_out": 0,
                        "overflow": 0,
                    },
                    "queues": [
                        {
                            "name": "critical",
                            "messages_ready": 0,
                            "messages_unacknowledged": 0,
                            "consumers": 1,
                        }
                    ],
                }
            ]
        }
    )

    service: str = Field(..., examples=["api_instant"], description="Service instance or SLA pool identifier")
    environment: str = Field(..., examples=["development"], description="Application environment")
    status: str = Field(..., examples=["healthy"], description="Current service operational status")
    db_pool: dict[str, int] = Field(..., description="Database connection pool metrics")
    queues: list[QueueMetric] = Field(default_factory=list, description="Broker queue depths")


