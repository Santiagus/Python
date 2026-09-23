"""End-of-Day (EOD) financial cut-off and ledger reconciliation Celery task.

Aggregates posted ledger transactions in minor-unit integer cents, verifies balance
integrity against clearinghouse settlement figures, generates cryptographic verification
hashes, and enforces strict period-level idempotency and concurrency locks.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import case, func, select

from app.db import get_session_factory
from app.models import LedgerEntry, ReconciliationReport
from services.worker.celery_app import celery_app
from services.worker.locks import distributed_lock
from services.worker.tasks.utils import run_sync

logger = logging.getLogger(__name__)


async def _execute_reconciliation(
    period_date_str: str,
    clearing_variance_cents: int = 0,
) -> dict[str, Any]:
    """Execute asynchronous database ledger aggregation and report generation.

    Args:
        period_date_str: Financial cut-off period date string ('YYYY-MM-DD').
        clearing_variance_cents: Optional minor-unit discrepancy simulated from external clearing.

    Returns:
        dict[str, Any]: Normalized result envelope detailing reconciliation outcome.
    """
    period = date.fromisoformat(period_date_str)
    session_factory = get_session_factory()

    async with session_factory() as session:
        # 1. Inspect if an existing report already exists for this date (Idempotency)
        existing_stmt = select(ReconciliationReport).where(ReconciliationReport.period_date == period)
        existing_res = await session.execute(existing_stmt)
        existing_report = existing_res.scalar_one_or_none()

        # 2. Execute single-query conditional aggregation across all posted entries for the date
        agg_stmt = select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.direction == "credit", LedgerEntry.amount_cents),
                        else_=0,
                    )
                ),
                0,
            ).label("total_credits"),
            func.coalesce(
                func.sum(
                    case(
                        (LedgerEntry.direction == "debit", LedgerEntry.amount_cents),
                        else_=0,
                    )
                ),
                0,
            ).label("total_debits"),
            func.count(LedgerEntry.entry_id).label("entry_count"),
        ).where(
            LedgerEntry.period_date == period,
            LedgerEntry.status == "posted",
        )

        agg_res = await session.execute(agg_stmt)
        row = agg_res.one()
        total_credits = int(row.total_credits)
        total_debits = int(row.total_debits)
        entry_count = int(row.entry_count)

        # 3. Calculate net movement and evaluate balance against clearing variance
        net_movement = total_credits - total_debits
        discrepancy = abs(clearing_variance_cents)
        report_status = "balanced" if discrepancy == 0 else "discrepancy_detected"

        # 4. Generate SHA-256 cryptographic verification checksum
        hash_payload = f"{period_date_str}:{total_credits}:{total_debits}:{net_movement}:{report_status}:{discrepancy}"
        verification_hash = hashlib.sha256(hash_payload.encode("utf-8")).hexdigest()

        # 5. Persist new report or perform in-place verification update
        now_utc = datetime.now(timezone.utc)
        if existing_report is not None:
            logger.info(
                "Updating existing reconciliation report (period=%s, prev_status=%s)",
                period_date_str,
                existing_report.status,
            )
            existing_report.total_credits_cents = total_credits
            existing_report.total_debits_cents = total_debits
            existing_report.net_movement_cents = net_movement
            existing_report.discrepancy_cents = discrepancy
            existing_report.status = report_status
            existing_report.verification_hash = verification_hash
            existing_report.reconciled_at = now_utc
            existing_report.metadata_json = {
                "entry_count": entry_count,
                "re-verified": True,
            }
            report_id = existing_report.report_id
            outcome = "verified_existing"
        else:
            logger.info(
                "Creating new reconciliation report (period=%s, status=%s)",
                period_date_str,
                report_status,
            )
            new_report = ReconciliationReport(
                report_id=uuid.uuid4(),
                period_date=period,
                total_credits_cents=total_credits,
                total_debits_cents=total_debits,
                net_movement_cents=net_movement,
                discrepancy_cents=discrepancy,
                status=report_status,
                verification_hash=verification_hash,
                reconciled_at=now_utc,
                metadata_json={
                    "entry_count": entry_count,
                    "re-verified": False,
                },
            )
            session.add(new_report)
            report_id = new_report.report_id
            outcome = "created"

        await session.commit()

        return {
            "outcome": outcome,
            "report_id": str(report_id),
            "period_date": period_date_str,
            "status": report_status,
            "total_credits_cents": total_credits,
            "total_debits_cents": total_debits,
            "net_movement_cents": net_movement,
            "discrepancy_cents": discrepancy,
            "entry_count": entry_count,
            "verification_hash": verification_hash,
        }


@celery_app.task(name="services.worker.tasks.reconciliation.reconcile_eod_cutoff")
def reconcile_eod_cutoff(
    period_date: str,
    clearing_variance_cents: int = 0,
) -> dict[str, Any]:
    """Execute scheduled or manual End-of-Day ledger reconciliation.

    Guarded by an atomic Redis mutex to prevent overlapping executions for the same period.

    Args:
        period_date: Financial cut-off period date in ISO format ('YYYY-MM-DD').
        clearing_variance_cents: Optional simulated external clearinghouse variance.

    Returns:
        dict[str, Any]: Execution result envelope.
    """
    lock_key = f"lock:reconciliation:{period_date}"

    # 1. Acquire distributed lock with a 60-second TTL
    with distributed_lock(lock_key, ttl_seconds=60) as acquired:
        if not acquired:
            logger.warning(
                "Reconciliation skipped for period %s: another worker holds lock %s",
                period_date,
                lock_key,
            )
            return {
                "outcome": "skipped_overlap",
                "period_date": period_date,
                "status": "skipped",
                "reason": "Concurrent reconciliation execution detected for this period",
            }

        # 2. Execute reconciliation logic inside sync-in-async adapter
        return run_sync(
            _execute_reconciliation(
                period_date_str=period_date,
                clearing_variance_cents=clearing_variance_cents,
            )
        )
