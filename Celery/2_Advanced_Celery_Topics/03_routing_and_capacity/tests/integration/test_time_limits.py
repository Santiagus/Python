"""Integration tests for Celery task time limits and timeout compensation."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded
import pytest
from sqlalchemy import select

from app.models import Account, Payment
from services.worker.tasks.payouts import process_instant_payout


@pytest.mark.integration
class TestTimeLimitsAndCompensation:
    """Test soft time limit (3s) enforcement and database refund compensation."""

    @pytest.mark.asyncio
    async def test_soft_time_limit_triggers_compensating_refund(
        self,
        db_session,
    ) -> None:
        """When soft time limit is exceeded during processing, balance is refunded and status set to failed."""
        source_id = uuid4()
        pid = uuid4()

        # 1. Create funding account with $1,000.00
        unique_acc_num = f"9999{uuid4().int % 1000000000000:012d}"
        account = Account(
            account_id=source_id,
            account_number=unique_acc_num,
            account_mask=f"******{unique_acc_num[-4:]}",
            balance_cents=100000,
            currency="USD",
        )
        db_session.add(account)

        # 2. Create pending payment for $200.00
        payment = Payment(
            payment_id=pid,
            idempotency_key=f"idemp_timeout_{uuid4().hex}",
            source_account_id=source_id,
            destination_account_number="11223344",
            destination_routing_number="021000021",
            amount_cents=20000,
            rail="rtp",
            priority="critical",
            status="pending",
        )
        db_session.add(payment)
        await db_session.commit()

        # 3. Simulate slow bank clearing call that raises SoftTimeLimitExceeded
        mock_bank_client = AsyncMock()
        mock_bank_client.clear_instant_payment.side_effect = SoftTimeLimitExceeded("3s exceeded")

        with patch("services.worker.tasks.payouts.BankSimulatorClient", return_value=mock_bank_client):
            with pytest.raises(SoftTimeLimitExceeded):
                process_instant_payout(str(pid))

        # 4. Verify in DB: payment is marked failed and account balance refunded
        db_session.expire_all()
        p_stmt = select(Payment).where(Payment.payment_id == pid)
        p_res = await db_session.execute(p_stmt)
        updated_payment = p_res.scalar_one()
        assert updated_payment.status == "failed"
        assert "soft time limit" in updated_payment.error_detail.lower()

        acc_stmt = select(Account).where(Account.account_id == source_id)
        acc_res = await db_session.execute(acc_stmt)
        updated_account = acc_res.scalar_one()
        assert updated_account.balance_cents == 100000  # Full $1,000.00 restored!

    @pytest.mark.asyncio
    async def test_soft_time_limit_when_payment_not_processing(self, db_session) -> None:
        """When soft time limit fires but payment was not in 'processing' state, compensation skips cleanly."""
        non_existent_pid = uuid4()
        with patch("services.worker.tasks.payouts._execute_instant_payout", side_effect=SoftTimeLimitExceeded):
            with pytest.raises(SoftTimeLimitExceeded):
                process_instant_payout(str(non_existent_pid))
