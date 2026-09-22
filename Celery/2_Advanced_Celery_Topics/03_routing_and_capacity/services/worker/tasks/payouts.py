"""Real-time instant payout domain tasks (FedNow & RTP).

Implements the Two-Phase Balance Reservation pattern with zero network I/O held inside
database row locks, strict soft/hard time limits, and automated receipt chaining.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from app.db import get_session_factory
from app.models import Account, Payment
from services.bank_simulator_api.client import BankClearingError, BankSimulatorClient
from services.worker.celery_app import celery_app
from services.worker.tasks.notifications import send_payment_receipt
from services.worker.tasks.utils import run_sync

logger = logging.getLogger(__name__)


async def _execute_instant_payout(payment_id_str: str) -> dict[str, Any]:
    """Execute the two-phase balance reservation and partner bank clearing workflow."""
    payment_uuid = UUID(payment_id_str)
    session_factory = get_session_factory()
    bank_client = BankSimulatorClient()

    source_account_id: UUID | None = None
    amount_cents: int = 0
    destination_account: str = ""
    destination_routing: str = ""
    rail: str = ""

    # =========================================================================
    # PHASE 1: ATOMIC DATABASE BALANCE RESERVATION (LOCK HELD < 3MS)
    # =========================================================================
    async with session_factory() as session:
        # 1. Fetch payment record with row lock
        payment_stmt = select(Payment).where(Payment.payment_id == payment_uuid).with_for_update()
        payment_res = await session.execute(payment_stmt)
        payment = payment_res.scalar_one_or_none()

        if not payment:
            logger.error("payment_not_found", extra={"payment_id": payment_id_str})
            return {"status": "error", "error": "Payment record not found"}

        # Idempotency check: if already processed or settled, do not re-execute
        if payment.status in ("settled", "processing"):
            logger.info("payment_already_processed", extra={"payment_id": payment_id_str, "status": payment.status})
            return {"status": "skipped", "message": f"Payment already in status {payment.status}"}

        # 2. Lock account record and check liquidity
        account_stmt = select(Account).where(Account.account_id == payment.source_account_id).with_for_update()
        account_res = await session.execute(account_stmt)
        account = account_res.scalar_one_or_none()

        if not account or account.balance_cents < payment.amount_cents:
            # Insufficient funds: reject payment immediately
            payment.status = "rejected"
            payment.error_detail = "Insufficient account balance"
            await session.commit()
            logger.warning("payment_insufficient_funds", extra={"payment_id": payment_id_str})
            return {"status": "rejected", "reason": "Insufficient account balance"}

        # 3. Reserve balance and transition payment to 'processing'
        account.balance_cents -= payment.amount_cents
        payment.status = "processing"

        # Cache values for external call outside lock
        source_account_id = payment.source_account_id
        amount_cents = payment.amount_cents
        destination_account = payment.destination_account_number
        destination_routing = payment.destination_routing_number
        rail = payment.rail

        # Invariant: Commit immediately! The account row lock is released now!
        await session.commit()

    # =========================================================================
    # PHASE 2: EXTERNAL BANK NETWORK CALL (ZERO DB LOCKS HELD)
    # =========================================================================
    bank_success = False
    clearing_reference: str | None = None
    failure_reason: str | None = None

    try:
        clearing_res = await bank_client.clear_instant_payment(
            payment_id=payment_id_str,
            amount_cents=amount_cents,
            rail=rail,
            destination_account_number=destination_account,
            destination_routing_number=destination_routing,
        )
        clearing_reference = clearing_res.get("clearing_reference")
        bank_success = True
    except SoftTimeLimitExceeded:
        raise
    except (BankClearingError, Exception) as exc:
        failure_reason = str(exc)
        logger.error("bank_clearing_failed", extra={"payment_id": payment_id_str, "error": failure_reason})

    # =========================================================================
    # PHASE 3: FINAL SETTLEMENT OR COMPENSATING REFUND
    # =========================================================================
    async with session_factory() as session:
        payment_stmt = select(Payment).where(Payment.payment_id == payment_uuid).with_for_update()
        payment_res = await session.execute(payment_stmt)
        payment = payment_res.scalar_one()

        if bank_success:
            # Settle payment
            payment.status = "settled"
            payment.cleared_at = datetime.now(timezone.utc)
            payment.external_reference = clearing_reference
            await session.commit()

            # Chain notification side-effect via immutable signature (.si)
            send_payment_receipt.si(payment_id_str).apply_async()

            return {
                "status": "ok",
                "payment_id": payment_id_str,
                "clearing_reference": clearing_reference,
            }
        else:
            # Compensating transaction: refund reserved balance back to source account
            account_stmt = select(Account).where(Account.account_id == source_account_id).with_for_update()
            account_res = await session.execute(account_stmt)
            account = account_res.scalar_one()
            account.balance_cents += amount_cents

            # Mark payment as failed
            payment.status = "failed"
            payment.error_detail = failure_reason
            await session.commit()

            return {
                "status": "failed",
                "payment_id": payment_id_str,
                "error": failure_reason,
            }


@celery_app.task(
    bind=True,
    name="services.worker.tasks.payouts.process_instant_payout",
    soft_time_limit=3,
    time_limit=5,
    acks_late=True,
)
def process_instant_payout(self, payment_id: str) -> dict[str, Any]:
    """Celery task executing real-time instant payout with SLA guarantees.

    Args:
        payment_id: String UUID of the payment record.

    Returns:
        dict[str, Any]: Result Envelope indicating outcome ('ok', 'rejected', 'failed').
    """
    try:
        return run_sync(_execute_instant_payout(payment_id))
    except SoftTimeLimitExceeded:
        logger.error("payout_soft_time_limit_exceeded", extra={"payment_id": payment_id})
        # Execute compensating refund synchronously if soft time limit hit during bank I/O
        async def _compensate_timeout():
            session_factory = get_session_factory()
            async with session_factory() as session:
                payment_stmt = select(Payment).where(Payment.payment_id == UUID(payment_id)).with_for_update()
                payment_res = await session.execute(payment_stmt)
                payment = payment_res.scalar_one_or_none()
                if payment and payment.status == "processing":
                    account_stmt = select(Account).where(Account.account_id == payment.source_account_id).with_for_update()
                    account_res = await session.execute(account_stmt)
                    account = account_res.scalar_one()
                    account.balance_cents += payment.amount_cents
                    payment.status = "failed"
                    payment.error_detail = "Execution exceeded 3s soft time limit"
                    await session.commit()

        try:
            run_sync(_compensate_timeout())
        except Exception as e:
            logger.exception("compensating_timeout_failed", extra={"payment_id": payment_id, "error": str(e)})

        raise

