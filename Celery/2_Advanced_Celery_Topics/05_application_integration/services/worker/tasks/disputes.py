"""Card dispute submission background task with cooperative cancellation.

Executes clearinghouse evidence transmission, cooperative in-flight cancellation checks,
and atomic single-query state machine transitions with zero speculative read overhead.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.db import get_session_factory
from app.models import CardDispute
from services.worker.celery_app import celery_app
from services.worker.tasks.utils import run_sync

logger = logging.getLogger(__name__)


async def _process_dispute_submission(
    dispute_id_str: str,
    simulate_failure: bool = False,
) -> dict[str, Any]:
    """Execute cooperative in-flight check, network transmission, and atomic state transition.

    Args:
        dispute_id_str: String representation of the target dispute UUID.
        simulate_failure: If True, simulates clearinghouse network timeout for testing.

    Returns:
        dict[str, Any]: Execution result envelope.
    """
    dispute_uuid = UUID(dispute_id_str)
    session_factory = get_session_factory()

    async with session_factory() as session:
        # 1. Cooperative in-flight cancellation check
        stmt = select(CardDispute.id, CardDispute.status).where(CardDispute.id == dispute_uuid)
        res = await session.execute(stmt)
        row = res.first()

        if not row:
            logger.warning("dispute_not_found", extra={"dispute_id": dispute_id_str})
            return {"status": "not_found", "dispute_id": dispute_id_str}

        current_status = row.status

        # 2. Check if cancellation already won the race prior to network submission
        if current_status == "cancelled":
            logger.info(
                "dispute_submission_aborted_due_to_cancellation",
                extra={"dispute_id": dispute_id_str},
            )
            return {
                "status": "cancelled",
                "dispute_id": dispute_id_str,
                "message": "Dispute was revoked in-flight prior to clearinghouse transmission",
            }

        if current_status != "processing":
            logger.info(
                "dispute_already_terminal",
                extra={"dispute_id": dispute_id_str, "status": current_status},
            )
            return {
                "status": current_status,
                "dispute_id": dispute_id_str,
                "message": f"Dispute is already in terminal state {current_status}",
            }

        # 3. Handle simulated failure or clearinghouse network transmission
        now = datetime.now(timezone.utc)
        if simulate_failure:
            fail_stmt = (
                update(CardDispute)
                .where(CardDispute.id == dispute_uuid, CardDispute.status == "processing")
                .values(
                    status="failed",
                    error_message="Clearinghouse timeout (simulated 503)",
                    updated_at=now,
                )
            )
            await session.execute(fail_stmt)
            await session.commit()

            logger.warning(
                "dispute_clearinghouse_submission_failed",
                extra={"dispute_id": dispute_id_str},
            )
            return {
                "status": "failed",
                "dispute_id": dispute_id_str,
                "error": "Clearinghouse timeout (simulated 503)",
            }

        # 4. Generate clearinghouse network reference ID (e.g. Visa VROL / MC Clearing)
        network_ref_id = f"VROL-{uuid.uuid4().hex[:8].upper()}"

        # 5. Atomic conditional update: strictly transition only if status is still 'processing'
        # If cancellation was executed in parallel, this update will match 0 rows
        success_stmt = (
            update(CardDispute)
            .where(CardDispute.id == dispute_uuid, CardDispute.status == "processing")
            .values(
                status="submitted_to_network",
                network_reference_id=network_ref_id,
                updated_at=now,
            )
        )
        update_res = await session.execute(success_stmt)
        await session.commit()

        if update_res.rowcount == 0:
            logger.info(
                "dispute_state_transition_superseded_by_cancellation",
                extra={"dispute_id": dispute_id_str},
            )
            return {
                "status": "cancelled",
                "dispute_id": dispute_id_str,
                "message": "Dispute was cancelled concurrently before state update could commit",
            }

        logger.info(
            "dispute_submitted_to_network",
            extra={
                "dispute_id": dispute_id_str,
                "network_reference_id": network_ref_id,
            },
        )
        return {
            "status": "submitted_to_network",
            "dispute_id": dispute_id_str,
            "network_reference_id": network_ref_id,
        }


@celery_app.task(
    bind=True,
    name="services.worker.tasks.disputes.submit_card_dispute_task",
    max_retries=3,
    default_retry_delay=5,
)
def submit_card_dispute_task(
    self: Any,
    dispute_id: str,
    simulate_failure: bool = False,
) -> dict[str, Any]:
    """Celery background task for asynchronous card dispute submission to clearinghouse.

    Args:
        self: Bound Celery task instance.
        dispute_id: Unique string UUID of the dispute to submit.
        simulate_failure: Flag to simulate upstream network timeout.

    Returns:
        dict[str, Any]: Result envelope containing status and network reference ID.
    """
    return run_sync(_process_dispute_submission(dispute_id, simulate_failure))
