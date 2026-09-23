"""Historical gap detection and backfill Celery task for missed EOD cut-offs.

Audits unclosed Monday-through-Friday banking business periods, identifies missing
reconciliation reports, and sequentially dispatches individual cut-off tasks in strict
chronological order while guarded by a distributed concurrency mutex.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.db import get_session_factory
from app.models import LedgerEntry, ReconciliationReport
from services.worker.celery_app import celery_app
from services.worker.locks import distributed_lock
from services.worker.tasks.utils import run_sync

logger = logging.getLogger(__name__)

RECONCILIATION_TASK_NAME = "services.worker.tasks.reconciliation.reconcile_eod_cutoff"


async def _execute_gap_backfill(
    start_date_str: str | None = None,
    end_date_str: str | None = None,
) -> dict[str, Any]:
    """Execute asynchronous database audit to detect missing periods and dispatch backfills.

    Args:
        start_date_str: Optional ISO string for scan range start.
        end_date_str: Optional ISO string for scan range end.

    Returns:
        dict[str, Any]: Normalized result envelope detailing backfill outcome.
    """
    now_utc = datetime.now(timezone.utc)
    session_factory = get_session_factory()

    # 1. Determine effective end_date (defaults to yesterday UTC)
    if end_date_str is not None:
        end_date = date.fromisoformat(end_date_str)
    else:
        end_date = (now_utc - timedelta(days=1)).date()

    async with session_factory() as session:
        # 2. Determine effective start_date (defaults to earliest ledger activity or 30 days ago)
        if start_date_str is not None:
            start_date = date.fromisoformat(start_date_str)
        else:
            earliest_entry_res = await session.execute(select(func.min(LedgerEntry.period_date)))
            earliest_entry = earliest_entry_res.scalar_one_or_none()

            earliest_report_res = await session.execute(select(func.min(ReconciliationReport.period_date)))
            earliest_report = earliest_report_res.scalar_one_or_none()

            candidates = [d for d in [earliest_entry, earliest_report] if d is not None]
            if candidates:
                start_date = min(candidates)
            else:
                start_date = end_date - timedelta(days=30)

        # 3. Validate boundary order
        if start_date > end_date:
            logger.warning(
                "Invalid backfill range requested: start_date (%s) > end_date (%s)",
                start_date,
                end_date,
            )
            return {
                "status": "invalid_range",
                "message": f"start_date ({start_date}) cannot be after end_date ({end_date})",
                "scan_range_start": start_date.isoformat(),
                "scan_range_end": end_date.isoformat(),
                "missing_gaps_count": 0,
                "dispatched_tasks": [],
            }

        # 4. Query all existing reconciliation reports within the window
        reports_stmt = select(ReconciliationReport.period_date).where(
            ReconciliationReport.period_date >= start_date,
            ReconciliationReport.period_date <= end_date,
        )
        reports_res = await session.execute(reports_stmt)
        existing_dates = set(reports_res.scalars().all())

    # 5. Identify missing Monday-through-Friday business days (0=Mon, 4=Fri)
    missing_dates: list[date] = []
    curr = start_date
    while curr <= end_date:
        if curr.weekday() < 5 and curr not in existing_dates:
            missing_dates.append(curr)
        curr += timedelta(days=1)

    # 6. Sequentially dispatch individual reconciliation tasks in strict chronological order
    dispatched_tasks: list[dict[str, str]] = []
    for missing_date in missing_dates:
        date_str = missing_date.isoformat()
        result = celery_app.send_task(
            RECONCILIATION_TASK_NAME,
            args=[date_str, 0],
            queue="reconciliation",
            routing_key="scheduling.reconciliation",
            headers={"source": "gap_backfill"},
        )
        dispatched_tasks.append(
            {
                "period_date": date_str,
                "task_id": str(result.id),
            }
        )
        logger.info(
            "Dispatched backfill reconciliation for missed period %s (task_id=%s)",
            date_str,
            result.id,
        )

    return {
        "status": "ok",
        "scan_range_start": start_date.isoformat(),
        "scan_range_end": end_date.isoformat(),
        "missing_gaps_count": len(missing_dates),
        "dispatched_tasks": dispatched_tasks,
    }


@celery_app.task(
    name="services.worker.tasks.backfill.detect_and_backfill_gaps",
    bind=True,
    acks_late=True,
)
def detect_and_backfill_gaps(
    self: Any,
    start_date_str: str | None = None,
    end_date_str: str | None = None,
) -> dict[str, Any]:
    """Execute scheduled or manual historical gap detection and sequential backfill.

    Guarded by an atomic Redis mutex to prevent overlapping executions from concurrent
    schedules or simultaneous API triggers.

    Args:
        self: Bound Celery task instance.
        start_date_str: Optional ISO string for scan range start ('YYYY-MM-DD').
        end_date_str: Optional ISO string for scan range end ('YYYY-MM-DD').

    Returns:
        dict[str, Any]: Execution result envelope.
    """
    lock_key = "lock:backfill:gaps"

    # 1. Acquire distributed lock with a 60-second TTL
    with distributed_lock(lock_key, ttl_seconds=60) as acquired:
        if not acquired:
            logger.warning(
                "Gap backfill task skipped: another worker holds lock %s",
                lock_key,
            )
            return {
                "status": "skipped_overlap",
                "message": "Another gap backfill job is currently executing",
            }

        # 2. Execute gap audit and dispatching logic inside sync-in-async adapter
        return run_sync(
            _execute_gap_backfill(
                start_date_str=start_date_str,
                end_date_str=end_date_str,
            )
        )
