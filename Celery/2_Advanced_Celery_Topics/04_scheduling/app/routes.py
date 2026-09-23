"""FastAPI REST routes for EOD banking cut-off and reconciliation control plane.

Exposes endpoints to query financial reconciliation reports, audit missing business-day gaps,
manually trigger reconciliation runs, seed test transactions, and monitor infrastructure health.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.dispatcher import dispatch_reconciliation_cutoff
from app.models import Account, LedgerEntry, ReconciliationReport
from app.schemas import (
    GapAuditResponse,
    HealthResponse,
    ReconciliationListResponse,
    ReconciliationReportItem,
    SeedLedgerRequest,
    SeedLedgerResponse,
    TriggerReconciliationRequest,
    TriggerReconciliationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Reconciliations"])


# =============================================================================
# 1. Health & Readiness Probe
# =============================================================================
@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Infrastructure Health & Readiness Check",
    description="Validates active connectivity to PostgreSQL and Redis backing services.",
)
async def check_health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> HealthResponse:
    """Validate system health and dependency readiness.

    Args:
        response: FastAPI response object to alter HTTP status code if degraded.
        session: Active async SQLAlchemy database session.

    Returns:
        HealthResponse: Health status object detailing downstream components.
    """
    settings = get_settings()
    components: dict[str, str] = {}
    is_healthy = True

    # 1. Ping PostgreSQL
    try:
        await session.execute(select(func.now()))
        components["database"] = "connected"
    except Exception as exc:
        logger.error("Health check failed on database ping: %s", exc)
        components["database"] = f"unhealthy: {exc}"
        is_healthy = False

    # 2. Ping Redis
    try:
        client = aioredis.from_url(settings.redis_url, socket_timeout=2.0)
        await client.ping()
        await client.aclose()
        components["redis"] = "connected"
    except Exception as exc:
        logger.error("Health check failed on redis ping: %s", exc)
        components["redis"] = f"unhealthy: {exc}"
        is_healthy = False

    # 3. Determine overall status code
    overall_status = "healthy" if is_healthy else "degraded"
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(timezone.utc),
        components=components,
    )


# =============================================================================
# 2. Reconciliation Reports Query Endpoints
# =============================================================================
@router.get(
    "/reconciliations",
    response_model=ReconciliationListResponse,
    summary="List Reconciliation Reports",
    description="Retrieve a paginated list of daily EOD financial reconciliation reports.",
)
async def list_reconciliations(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset pagination index")] = 0,
    status_filter: Annotated[str | None, Query(alias="status", description="Filter by status")] = None,
) -> ReconciliationListResponse:
    """Fetch paginated reconciliation report records with optional status filtering.

    Args:
        session: Active async database session.
        limit: Maximum number of rows to retrieve.
        offset: Number of rows to skip.
        status_filter: Optional reconciliation status filter.

    Returns:
        ReconciliationListResponse: Paginated report summaries and total match count.
    """
    # 1. Build base query with optional status filtering
    query = select(ReconciliationReport)
    count_query = select(func.count(ReconciliationReport.report_id))

    if status_filter:
        query = query.where(ReconciliationReport.status == status_filter)
        count_query = count_query.where(ReconciliationReport.status == status_filter)

    # 2. Query total match count
    total_res = await session.execute(count_query)
    total = total_res.scalar_one()

    # 3. Query paginated results ordered by period_date descending
    query = query.order_by(desc(ReconciliationReport.period_date)).limit(limit).offset(offset)
    result = await session.execute(query)
    reports = result.scalars().all()

    # 4. Convert ORM records into Pydantic models
    items = [ReconciliationReportItem.model_validate(r) for r in reports]

    return ReconciliationListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


@router.get(
    "/reconciliations/gaps",
    response_model=GapAuditResponse,
    summary="Audit Missing Business-Day Gaps",
    description="Identifies unclosed Monday-Friday banking business dates requiring backfill.",
)
async def audit_unclosed_gaps(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GapAuditResponse:
    """Calculate missing Monday through Friday business days without a reconciliation report.

    Args:
        session: Active async database session.

    Returns:
        GapAuditResponse: Chronological list of missing unclosed business dates.
    """
    today = datetime.now(timezone.utc).date()

    # 1. Query earliest transaction or report date to establish scan baseline
    earliest_entry_stmt = select(func.min(LedgerEntry.period_date))
    earliest_entry_res = await session.execute(earliest_entry_stmt)
    earliest_entry_date = earliest_entry_res.scalar_one_or_none()

    earliest_report_stmt = select(func.min(ReconciliationReport.period_date))
    earliest_report_res = await session.execute(earliest_report_stmt)
    earliest_report_date = earliest_report_res.scalar_one_or_none()

    # Determine baseline start date (earliest recorded activity or start of current month)
    candidates = [d for d in [earliest_entry_date, earliest_report_date] if d is not None]
    if candidates:
        start_date = min(candidates)
    else:
        start_date = date(today.year, today.month, 1)

    # 2. Query all existing reconciliation report dates within the window
    existing_reports_stmt = select(ReconciliationReport.period_date).where(
        ReconciliationReport.period_date >= start_date,
        ReconciliationReport.period_date <= today,
    )
    existing_reports_res = await session.execute(existing_reports_stmt)
    existing_dates = set(existing_reports_res.scalars().all())

    # 3. Identify Monday-Friday business days missing from existing reports
    missing_gaps: list[str] = []
    curr = start_date
    while curr <= today:
        if curr.weekday() < 5 and curr not in existing_dates:  # 0=Monday .. 4=Friday
            missing_gaps.append(curr.isoformat())
        curr += timedelta(days=1)

    return GapAuditResponse(
        gaps=missing_gaps,
        total_gaps=len(missing_gaps),
        scan_range_start=start_date.isoformat(),
        scan_range_end=today.isoformat(),
    )


@router.get(
    "/reconciliations/{period_date}",
    response_model=ReconciliationReportItem,
    summary="Get Single Reconciliation Report",
    description="Retrieve the exact verification report for a specific banking business date.",
)
async def get_reconciliation_by_date(
    period_date: date,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReconciliationReportItem:
    """Retrieve an existing reconciliation report by business date.

    Args:
        period_date: Business date to look up ('YYYY-MM-DD').
        session: Active async database session.

    Returns:
        ReconciliationReportItem: Report details and verification checksum.

    Raises:
        HTTPException: 404 NOT FOUND if no report exists for the given date.
    """
    stmt = select(ReconciliationReport).where(ReconciliationReport.period_date == period_date)
    res = await session.execute(stmt)
    report = res.scalar_one_or_none()

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No reconciliation report found for period {period_date}",
        )

    return ReconciliationReportItem.model_validate(report)


# =============================================================================
# 3. Reconciliation Task Trigger Endpoint
# =============================================================================
@router.post(
    "/reconciliations/trigger",
    response_model=TriggerReconciliationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger EOD Reconciliation Job",
    description="Dispatches an asynchronous Celery task to seal and reconcile a business period.",
)
async def trigger_reconciliation(
    payload: TriggerReconciliationRequest,
) -> TriggerReconciliationResponse:
    """Enqueue an asynchronous ledger reconciliation cut-off job.

    Args:
        payload: Parameters specifying period date and simulated clearing variance.

    Returns:
        TriggerReconciliationResponse: 202 Accepted status with Celery task ID.
    """
    date_str = payload.period_date.isoformat()

    # 1. Dispatch task to RabbitMQ broker via producer dispatcher
    task_id = dispatch_reconciliation_cutoff(
        period_date_str=date_str,
        clearing_variance_cents=payload.clearing_variance_cents,
    )

    return TriggerReconciliationResponse(
        task_id=task_id,
        period_date=date_str,
        status="queued",
        message=f"Reconciliation job queued for period {date_str}",
    )


# =============================================================================
# 4. Test Seeding Endpoint
# =============================================================================
@router.post(
    "/seed",
    response_model=SeedLedgerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Seed Synthetic Ledger Data",
    description="Helper endpoint to generate realistic accounts and balanced or discrepancy ledger transactions.",
)
async def seed_ledger_data(
    payload: SeedLedgerRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SeedLedgerResponse:
    """Seed synthetic accounts and double-entry ledger transactions for end-to-end testing.

    Args:
        payload: Seeding specifications (date, scenario, amount).
        session: Active async database session.

    Returns:
        SeedLedgerResponse: Confirmation of seeded account and entry totals.
    """
    now = datetime.now(timezone.utc)
    acc_id = uuid.uuid4()
    acc_num = f"ACC-{str(acc_id)[:8].upper()}"

    # 1. Create or ensure an operating account exists
    account = Account(
        account_id=acc_id,
        account_number=acc_num,
        account_mask=f"******{acc_num[-4:]}",
        account_type="operating",
        balance_cents=payload.amount_cents * 2,
        currency="USD",
        created_at=now,
    )
    session.add(account)

    entries_created = 0
    total_credits = 0
    total_debits = 0

    # 2. Generate ledger entries based on scenario
    if payload.scenario != "empty":
        # Credit entry
        credit_entry = LedgerEntry(
            entry_id=uuid.uuid4(),
            account_id=acc_id,
            amount_cents=payload.amount_cents,
            direction="credit",
            status="posted",
            period_date=payload.period_date,
            description="Synthetic customer deposit",
            created_at=now,
        )
        session.add(credit_entry)
        total_credits += payload.amount_cents
        entries_created += 1

        # Debit entry (balanced or discrepancy)
        debit_amount = (
            payload.amount_cents
            if payload.scenario == "balanced"
            else max(1, payload.amount_cents - 20000)  # $200 discrepancy
        )
        debit_entry = LedgerEntry(
            entry_id=uuid.uuid4(),
            account_id=acc_id,
            amount_cents=debit_amount,
            direction="debit",
            status="posted",
            period_date=payload.period_date,
            description="Synthetic vendor payout",
            created_at=now,
        )
        session.add(debit_entry)
        total_debits += debit_amount
        entries_created += 1

    # 3. Commit transactions atomically
    await session.commit()

    return SeedLedgerResponse(
        account_id=acc_id,
        period_date=payload.period_date.isoformat(),
        scenario=payload.scenario,
        entries_created=entries_created,
        total_credits_cents=total_credits,
        total_debits_cents=total_debits,
    )
