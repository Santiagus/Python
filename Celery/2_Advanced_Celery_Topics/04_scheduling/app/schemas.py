"""Pydantic v2 schemas for API requests, responses, and Swagger documentation.

Enforces strict input validation, realistic specimen examples for zero-422 Swagger UI
execution, and Fowler's Money Pattern representation with minor-unit integer cents.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class HealthResponse(BaseModel):
    """Health check response schema reflecting infrastructure connectivity."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "status": "healthy",
                    "timestamp": "2026-09-23T17:00:00Z",
                    "components": {
                        "database": "connected",
                        "redis": "connected",
                    },
                }
            ]
        },
    )

    status: str = Field(
        ...,
        description="Overall service health status ('healthy' or 'degraded')",
        examples=["healthy"],
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of the health check in UTC",
        examples=["2026-09-23T17:00:00Z"],
    )
    components: dict[str, str] = Field(
        default_factory=dict,
        description="Health status of downstream dependencies (PostgreSQL, Redis)",
        examples=[{"database": "connected", "redis": "connected"}],
    )


class ReconciliationReportItem(BaseModel):
    """Individual financial cut-off reconciliation report summary."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "report_id": "a0000000-0000-0000-0000-000000000001",
                    "period_date": "2026-09-23",
                    "total_credits_cents": 1500000,
                    "total_debits_cents": 1500000,
                    "net_movement_cents": 0,
                    "discrepancy_cents": 0,
                    "status": "balanced",
                    "verification_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                    "reconciled_at": "2026-09-23T17:00:05Z",
                    "created_at": "2026-09-23T17:00:05Z",
                }
            ]
        },
    )

    report_id: UUID = Field(
        ...,
        description="Unique identifier of the reconciliation report",
        examples=["a0000000-0000-0000-0000-000000000001"],
    )
    period_date: date = Field(
        ...,
        description="Financial banking business period date ('YYYY-MM-DD')",
        examples=["2026-09-23"],
    )
    total_credits_cents: int = Field(
        ...,
        description="Total posted credit transactions in minor-unit integer cents",
        examples=[1500000],
    )
    total_debits_cents: int = Field(
        ...,
        description="Total posted debit transactions in minor-unit integer cents",
        examples=[1500000],
    )
    net_movement_cents: int = Field(
        ...,
        description="Net ledger movement in cents (Credits - Debits)",
        examples=[0],
    )
    discrepancy_cents: int = Field(
        ...,
        description="Identified discrepancy against clearinghouse records in cents",
        examples=[0],
    )
    status: str = Field(
        ...,
        description="Reconciliation status: balanced, discrepancy_detected, pending, failed",
        examples=["balanced"],
    )
    verification_hash: str = Field(
        ...,
        description="SHA-256 cryptographic verification checksum of ledger totals",
        examples=["e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"],
    )
    reconciled_at: datetime = Field(
        ...,
        description="UTC timestamp when reconciliation verification was executed",
        examples=["2026-09-23T17:00:05Z"],
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp when the report was first created",
        examples=["2026-09-23T17:00:05Z"],
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_credits(self) -> Decimal:
        """Formatted total credit amount in standard currency decimal units."""
        return Decimal(self.total_credits_cents) / Decimal(100)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_debits(self) -> Decimal:
        """Formatted total debit amount in standard currency decimal units."""
        return Decimal(self.total_debits_cents) / Decimal(100)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def discrepancy(self) -> Decimal:
        """Formatted discrepancy amount in standard currency decimal units."""
        return Decimal(self.discrepancy_cents) / Decimal(100)


class ReconciliationListResponse(BaseModel):
    """Paginated collection of reconciliation reports."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                    "items": [
                        {
                            "report_id": "a0000000-0000-0000-0000-000000000001",
                            "period_date": "2026-09-23",
                            "total_credits_cents": 1500000,
                            "total_debits_cents": 1500000,
                            "net_movement_cents": 0,
                            "discrepancy_cents": 0,
                            "status": "balanced",
                            "verification_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                            "reconciled_at": "2026-09-23T17:00:05Z",
                            "created_at": "2026-09-23T17:00:05Z",
                        }
                    ],
                }
            ]
        },
    )

    total: int = Field(
        ...,
        description="Total number of matching reports in storage",
        examples=[1],
    )
    limit: int = Field(
        ...,
        description="Maximum number of items returned per page",
        examples=[50],
    )
    offset: int = Field(
        ...,
        description="Pagination offset index",
        examples=[0],
    )
    items: list[ReconciliationReportItem] = Field(
        default_factory=list,
        description="List of reconciliation report summaries",
    )


