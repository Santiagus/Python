"""Integration tests for EOD ledger reconciliation Celery task, idempotency, and locking."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, LedgerEntry, ReconciliationReport
from services.worker.locks import DistributedLock, get_redis_client
from services.worker.tasks.reconciliation import reconcile_eod_cutoff


@pytest.mark.integration
async def test_reconcile_eod_cutoff_happy_path(db_session: AsyncSession) -> None:
    """Verify EOD cut-off calculates credit/debit totals, net movement, and balanced report."""
    period = "2026-09-23"
    period_d = date(2026, 9, 23)

    # 1. Create funding account
    account = Account(
        account_number=f"9999{uuid.uuid4().hex[:12]}",
        account_mask="******1111",
        balance_cents=10000000,
    )
    db_session.add(account)
    await db_session.flush()

    # 2. Insert sample posted transactions
    entries = [
        LedgerEntry(
            account_id=account.account_id,
            amount_cents=500000,  # +$5,000
            direction="credit",
            status="posted",
            period_date=period_d,
        ),
        LedgerEntry(
            account_id=account.account_id,
            amount_cents=200000,  # -$2,000
            direction="debit",
            status="posted",
            period_date=period_d,
        ),
        LedgerEntry(
            account_id=account.account_id,
            amount_cents=100000,  # +$1,000
            direction="credit",
            status="posted",
            period_date=period_d,
        ),
        # Cancelled entry (must be excluded from aggregation)
        LedgerEntry(
            account_id=account.account_id,
            amount_cents=999999,
            direction="credit",
            status="cancelled",
            period_date=period_d,
        ),
    ]
    db_session.add_all(entries)
    await db_session.commit()

    # 3. Execute Celery task
    result = reconcile_eod_cutoff(period_date=period, clearing_variance_cents=0)

    # 4. Verify result envelope
    assert result["outcome"] == "created"
    assert result["status"] == "balanced"
    assert result["total_credits_cents"] == 600000
    assert result["total_debits_cents"] == 200000
    assert result["net_movement_cents"] == 400000
    assert result["discrepancy_cents"] == 0
    assert result["entry_count"] == 3
    assert len(result["verification_hash"]) == 64

    # 5. Verify database record
    db_report = await db_session.execute(
        select(ReconciliationReport).where(ReconciliationReport.period_date == period_d)
    )
    report = db_report.scalar_one()
    assert report.status == "balanced"
    assert report.total_credits_cents == 600000


@pytest.mark.integration
async def test_reconcile_eod_cutoff_discrepancy_detected(db_session: AsyncSession) -> None:
    """Verify reconciliation detects variance between ledger and clearinghouse records."""
    period = "2026-09-24"
    period_d = date(2026, 9, 24)

    account = Account(
        account_number=f"9999{uuid.uuid4().hex[:12]}",
        account_mask="******2222",
        balance_cents=5000000,
    )
    db_session.add(account)
    await db_session.flush()

    db_session.add(
        LedgerEntry(
            account_id=account.account_id,
            amount_cents=300000,
            direction="credit",
            status="posted",
            period_date=period_d,
        )
    )
    await db_session.commit()

    # Simulate $50.00 (5,000 cents) discrepancy
    result = reconcile_eod_cutoff(period_date=period, clearing_variance_cents=5000)

    assert result["outcome"] == "created"
    assert result["status"] == "discrepancy_detected"
    assert result["discrepancy_cents"] == 5000


@pytest.mark.integration
async def test_reconcile_eod_cutoff_idempotent_reexecution(db_session: AsyncSession) -> None:
    """Verify re-running for an existing period updates in-place without duplicate rows."""
    period = "2026-09-25"
    period_d = date(2026, 9, 25)

    account = Account(
        account_number=f"9999{uuid.uuid4().hex[:12]}",
        account_mask="******3333",
        balance_cents=1000000,
    )
    db_session.add(account)
    await db_session.flush()

    db_session.add(
        LedgerEntry(
            account_id=account.account_id,
            amount_cents=100000,
            direction="credit",
            status="posted",
            period_date=period_d,
        )
    )
    await db_session.commit()

    # First execution
    res1 = reconcile_eod_cutoff(period_date=period)
    assert res1["outcome"] == "created"

    # Second execution on identical date
    res2 = reconcile_eod_cutoff(period_date=period)
    assert res2["outcome"] == "verified_existing"
    assert res2["report_id"] == res1["report_id"]

    # Verify only 1 database row exists for this date
    all_reports = await db_session.execute(
        select(ReconciliationReport).where(ReconciliationReport.period_date == period_d)
    )
    rows = all_reports.scalars().all()
    assert len(rows) == 1


@pytest.mark.integration
def test_reconcile_eod_cutoff_overlap_protection() -> None:
    """Verify that an active Redis mutex skips concurrent execution for the same period."""
    period = "2026-09-26"
    lock_key = f"lock:reconciliation:{period}"
    client = get_redis_client()

    # Pre-acquire the lock manually to simulate an in-flight worker
    manual_lock = DistributedLock(lock_key=lock_key, ttl_seconds=30, client=client)
    assert manual_lock.acquire() is True

    try:
        # Task invocation should detect contention and exit cleanly
        result = reconcile_eod_cutoff(period_date=period)
        assert result["outcome"] == "skipped_overlap"
        assert result["status"] == "skipped"
    finally:
        manual_lock.release()
