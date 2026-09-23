"""Unit tests for domain tasks in payouts, settlements, and notifications."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded
import pytest

from services.bank_simulator_api.client import BankClearingError
from services.worker.tasks.notifications import (
    dispatch_merchant_webhook,
    send_payment_receipt,
)
from services.worker.tasks.payouts import _execute_instant_payout, process_instant_payout
from services.worker.tasks.settlements import _execute_payroll_chunk, process_payroll_chunk


def _create_mock_session() -> AsyncMock:
    """Helper creating a properly structured AsyncMock session."""
    session = AsyncMock()
    session.begin = MagicMock()
    session.begin.return_value.__aenter__ = AsyncMock(return_value=None)
    session.begin.return_value.__aexit__ = AsyncMock(return_value=None)
    return session


def _create_mock_factory(sessions: list[AsyncMock]) -> MagicMock:
    """Helper creating session_factory that yields sessions in sequence."""
    factory = MagicMock()
    context_managers = []
    for s in sessions:
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=s)
        cm.__aexit__ = AsyncMock(return_value=None)
        context_managers.append(cm)
    factory.side_effect = context_managers
    return factory


@pytest.mark.unit
class TestPayoutTasks:
    """Test instant payout execution, balance reservation, and compensating refunds."""

    @pytest.mark.asyncio
    async def test_instant_payout_payment_not_found(self) -> None:
        """When payment UUID does not exist, return error envelope."""
        pid = str(uuid4())
        session = _create_mock_session()
        res_mock = MagicMock()
        res_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = res_mock

        factory = _create_mock_factory([session])

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory):
            res = await _execute_instant_payout(pid)
            assert res["status"] == "error"
            assert "not found" in res["error"]

    @pytest.mark.asyncio
    async def test_instant_payout_already_settled_idempotency(self) -> None:
        """When payment is already settled, skip execution safely."""
        pid = str(uuid4())
        mock_payment = MagicMock()
        mock_payment.status = "settled"

        session = _create_mock_session()
        res_mock = MagicMock()
        res_mock.scalar_one_or_none.return_value = mock_payment
        session.execute.return_value = res_mock

        factory = _create_mock_factory([session])

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory):
            res = await _execute_instant_payout(pid)
            assert res["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_instant_payout_insufficient_funds(self) -> None:
        """When source account has insufficient balance, reject payment immediately."""
        pid = str(uuid4())
        mock_payment = MagicMock()
        mock_payment.status = "pending"
        mock_payment.amount_cents = 500000  # $5,000.00
        mock_payment.source_account_id = uuid4()

        mock_account = MagicMock()
        mock_account.balance_cents = 1000  # $10.00

        session = _create_mock_session()
        res1 = MagicMock()
        res1.scalar_one_or_none.return_value = mock_payment
        res2 = MagicMock()
        res2.scalar_one_or_none.return_value = mock_account
        session.execute.side_effect = [res1, res2]

        factory = _create_mock_factory([session])

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory):
            res = await _execute_instant_payout(pid)
            assert res["status"] == "rejected"
            assert mock_payment.status == "rejected"
            assert mock_payment.error_detail == "Insufficient account balance"

    @pytest.mark.asyncio
    async def test_instant_payout_happy_path(self) -> None:
        """Successful payout reserves balance, calls bank, marks settled, and chains receipt."""
        pid = str(uuid4())
        source_id = uuid4()

        mock_payment = MagicMock()
        mock_payment.status = "pending"
        mock_payment.amount_cents = 25000
        mock_payment.source_account_id = source_id
        mock_payment.destination_account_number = "12345678"
        mock_payment.destination_routing_number = "021000021"
        mock_payment.rail = "rtp"

        mock_account = MagicMock()
        mock_account.balance_cents = 100000

        session_p1 = _create_mock_session()
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        r2 = MagicMock()
        r2.scalar_one_or_none.return_value = mock_account
        session_p1.execute.side_effect = [r1, r2]

        mock_payment_p3 = MagicMock()
        session_p3 = _create_mock_session()
        r3 = MagicMock()
        r3.scalar_one.return_value = mock_payment_p3
        session_p3.execute.return_value = r3

        factory = _create_mock_factory([session_p1, session_p3])

        mock_bank_client = AsyncMock()
        mock_bank_client.clear_instant_payment.return_value = {
            "status": "settled",
            "clearing_reference": "CLR_RTP_TEST_123",
        }

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.payouts.BankSimulatorClient", return_value=mock_bank_client), \
             patch("services.worker.tasks.payouts.send_payment_receipt.si") as mock_receipt:

            res = await _execute_instant_payout(pid)

            assert res["status"] == "ok"
            assert res["clearing_reference"] == "CLR_RTP_TEST_123"
            assert mock_account.balance_cents == 75000
            assert mock_payment_p3.status == "settled"
            assert mock_receipt.called

    @pytest.mark.asyncio
    async def test_instant_payout_bank_failure_compensation(self) -> None:
        """When bank rail rejects payment, compensating refund restores source balance."""
        pid = str(uuid4())
        source_id = uuid4()

        mock_payment = MagicMock()
        mock_payment.status = "pending"
        mock_payment.amount_cents = 10000
        mock_payment.source_account_id = source_id
        mock_payment.destination_account_number = "1234"
        mock_payment.destination_routing_number = "021000021"
        mock_payment.rail = "fednow"

        mock_account = MagicMock()
        mock_account.balance_cents = 50000

        session_p1 = _create_mock_session()
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        r2 = MagicMock()
        r2.scalar_one_or_none.return_value = mock_account
        session_p1.execute.side_effect = [r1, r2]

        mock_payment_p3 = MagicMock()
        mock_account_p3 = MagicMock()
        mock_account_p3.balance_cents = 40000  # post-deduction
        session_p3 = _create_mock_session()
        r3 = MagicMock()
        r3.scalar_one.return_value = mock_payment_p3
        r4 = MagicMock()
        r4.scalar_one.return_value = mock_account_p3
        session_p3.execute.side_effect = [r3, r4]

        factory = _create_mock_factory([session_p1, session_p3])

        mock_bank_client = AsyncMock()
        mock_bank_client.clear_instant_payment.side_effect = BankClearingError("Partner bank timeout")

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.payouts.BankSimulatorClient", return_value=mock_bank_client):

            res = await _execute_instant_payout(pid)

            assert res["status"] == "failed"
            assert "Partner bank timeout" in res["error"]
            assert mock_account_p3.balance_cents == 50000  # Refunded
            assert mock_payment_p3.status == "failed"

    @pytest.mark.asyncio
    async def test_instant_payout_circuit_breaker_rail_failover_success(self) -> None:
        """When primary rail circuit is OPEN, payment fails over to healthy secondary rail."""
        from app.circuit_breaker import CircuitBreakerOpenError
        pid = str(uuid4())
        source_id = uuid4()

        mock_payment = MagicMock(status="pending", amount_cents=10000, source_account_id=source_id,
                                 destination_account_number="1234", destination_routing_number="021000021",
                                 rail="rtp")
        mock_account = MagicMock(balance_cents=50000)

        session_p1 = _create_mock_session()
        r1, r2 = MagicMock(), MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        r2.scalar_one_or_none.return_value = mock_account
        session_p1.execute.side_effect = [r1, r2]

        mock_payment_p3 = MagicMock()
        session_p3 = _create_mock_session()
        r3 = MagicMock()
        r3.scalar_one.return_value = mock_payment_p3
        session_p3.execute.return_value = r3

        factory = _create_mock_factory([session_p1, session_p3])

        mock_bank_client = AsyncMock()
        mock_bank_client.clear_instant_payment.side_effect = [
            CircuitBreakerOpenError(rail="rtp"),
            {"status": "settled", "clearing_reference": "CLR_FEDNOW_FAILOVER_999"},
        ]

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.payouts.BankSimulatorClient", return_value=mock_bank_client), \
             patch("services.worker.tasks.payouts.get_fallback_rail", return_value="fednow"), \
             patch("services.worker.tasks.payouts.send_payment_receipt.si"):

            res = await _execute_instant_payout(pid)
            assert res["status"] == "ok"
            assert res["clearing_reference"] == "CLR_FEDNOW_FAILOVER_999"
            assert mock_payment_p3.status == "settled"

    @pytest.mark.asyncio
    async def test_instant_payout_circuit_breaker_rail_failover_failure(self) -> None:
        """When primary rail circuit is OPEN and secondary rail clearance also fails, compensation occurs."""
        from app.circuit_breaker import CircuitBreakerOpenError
        pid = str(uuid4())
        source_id = uuid4()

        mock_payment = MagicMock(status="pending", amount_cents=10000, source_account_id=source_id,
                                 destination_account_number="1234", destination_routing_number="021000021",
                                 rail="rtp")
        mock_account = MagicMock(balance_cents=50000)

        session_p1 = _create_mock_session()
        r1, r2 = MagicMock(), MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        r2.scalar_one_or_none.return_value = mock_account
        session_p1.execute.side_effect = [r1, r2]

        mock_payment_p3 = MagicMock()
        mock_account_p3 = MagicMock(balance_cents=40000)
        session_p3 = _create_mock_session()
        r3, r4 = MagicMock(), MagicMock()
        r3.scalar_one.return_value = mock_payment_p3
        r4.scalar_one.return_value = mock_account_p3
        session_p3.execute.side_effect = [r3, r4]

        factory = _create_mock_factory([session_p1, session_p3])

        mock_bank_client = AsyncMock()
        mock_bank_client.clear_instant_payment.side_effect = [
            CircuitBreakerOpenError(rail="rtp"),
            RuntimeError("FedNow clearing rail rejected"),
        ]

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.payouts.BankSimulatorClient", return_value=mock_bank_client), \
             patch("services.worker.tasks.payouts.get_fallback_rail", return_value="fednow"):

            res = await _execute_instant_payout(pid)
            assert res["status"] == "failed"
            assert "Fallback rail fednow failed" in res["error"]
            assert mock_account_p3.balance_cents == 50000  # Refunded

    @pytest.mark.asyncio
    async def test_instant_payout_circuit_breaker_fast_fail_no_fallback(self) -> None:
        """When circuit is OPEN and no fallback rail is available, fast-fails immediately."""
        from app.circuit_breaker import CircuitBreakerOpenError
        pid = str(uuid4())
        source_id = uuid4()

        mock_payment = MagicMock(status="pending", amount_cents=10000, source_account_id=source_id,
                                 destination_account_number="1234", destination_routing_number="021000021",
                                 rail="rtp")
        mock_account = MagicMock(balance_cents=50000)

        session_p1 = _create_mock_session()
        r1, r2 = MagicMock(), MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        r2.scalar_one_or_none.return_value = mock_account
        session_p1.execute.side_effect = [r1, r2]

        mock_payment_p3 = MagicMock()
        mock_account_p3 = MagicMock(balance_cents=40000)
        session_p3 = _create_mock_session()
        r3, r4 = MagicMock(), MagicMock()
        r3.scalar_one.return_value = mock_payment_p3
        r4.scalar_one.return_value = mock_account_p3
        session_p3.execute.side_effect = [r3, r4]

        factory = _create_mock_factory([session_p1, session_p3])

        mock_bank_client = AsyncMock()
        mock_bank_client.clear_instant_payment.side_effect = CircuitBreakerOpenError(rail="rtp")

        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.payouts.BankSimulatorClient", return_value=mock_bank_client), \
             patch("services.worker.tasks.payouts.get_fallback_rail", return_value=None):

            res = await _execute_instant_payout(pid)
            assert res["status"] == "failed"
            assert "no healthy fallback available" in res["error"]
            assert mock_account_p3.balance_cents == 50000  # Refunded

    @pytest.mark.asyncio
    async def test_instant_payout_soft_time_limit_in_bank_call(self) -> None:
        """When bank client raises SoftTimeLimitExceeded, _execute_instant_payout re-raises."""
        pid = str(uuid4())
        source_id = uuid4()
        mock_payment = MagicMock(status="pending", amount_cents=10000, source_account_id=source_id,
                                 destination_account_number="1234", destination_routing_number="021000021",
                                 rail="rtp")
        mock_account = MagicMock(balance_cents=50000)
        session = _create_mock_session()
        r1, r2 = MagicMock(), MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        r2.scalar_one_or_none.return_value = mock_account
        session.execute.side_effect = [r1, r2]
        factory = _create_mock_factory([session])
        mock_bank_client = AsyncMock()
        mock_bank_client.clear_instant_payment.side_effect = SoftTimeLimitExceeded
        with patch("services.worker.tasks.payouts.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.payouts.BankSimulatorClient", return_value=mock_bank_client):
            with pytest.raises(SoftTimeLimitExceeded):
                await _execute_instant_payout(pid)

    def test_process_instant_payout_task_wrapper(self) -> None:
        """Verify Celery task synchronous wrapper invokes async function."""
        with patch("services.worker.tasks.payouts._execute_instant_payout", return_value={"status": "ok"}):
            res = process_instant_payout(str(uuid4()))
            assert res["status"] == "ok"

    def test_process_instant_payout_soft_time_limit_handling(self) -> None:
        """Verify SoftTimeLimitExceeded triggers compensating refund and re-raises."""
        pid = str(uuid4())
        source_id = uuid4()
        mock_payment = MagicMock(status="processing", amount_cents=15000, source_account_id=source_id)
        mock_account = MagicMock(balance_cents=35000)

        session = _create_mock_session()
        r1, r2 = MagicMock(), MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        r2.scalar_one.return_value = mock_account
        session.execute.side_effect = [r1, r2]
        factory = _create_mock_factory([session])

        with patch("services.worker.tasks.payouts._execute_instant_payout", side_effect=SoftTimeLimitExceeded), \
             patch("services.worker.tasks.payouts.get_session_factory", return_value=factory):
            with pytest.raises(SoftTimeLimitExceeded):
                process_instant_payout(pid)

            assert mock_account.balance_cents == 50000
            assert mock_payment.status == "failed"
            assert "3s soft time limit" in mock_payment.error_detail

    def test_process_instant_payout_timeout_when_not_processing(self) -> None:
        """When payment is not in processing state during timeout, compensation is skipped."""
        pid = str(uuid4())
        mock_payment = MagicMock(status="settled")
        session = _create_mock_session()
        r1 = MagicMock()
        r1.scalar_one_or_none.return_value = mock_payment
        session.execute.return_value = r1
        factory = _create_mock_factory([session])

        with patch("services.worker.tasks.payouts._execute_instant_payout", side_effect=SoftTimeLimitExceeded), \
             patch("services.worker.tasks.payouts.get_session_factory", return_value=factory):
            with pytest.raises(SoftTimeLimitExceeded):
                process_instant_payout(pid)

    def test_process_instant_payout_timeout_compensation_failure(self) -> None:
        """When compensation fails during soft time limit handling, it logs and re-raises SoftTimeLimitExceeded."""
        with patch("services.worker.tasks.payouts._execute_instant_payout", side_effect=SoftTimeLimitExceeded), \
             patch("services.worker.tasks.payouts.get_session_factory", side_effect=RuntimeError("DB connection dead")):
            with pytest.raises(SoftTimeLimitExceeded):
                process_instant_payout(str(uuid4()))


@pytest.mark.unit
class TestSettlementTasks:
    """Test batch payroll chunk processing and webhook triggering."""

    @pytest.mark.asyncio
    async def test_payroll_chunk_happy_path(self) -> None:
        """Process chunk, update database records, and complete batch."""
        batch_id = str(uuid4())
        item_ids = [str(uuid4()), str(uuid4())]

        d1 = MagicMock(disbursement_id=item_ids[0], account_number="111", routing_number="021", amount_cents=1000)
        d2 = MagicMock(disbursement_id=item_ids[1], account_number="222", routing_number="021", amount_cents=2000)

        session_read = _create_mock_session()
        r1 = MagicMock()
        r1.scalars.return_value.all.return_value = [d1, d2]
        session_read.execute.return_value = r1

        mock_batch = MagicMock(processed_items=0, total_items=2, status="pending")
        session_write = _create_mock_session()
        r2 = MagicMock()
        r3 = MagicMock()
        r3.scalar_one.return_value = mock_batch
        session_write.execute.side_effect = [r2, r3]

        factory = _create_mock_factory([session_read, session_write])

        mock_bank = AsyncMock()
        mock_bank.clear_batch_chunk.return_value = {"status": "accepted"}

        with patch("services.worker.tasks.settlements.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.settlements.BankSimulatorClient", return_value=mock_bank), \
             patch("services.worker.tasks.settlements.dispatch_merchant_webhook.si") as mock_webhook:

            res = await _execute_payroll_chunk(batch_id, 0, item_ids)

            assert res["status"] == "ok"
            assert res["batch_completed"] is True
            assert mock_batch.status == "completed"
            assert mock_webhook.called

    @pytest.mark.asyncio
    async def test_payroll_chunk_partial_batch_not_completed(self) -> None:
        """Process chunk where batch still has pending items (batch_completed=False)."""
        batch_id = str(uuid4())
        item_ids = [str(uuid4())]

        d1 = MagicMock(disbursement_id=item_ids[0], account_number="111", routing_number="021", amount_cents=1000)

        session_read = _create_mock_session()
        r1 = MagicMock()
        r1.scalars.return_value.all.return_value = [d1]
        session_read.execute.return_value = r1

        mock_batch = MagicMock(processed_items=0, total_items=10, status="processing")
        session_write = _create_mock_session()
        r2 = MagicMock()
        r3 = MagicMock()
        r3.scalar_one.return_value = mock_batch
        session_write.execute.side_effect = [r2, r3]

        factory = _create_mock_factory([session_read, session_write])
        mock_bank = AsyncMock()
        mock_bank.clear_batch_chunk.return_value = {"status": "accepted"}

        with patch("services.worker.tasks.settlements.get_session_factory", return_value=factory), \
             patch("services.worker.tasks.settlements.BankSimulatorClient", return_value=mock_bank):

            res = await _execute_payroll_chunk(batch_id, 0, item_ids)

            assert res["status"] == "ok"
            assert res["batch_completed"] is False
            assert mock_batch.status == "processing"

    def test_process_payroll_chunk_task_wrapper(self) -> None:
        """Verify Celery task synchronous wrapper for payroll chunk."""
        with patch("services.worker.tasks.settlements._execute_payroll_chunk", return_value={"status": "ok"}):
            res = process_payroll_chunk(str(uuid4()), 0, ["id1", "id2"])
            assert res["status"] == "ok"


@pytest.mark.unit
class TestCelerySignals:
    """Test task_prerun and task_postrun signal handlers for correlation ID ContextVar binding."""

    def test_prerun_with_correlation_id_header(self) -> None:
        from app.logging_config import current_request_id
        from services.worker.celery_app import _task_context_tokens, handle_task_postrun, handle_task_prerun

        mock_task = MagicMock()
        mock_task.name = "test_task"
        mock_task.request.headers = {"correlation_id": "corr_abc_123"}
        handle_task_prerun(sender=None, task_id="task_1", task=mock_task, args=(), kwargs={})
        assert current_request_id.get() == "corr_abc_123"
        assert "task_1" in _task_context_tokens

        # Clean up via postrun
        handle_task_postrun(sender=None, task_id="task_1", task=mock_task, args=(), kwargs={}, retval=None, state="SUCCESS")
        assert current_request_id.get() is None

    def test_prerun_with_request_id_fallback(self) -> None:
        from app.logging_config import current_request_id
        from services.worker.celery_app import handle_task_postrun, handle_task_prerun

        mock_task = MagicMock()
        mock_task.name = "test_task"
        mock_task.request.headers = {"request_id": "req_xyz_789"}
        handle_task_prerun(sender=None, task_id="task_2", task=mock_task, args=(), kwargs={})
        assert current_request_id.get() == "req_xyz_789"
        handle_task_postrun(sender=None, task_id="task_2", task=mock_task, args=(), kwargs={}, retval=None, state="SUCCESS")

    def test_prerun_with_no_headers_uses_task_id(self) -> None:
        from app.logging_config import current_request_id
        from services.worker.celery_app import handle_task_postrun, handle_task_prerun

        mock_task = MagicMock()
        mock_task.name = "test_task"
        mock_task.request.headers = None
        handle_task_prerun(sender=None, task_id="task_3", task=mock_task, args=(), kwargs={})
        assert current_request_id.get() == "task_3"
        handle_task_postrun(sender=None, task_id="task_3", task=mock_task, args=(), kwargs={}, retval=None, state="SUCCESS")

    def test_postrun_unknown_task_id(self) -> None:
        from services.worker.celery_app import handle_task_postrun

        mock_task = MagicMock()
        mock_task.name = "test_task"
        # Should not raise exception when task_id not in dictionary
        handle_task_postrun(sender=None, task_id="unknown_task_999", task=mock_task, args=(), kwargs={}, retval=None, state="SUCCESS")

    def test_worker_process_init(self) -> None:
        import app.db as app_db
        from services.bank_simulator_api import client as bank_client_module
        from services.worker.celery_app import handle_worker_process_init
        from services.worker.tasks import utils

        app_db._engine = None
        app_db._session_factory = None

        handle_worker_process_init(sender=None)

        assert app_db._engine is not None
        assert app_db._session_factory is not None
        assert bank_client_module.bank_simulator_client is not None
        assert getattr(utils._thread_local, "loop", None) is not None

    def test_worker_process_shutdown_with_engine(self) -> None:
        import app.db as app_db
        from services.worker.celery_app import handle_worker_process_shutdown
        from services.worker.tasks import utils

        loop = utils.get_worker_loop()
        mock_close = AsyncMock()
        mock_client_close = AsyncMock()

        with patch("app.db.close_db", mock_close), \
             patch("services.bank_simulator_api.client.close_bank_client", mock_client_close):
            app_db._engine = MagicMock()
            handle_worker_process_shutdown(sender=None)
            assert mock_close.called
            assert mock_client_close.called

    def test_worker_process_shutdown_with_exception(self) -> None:
        import app.db as app_db
        from services.worker.celery_app import handle_worker_process_shutdown
        from services.worker.tasks import utils

        loop = utils.get_worker_loop()
        mock_close = AsyncMock(side_effect=RuntimeError("close failed"))
        mock_client_close = AsyncMock(side_effect=RuntimeError("client close failed"))

        with patch("app.db.close_db", mock_close), \
             patch("services.bank_simulator_api.client.close_bank_client", mock_client_close):
            app_db._engine = MagicMock()
            handle_worker_process_shutdown(sender=None)
            assert mock_close.called
            assert mock_client_close.called

    def test_worker_process_shutdown_no_loop(self) -> None:
        from services.worker.celery_app import handle_worker_process_shutdown
        from services.worker.tasks import utils

        utils.reset_worker_loop()
        # Should execute cleanly without error
        handle_worker_process_shutdown(sender=None)

    def test_worker_process_shutdown_loop_open_no_engine(self) -> None:
        import app.db as app_db
        from services.worker.celery_app import handle_worker_process_shutdown
        from services.worker.tasks import utils

        utils.get_worker_loop()
        app_db._engine = None
        handle_worker_process_shutdown(sender=None)
        assert getattr(utils._thread_local, "loop", None) is None



@pytest.mark.unit
class TestWorkerUtils:
    """Test worker event loop lifecycle and synchronous execution adapter."""

    def test_get_worker_loop_creates_and_reuses(self) -> None:
        from services.worker.tasks import utils

        utils.reset_worker_loop()
        loop1 = utils.get_worker_loop()
        assert not loop1.is_closed()

        loop2 = utils.get_worker_loop()
        assert loop1 is loop2
        utils.reset_worker_loop()

    def test_reset_worker_loop_when_closed(self) -> None:
        from services.worker.tasks import utils

        loop = utils.get_worker_loop()
        loop.close()
        # Should cleanly handle already closed loop
        utils.reset_worker_loop()
        assert getattr(utils._thread_local, "loop", None) is None

    def test_run_sync_outside_event_loop(self) -> None:
        from services.worker.tasks.utils import reset_worker_loop, run_sync

        reset_worker_loop()

        async def _sample_coro():
            await asyncio.sleep(0.001)
            return 42

        res = run_sync(_sample_coro())
        assert res == 42
        reset_worker_loop()

    @pytest.mark.asyncio
    async def test_run_sync_inside_event_loop(self) -> None:
        from services.worker.tasks.utils import reset_worker_loop, run_sync

        async def _inner_coro():
            await asyncio.sleep(0.001)
            return "from_thread"

        res = run_sync(_inner_coro())
        assert res == "from_thread"
        reset_worker_loop()

    def test_sync_executor_lifecycle(self) -> None:
        from services.worker.tasks import utils

        executor = utils.get_sync_executor()
        assert executor is not None
        assert not executor._shutdown

        utils.shutdown_sync_executor()
        # calling get_sync_executor after shutdown should re-initialize
        new_executor = utils.get_sync_executor()
        assert new_executor is not None
        assert not new_executor._shutdown

        # test when _sync_executor is None
        utils._sync_executor = None
        recreated = utils.get_sync_executor()
        assert recreated is not None
        assert not recreated._shutdown



@pytest.mark.unit
class TestNotificationTasks:
    """Test receipt delivery and merchant webhook notifications."""

    def test_send_payment_receipt_success(self) -> None:
        """Delivers receipt when payment exists."""
        pid = str(uuid4())
        mock_payment = MagicMock(amount_cents=5000, status="settled", external_reference="CLR_123")
        session = _create_mock_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = mock_payment
        session.execute.return_value = r

        factory = _create_mock_factory([session])

        with patch("services.worker.tasks.notifications.get_session_factory", return_value=factory):
            res = send_payment_receipt(pid)
            assert res["status"] == "delivered"
            assert res["external_reference"] == "CLR_123"

    def test_send_payment_receipt_skipped_when_not_found(self) -> None:
        """Skips receipt when payment is not found."""
        pid = str(uuid4())
        session = _create_mock_session()
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        session.execute.return_value = r

        factory = _create_mock_factory([session])

        with patch("services.worker.tasks.notifications.get_session_factory", return_value=factory):
            res = send_payment_receipt(pid)
            assert res["status"] == "skipped"

    def test_dispatch_merchant_webhook(self) -> None:
        """Dispatches merchant webhook event."""
        res = dispatch_merchant_webhook("batch_123", "batch.settlement.completed")
        assert res["status"] == "delivered"
        assert res["event_type"] == "batch.settlement.completed"