class TriggerReconciliationRequest(BaseModel):
    """Request payload to manually trigger or re-run an EOD reconciliation."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "period_date": "2026-09-23",
                    "clearing_variance_cents": 0,
                    "force": False,
                }
            ]
        }
    )

    period_date: date = Field(
        ...,
        description="Financial business period date to reconcile ('YYYY-MM-DD')",
        examples=["2026-09-23"],
    )
    clearing_variance_cents: int = Field(
        default=0,
        ge=0,
        description="Simulated clearinghouse variance in minor-unit cents (for testing discrepancy alerts)",
        examples=[0],
    )
    force: bool = Field(
        default=False,
        description="Force re-execution even if previously marked balanced",
        examples=[False],
    )


class TriggerReconciliationResponse(BaseModel):
    """Asynchronous acknowledgment confirming reconciliation job dispatch."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "task_id": "c1f72b84-482a-4df6-83cb-6a0dc11ea3d8",
                    "period_date": "2026-09-23",
                    "status": "queued",
                    "message": "Reconciliation task dispatched to queue 'reconciliation'",
                }
            ]
        }
    )

    task_id: str = Field(
        ...,
        description="Celery task UUID tracking asynchronous worker execution",
        examples=["c1f72b84-482a-4df6-83cb-6a0dc11ea3d8"],
    )
    period_date: str = Field(
        ...,
        description="Financial cut-off period date queued for processing",
        examples=["2026-09-23"],
    )
    status: str = Field(
        default="queued",
        description="Current dispatch status",
        examples=["queued"],
    )
    message: str = Field(
        ...,
        description="Human-readable status confirmation",
        examples=["Reconciliation task dispatched to queue 'reconciliation'"],
    )


class TriggerBackfillRequest(BaseModel):
    """Request payload to manually trigger historical gap detection and backfill."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-22",
                }
            ]
        }
    )

    start_date: date | None = Field(
        default=None,
        description="Optional beginning of the gap scan range (defaults to earliest ledger activity or 30 days ago)",
        examples=["2026-09-01"],
    )
    end_date: date | None = Field(
        default=None,
        description="Optional end of the gap scan range (defaults to yesterday)",
        examples=["2026-09-22"],
    )


class TriggerBackfillResponse(BaseModel):
    """Response payload confirming dispatch of the gap backfill task."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "task_id": "c0000000-0000-0000-0000-000000000001",
                    "status": "queued",
                    "message": "Historical gap backfill task dispatched to queue 'reconciliation'",
                    "scan_range_start": "2026-09-01",
                    "scan_range_end": "2026-09-22",
                }
            ]
        }
    )

    task_id: str = Field(
        ...,
        description="Celery task identifier assigned to the backfill execution",
        examples=["c0000000-0000-0000-0000-000000000001"],
    )
    status: str = Field(
        default="queued",
        description="Current dispatch status",
        examples=["queued"],
    )
    message: str = Field(
        ...,
        description="Human-readable status confirmation",
        examples=["Historical gap backfill task dispatched to queue 'reconciliation'"],
    )
    scan_range_start: str | None = Field(
        default=None,
        description="Audited scan range start date ('YYYY-MM-DD')",
        examples=["2026-09-01"],
    )
    scan_range_end: str | None = Field(
        default=None,
        description="Audited scan range end date ('YYYY-MM-DD')",
        examples=["2026-09-22"],
    )


class GapAuditResponse(BaseModel):
    """Audit response identifying unclosed historical business-day gaps."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "gaps": ["2026-09-21", "2026-09-22"],
                    "total_gaps": 2,
                    "scan_range_start": "2026-09-01",
                    "scan_range_end": "2026-09-22",
                }
            ]
        }
    )

    gaps: list[str] = Field(
        default_factory=list,
        description="List of unclosed Monday-Friday business dates ('YYYY-MM-DD')",
        examples=[["2026-09-21", "2026-09-22"]],
    )
    total_gaps: int = Field(
        ...,
        description="Total count of missing reconciliation periods",
        examples=[2],
    )
    scan_range_start: str = Field(
        ...,
        description="Beginning of the audited date range",
        examples=["2026-09-01"],
    )
    scan_range_end: str = Field(
        ...,
        description="End of the audited date range (yesterday or today)",
        examples=["2026-09-22"],
    )


class SeedLedgerRequest(BaseModel):
    """Request payload to seed synthetic ledger entries for testing workflows."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "period_date": "2026-09-23",
                    "scenario": "balanced",
                    "amount_cents": 1500000,
                }
            ]
        }
    )

    period_date: date = Field(
        ...,
        description="Financial business period date to populate with ledger entries",
        examples=["2026-09-23"],
    )
    scenario: str = Field(
        default="balanced",
        pattern="^(balanced|discrepancy|empty)$",
        description="Seed scenario: 'balanced' (equal debits/credits), 'discrepancy' (unbalanced), or 'empty'",
        examples=["balanced"],
    )
    amount_cents: int = Field(
        default=1500000,
        gt=0,
        description="Amount in minor-unit cents for transactions",
        examples=[1500000],
    )


class SeedLedgerResponse(BaseModel):
    """Response payload detailing seeded test entities."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "account_id": "b0000000-0000-0000-0000-000000000001",
                    "period_date": "2026-09-23",
                    "scenario": "balanced",
                    "entries_created": 2,
                    "total_credits_cents": 1500000,
                    "total_debits_cents": 1500000,
                }
            ]
        }
    )

    account_id: UUID = Field(
        ...,
        description="Primary account identifier associated with seeded entries",
        examples=["b0000000-0000-0000-0000-000000000001"],
    )
    period_date: str = Field(
        ...,
        description="Financial business period date seeded",
        examples=["2026-09-23"],
    )
    scenario: str = Field(
        ...,
        description="Seeded scenario pattern",
        examples=["balanced"],
    )
    entries_created: int = Field(
        ...,
        description="Total number of ledger entry rows created",
        examples=[2],
    )
    total_credits_cents: int = Field(
        ...,
        description="Sum of credit transactions seeded in cents",
        examples=[1500000],
    )
    total_debits_cents: int = Field(
        ...,
        description="Sum of debit transactions seeded in cents",
        examples=[1500000],
    )
