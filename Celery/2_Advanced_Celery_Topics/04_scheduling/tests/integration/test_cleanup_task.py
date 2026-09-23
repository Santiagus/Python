"""Integration tests for expired idempotency key cleanup Celery task."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyRecord
from services.worker.tasks.cleanup import purge_expired_records


@pytest.mark.integration
async def test_purge_expired_records(db_session: AsyncSession) -> None:
    """Verify that expired idempotency records are deleted while active records are kept."""
    now = datetime.now(timezone.utc)

    # 1. Insert 2 expired records and 1 active record
    expired_1 = IdempotencyRecord(
        key="test_expired_key_1",
        scope="reconciliation",
        expires_at=now - timedelta(days=2),
    )
    expired_2 = IdempotencyRecord(
        key="test_expired_key_2",
        scope="reconciliation",
        expires_at=now - timedelta(hours=1),
    )
    active_1 = IdempotencyRecord(
        key="test_active_key_1",
        scope="reconciliation",
        expires_at=now + timedelta(days=5),
    )

    db_session.add_all([expired_1, expired_2, active_1])
    await db_session.commit()

    # 2. Execute cleanup task
    result = purge_expired_records()

    # 3. Assert results
    assert result["status"] == "completed"
    assert result["purged_count"] == 2

    # 4. Verify DB state
    remaining = await db_session.execute(select(IdempotencyRecord))
    remaining_keys = [r.key for r in remaining.scalars().all()]

    assert "test_active_key_1" in remaining_keys
    assert "test_expired_key_1" not in remaining_keys
    assert "test_expired_key_2" not in remaining_keys
