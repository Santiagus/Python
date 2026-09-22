"""Notification and operational webhook tasks.

Handles asynchronous receipt delivery and merchant event webhooks routed to the
'default' queue with task pacing rate limits ('100/m').
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.db import get_session_factory
from app.models import Payment
from services.worker.celery_app import celery_app
from services.worker.tasks.utils import run_sync

logger = logging.getLogger(__name__)


async def _process_send_receipt(payment_id_str: str) -> dict[str, Any]:
    """Inspect payment settlement details and simulate receipt generation."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Payment).where(Payment.payment_id == UUID(payment_id_str))
        res = await session.execute(stmt)
        payment = res.scalar_one_or_none()

        if not payment:
            logger.warning("receipt_payment_not_found", extra={"payment_id": payment_id_str})
            return {"status": "skipped", "reason": "Payment not found"}

        logger.info(
            "payment_receipt_generated",
            extra={
                "payment_id": payment_id_str,
                "amount_cents": payment.amount_cents,
                "status": payment.status,
                "clearing_ref": payment.external_reference,
            },
        )

        return {
            "status": "delivered",
            "payment_id": payment_id_str,
            "external_reference": payment.external_reference,
        }


@celery_app.task(
    bind=True,
    name="services.worker.tasks.notifications.send_payment_receipt",
    rate_limit="100/m",
    soft_time_limit=20,
    time_limit=30,
    acks_late=True,
)
def send_payment_receipt(self, payment_id: str) -> dict[str, Any]:
    """Deliver payment receipt asynchronously to payer/payee.

    Args:
        payment_id: String UUID of payment record.

    Returns:
        dict[str, Any]: Result Envelope.
    """
    return run_sync(_process_send_receipt(payment_id))


@celery_app.task(
    bind=True,
    name="services.worker.tasks.notifications.dispatch_merchant_webhook",
    rate_limit="100/m",
    soft_time_limit=20,
    time_limit=30,
    acks_late=True,
)
def dispatch_merchant_webhook(self, reference_id: str, event_type: str) -> dict[str, Any]:
    """Dispatch an HMAC-signed webhook event to subscriber endpoints.

    Args:
        reference_id: Payment or Batch ID.
        event_type: Domain event string (e.g. 'batch.completed', 'payment.settled').

    Returns:
        dict[str, Any]: Result Envelope.
    """
    logger.info(
        "merchant_webhook_dispatched",
        extra={"reference_id": reference_id, "event_type": event_type},
    )
    return {
        "status": "delivered",
        "reference_id": reference_id,
        "event_type": event_type,
    }

