"""Integration tests for EOD ledger reconciliation Celery task, idempotency, and locking."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from unittest.mock import patch

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


@pytest.mark.integration
async def test_reconcile_eod_cutoff_completes_inflight_processing(db_session: AsyncSession) -> None:
    """Verify that an existing in-flight report with status='processing' is completed to 'balanced'."""
    period = "2026-09-27"
    period_d = date(2026, 9, 27)

    # 1. Pre-insert an in-flight report record
    inflight_report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=period_d,
        status="processing",
        total_credits_cents=0,
        total_debits_cents=0,
        net_movement_cents=0,
        discrepancy_cents=0,
        verification_hash="",
        metadata_json={"trigger": "manual_api"},
    )
    db_session.add(inflight_report)

    # 2. Add ledger entry
    account = Account(
        account_number=f"9999{uuid.uuid4().hex[:12]}",
        account_mask="******4444",
        balance_cents=2000000,
    )
    db_session.add(account)
    await db_session.flush()

    db_session.add(
        LedgerEntry(
            account_id=account.account_id,
            amount_cents=150000,
            direction="credit",
            status="posted",
            period_date=period_d,
        )
    )
    await db_session.commit()

    # 3. Execute Celery task
    result = reconcile_eod_cutoff(period_date=period, clearing_variance_cents=0)

    # 4. Assert outcome is completed and status is balanced
    assert result["outcome"] == "completed"
    assert result["status"] == "balanced"
    assert result["total_credits_cents"] == 150000

    # 5. Verify database record
    db_session.expire_all()
    db_report = await db_session.execute(
        select(ReconciliationReport).where(ReconciliationReport.period_date == period_d)
    )
    report = db_report.scalar_one()
    assert report.status == "balanced"
    assert report.total_credits_cents == 150000
    assert report.metadata_json is not None
    assert report.metadata_json.get("re-verified") is False


@pytest.mark.integration
async def test_reconcile_eod_cutoff_failure_persists_failed_status_existing_report(
    db_session: AsyncSession,
) -> None:
    """Verify that an exception during aggregation marks an existing report as 'failed' in DB."""
    period = "2026-09-28"
    period_d = date(2026, 9, 28)

    # 1. Pre-insert an in-flight report record
    inflight_report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=period_d,
        status="processing",
        total_credits_cents=0,
        total_debits_cents=0,
        net_movement_cents=0,
        discrepancy_cents=0,
        verification_hash="",
        metadata_json={"trigger": "manual_api"},
    )
    db_session.add(inflight_report)
    await db_session.commit()

    # 2. Simulate failure during hash calculation
    with patch(
        "services.worker.tasks.reconciliation._calculate_reconciliation_hash",
        side_effect=RuntimeError("Cryptographic failure"),
    ):
        with pytest.raises(RuntimeError, match="Cryptographic failure"):
            reconcile_eod_cutoff(period_date=period)

    # 3. Verify database record was marked as failed
    db_session.expire_all()
    db_report = await db_session.execute(
        select(ReconciliationReport).where(ReconciliationReport.period_date == period_d)
    )
    report = db_report.scalar_one()
    assert report.status == "failed"
    assert report.metadata_json is not None
    assert "Cryptographic failure" in report.metadata_json["error"]


@pytest.mark.integration
async def test_reconcile_eod_cutoff_failure_persists_failed_status_no_prior_report(
    db_session: AsyncSession,
) -> None:
    """Verify that an exception creates a new 'failed' report if no report existed prior to failure."""
    period = "2026-09-29"
    period_d = date(2026, 9, 29)

    # Simulate failure during hash calculation
    with patch(
        "services.worker.tasks.reconciliation._calculate_reconciliation_hash",
        side_effect=RuntimeError("Checksum crash"),
    ):
        with pytest.raises(RuntimeError, match="Checksum crash"):
            reconcile_eod_cutoff(period_date=period)

    # Verify new failed report was persisted
    db_session.expire_all()
    db_report = await db_session.execute(
        select(ReconciliationReport).where(ReconciliationReport.period_date == period_d)
    )
    report = db_report.scalar_one()
    assert report.status == "failed"
    assert report.metadata_json is not None
    assert "Checksum crash" in report.metadata_json["error"]


@pytest.mark.integration
async def test_reconcile_eod_cutoff_failure_inner_rollback_logged() -> None:
    """Verify that if saving the failed status itself fails, it logs error and re-raises original exception."""
    period = "2026-09-30"

    orig_select = select
    select_call_count = 0

    def fail_on_third_select(*args: Any, **kwargs: Any) -> Any:
        nonlocal select_call_count
        select_call_count += 1
        if select_call_count >= 3:
            raise RuntimeError("Inner select DB error")
        return orig_select(*args, **kwargs)

    with patch(
        "services.worker.tasks.reconciliation._calculate_reconciliation_hash",
        side_effect=RuntimeError("Fatal error"),
    ):
        with patch("services.worker.tasks.reconciliation.select", side_effect=fail_on_third_select):
            with pytest.raises(RuntimeError, match="Fatal error"):
                reconcile_eod_cutoff(period_date=period)
