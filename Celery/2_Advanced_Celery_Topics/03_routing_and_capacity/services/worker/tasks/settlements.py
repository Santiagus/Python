"""High-volume batch payroll and settlement chunk tasks (ACH/NACHA).

Consumes .chunks(100) from the 'bulk' queue, applies worker token-bucket rate limiting
('500/m'), executes bulk database updates, and triggers completion notifications.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.db import get_session_factory
from app.models import BatchSettlement, Disbursement
from services.bank_simulator_api.client import BankSimulatorClient
from services.worker.celery_app import celery_app
from services.worker.tasks.notifications import dispatch_merchant_webhook
from services.worker.tasks.utils import run_sync

logger = logging.getLogger(__name__)


async def _execute_payroll_chunk(batch_id_str: str, chunk_index: int, item_ids: list[str]) -> dict[str, Any]:
    """Execute batch chunk processing against the bank simulator and update database."""
    batch_uuid = UUID(batch_id_str)
    item_uuids = [UUID(i) for i in item_ids]
    session_factory = get_session_factory()
    bank_client = BankSimulatorClient()

    # 1. Fetch disbursement records for this chunk
    items_payload: list[dict[str, Any]] = []
    async with session_factory() as session:
        stmt = select(Disbursement).where(Disbursement.disbursement_id.in_(item_uuids))
        res = await session.execute(stmt)
        disbursements = res.scalars().all()

        for d in disbursements:
            items_payload.append({
                "disbursement_id": str(d.disbursement_id),
                "account_number": d.account_number,
                "routing_number": d.routing_number,
                "amount_cents": d.amount_cents,
            })

    # 2. Transmit chunk to partner clearing rail with rate pacing
    await bank_client.clear_batch_chunk(
        batch_id=batch_id_str,
        chunk_index=chunk_index,
        items=items_payload,
    )

    # 3. Perform bulk database status updates in a single atomic transaction
    batch_completed = False
    async with session_factory() as session:
        async with session.begin():
            # Update disbursement line items to settled
            update_disbursements_stmt = (
                update(Disbursement)
                .where(Disbursement.disbursement_id.in_(item_uuids))
                .values(status="settled", updated_at=datetime.now(timezone.utc))
            )
            await session.execute(update_disbursements_stmt)

            # Atomically increment processed items counter on parent batch
            batch_stmt = (
                select(BatchSettlement)
                .where(BatchSettlement.batch_id == batch_uuid)
                .with_for_update()
            )
            batch_res = await session.execute(batch_stmt)
            batch = batch_res.scalar_one()

            batch.processed_items += len(item_uuids)

            # Check if all chunks have finished
            if batch.processed_items >= batch.total_items:
                batch.status = "completed"
                batch_completed = True

            await session.commit()

    # 4. If entire batch is complete, trigger merchant webhook notification
    if batch_completed:
        logger.info("batch_settlement_completed", extra={"batch_id": batch_id_str, "total": len(item_ids)})
        dispatch_merchant_webhook.si(batch_id_str, "batch.settlement.completed").apply_async()

    return {
        "status": "ok",
        "batch_id": batch_id_str,
        "chunk_index": chunk_index,
        "processed_count": len(item_ids),
        "batch_completed": batch_completed,
    }


@celery_app.task(
    bind=True,
    name="services.worker.tasks.settlements.process_payroll_chunk",
    rate_limit="500/m",
    soft_time_limit=240,
    time_limit=300,
    acks_late=True,
)
def process_payroll_chunk(self, batch_id: str, chunk_index: int, item_ids: list[str]) -> dict[str, Any]:
    """Celery task processing a high-volume payroll chunk.

    Args:
        batch_id: String UUID of parent batch settlement.
        chunk_index: Zero-based sequence index.
        item_ids: List of disbursement string UUIDs.

    Returns:
        dict[str, Any]: Result Envelope.
    """
    logger.info(
        "processing_payroll_chunk",
        extra={
            "batch_id": batch_id,
            "chunk_index": chunk_index,
            "chunk_size": len(item_ids),
        },
    )
    return run_sync(_execute_payroll_chunk(batch_id, chunk_index, item_ids))

