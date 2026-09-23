"""Integration tests for historical gap detection, sequential backfill dispatching, and locking."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, LedgerEntry, ReconciliationReport
from services.worker.locks import DistributedLock, get_redis_client
from services.worker.tasks.backfill import detect_and_backfill_gaps


@pytest.mark.integration
async def test_detect_and_backfill_gaps_finds_unclosed_business_days(db_session: AsyncSession) -> None:
    """Verify gap detection identifies missing Monday-through-Friday days and dispatches sequentially."""
    now = datetime.now(timezone.utc)

    # 1. Create reports for Monday 2026-09-14 and Friday 2026-09-18
    # Leaving Tuesday 2026-09-15, Wednesday 2026-09-16, and Thursday 2026-09-17 unclosed
    mon_report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=date(2026, 9, 14),
        total_credits_cents=100000,
        total_debits_cents=100000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="hash_mon",
        reconciled_at=now,
    )
    fri_report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=date(2026, 9, 18),
        total_credits_cents=100000,
        total_debits_cents=100000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="hash_fri",
        reconciled_at=now,
    )
    db_session.add_all([mon_report, fri_report])
    await db_session.commit()

    # 2. Mock celery_app.send_task to capture dispatched backfill tasks
    fake_tasks = [
        MagicMock(id="task-uuid-tue"),
        MagicMock(id="task-uuid-wed"),
        MagicMock(id="task-uuid-thu"),
    ]

    with patch("services.worker.tasks.backfill.celery_app.send_task", side_effect=fake_tasks) as mock_send:
        result = detect_and_backfill_gaps(
            start_date_str="2026-09-14",
            end_date_str="2026-09-18",
        )

        # 3. Assert execution results
        assert result["status"] == "ok"
        assert result["missing_gaps_count"] == 3
        assert result["scan_range_start"] == "2026-09-14"
        assert result["scan_range_end"] == "2026-09-18"

        dispatched = result["dispatched_tasks"]
        assert len(dispatched) == 3
        assert dispatched[0]["period_date"] == "2026-09-15"
        assert dispatched[0]["task_id"] == "task-uuid-tue"
        assert dispatched[1]["period_date"] == "2026-09-16"
        assert dispatched[1]["task_id"] == "task-uuid-wed"
        assert dispatched[2]["period_date"] == "2026-09-17"
        assert dispatched[2]["task_id"] == "task-uuid-thu"

        # 4. Verify send_task called with appropriate routing and queue
        assert mock_send.call_count == 3
        mock_send.assert_any_call(
            "services.worker.tasks.reconciliation.reconcile_eod_cutoff",
            args=["2026-09-15", 0],
            queue="reconciliation",
            routing_key="scheduling.reconciliation",
            headers={"source": "gap_backfill"},
        )


@pytest.mark.integration
async def test_detect_and_backfill_gaps_excludes_weekends(db_session: AsyncSession) -> None:
    """Verify Saturday and Sunday are excluded from gap detection between Friday and Monday."""
    now = datetime.now(timezone.utc)

    # Reports exist for Friday 2026-09-18 and Monday 2026-09-21
    fri_report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=date(2026, 9, 18),
        total_credits_cents=50000,
        total_debits_cents=50000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="hash_fri_weekend",
        reconciled_at=now,
    )
    mon_report = ReconciliationReport(
        report_id=uuid.uuid4(),
        period_date=date(2026, 9, 21),
        total_credits_cents=50000,
        total_debits_cents=50000,
        net_movement_cents=0,
        discrepancy_cents=0,
        status="balanced",
        verification_hash="hash_mon_weekend",
        reconciled_at=now,
    )
    db_session.add_all([fri_report, mon_report])
    await db_session.commit()

    with patch("services.worker.tasks.backfill.celery_app.send_task") as mock_send:
        result = detect_and_backfill_gaps(
            start_date_str="2026-09-18",
            end_date_str="2026-09-21",
        )

        assert result["status"] == "ok"
        assert result["missing_gaps_count"] == 0
        assert result["dispatched_tasks"] == []
        mock_send.assert_not_called()


@pytest.mark.integration
async def test_detect_and_backfill_gaps_all_closed(db_session: AsyncSession) -> None:
    """Verify zero tasks are dispatched when all business dates are already reconciled."""
    now = datetime.now(timezone.utc)
    reports = [
        ReconciliationReport(
            report_id=uuid.uuid4(),
            period_date=date(2026, 9, 14),
            total_credits_cents=100,
            total_debits_cents=100,
            net_movement_cents=0,
            discrepancy_cents=0,
            status="balanced",
            verification_hash="hash_14",
            reconciled_at=now,
        ),
        ReconciliationReport(
            report_id=uuid.uuid4(),
            period_date=date(2026, 9, 15),
            total_credits_cents=100,
            total_debits_cents=100,
            net_movement_cents=0,
            discrepancy_cents=0,
            status="balanced",
            verification_hash="hash_15",
            reconciled_at=now,
        ),
    ]
    db_session.add_all(reports)
    await db_session.commit()

    with patch("services.worker.tasks.backfill.celery_app.send_task") as mock_send:
        result = detect_and_backfill_gaps(
            start_date_str="2026-09-14",
            end_date_str="2026-09-15",
        )

        assert result["status"] == "ok"
        assert result["missing_gaps_count"] == 0
        mock_send.assert_not_called()


@pytest.mark.integration
def test_detect_and_backfill_gaps_invalid_range() -> None:
    """Verify error envelope is returned when start_date is strictly greater than end_date."""
    result = detect_and_backfill_gaps(
        start_date_str="2026-09-20",
        end_date_str="2026-09-10",
    )
    assert result["status"] == "invalid_range"
    assert "start_date" in result["message"]
    assert result["missing_gaps_count"] == 0
    assert result["dispatched_tasks"] == []


@pytest.mark.integration
async def test_detect_and_backfill_gaps_default_dates(db_session: AsyncSession) -> None:
    """Verify default scan range resolves earliest ledger entry up to yesterday UTC."""
    account = Account(
        account_number=f"ACC-{uuid.uuid4().hex[:10]}",
        account_mask="******2222",
        balance_cents=500000,
    )
    db_session.add(account)
    await db_session.flush()

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    start_d = yesterday - timedelta(days=5)

    entry = LedgerEntry(
        account_id=account.account_id,
        amount_cents=10000,
        direction="credit",
        status="posted",
        period_date=start_d,
    )
    db_session.add(entry)
    await db_session.commit()

    with patch("services.worker.tasks.backfill.celery_app.send_task") as mock_send:
        mock_send.return_value = MagicMock(id="default-task-id")
        result = detect_and_backfill_gaps()

        assert result["status"] == "ok"
        assert result["scan_range_start"] == start_d.isoformat()
        assert result["scan_range_end"] == yesterday.isoformat()


@pytest.mark.integration
def test_detect_and_backfill_gaps_default_dates_fallback_no_entries() -> None:
    """Verify default scan range falls back to 30 days ago when no records exist."""
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    expected_start = yesterday - timedelta(days=30)

    with patch("services.worker.tasks.backfill.celery_app.send_task") as mock_send:
        mock_send.return_value = MagicMock(id="fallback-task-id")
        result = detect_and_backfill_gaps()

        assert result["status"] == "ok"
        assert result["scan_range_start"] == expected_start.isoformat()
        assert result["scan_range_end"] == yesterday.isoformat()


@pytest.mark.integration
def test_detect_and_backfill_gaps_concurrency_mutex() -> None:
    """Verify overlapping executions are rejected when Redis mutex lock is held."""
    redis_client = get_redis_client()
    lock_key = "lock:backfill:gaps"
    lock = DistributedLock(lock_key, ttl_seconds=30, client=redis_client)

    acquired = lock.acquire()
    assert acquired is True

    try:
        # Second execution attempts to acquire the lock and is skipped
        result = detect_and_backfill_gaps()
        assert result["status"] == "skipped_overlap"
        assert "Another gap backfill job is currently executing" in result["message"]
    finally:
        lock.release()
