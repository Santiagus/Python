"""Periodic data retention and expired idempotency key cleanup task.

Purges expired idempotency records from PostgreSQL to control storage growth
and maintain optimal index efficiency over long operational horizons.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete

from app.db import get_session_factory
from app.models import IdempotencyRecord
from services.worker.celery_app import celery_app
from services.worker.tasks.utils import run_sync

logger = logging.getLogger(__name__)


async def _execute_cleanup() -> dict[str, Any]:
    """Execute asynchronous database purge of expired idempotency keys.

    Returns:
        dict[str, Any]: Cleanup summary containing deleted row count and execution timestamp.
    """
    now_utc = datetime.now(timezone.utc)
    session_factory = get_session_factory()

    async with session_factory() as session:
        # 1. Delete all records whose expiration timestamp has passed
        stmt = delete(IdempotencyRecord).where(IdempotencyRecord.expires_at < now_utc)
        result = await session.execute(stmt)
        purged_count = int(result.rowcount)  # type: ignore[attr-defined]

        # 2. Commit transaction
        await session.commit()

        logger.info(
            "Purged expired idempotency records (count=%d, cutoff=%s)",
            purged_count,
            now_utc.isoformat(),
        )

        return {
            "status": "completed",
            "purged_count": purged_count,
            "executed_at": now_utc.isoformat(),
        }


@celery_app.task(name="services.worker.tasks.cleanup.purge_expired_records")
def purge_expired_records() -> dict[str, Any]:
    """Execute scheduled cleanup of expired idempotency records.

    Returns:
        dict[str, Any]: Execution result envelope with purged row count.
    """
    return run_sync(_execute_cleanup())
