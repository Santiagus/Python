"""Unit tests for the API Producer dispatcher and batch chunk slicing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.dispatcher import PaymentDispatcher
from app.logging_config import current_request_id


@pytest.mark.unit
class TestPaymentDispatcher:
    """Test task preparation, priority injection, and chunk slicing."""

    def test_dispatch_instant_payout_with_correlation_id(self) -> None:
        """Verify instant payout dispatches to critical queue with priority 10."""
        dispatcher = PaymentDispatcher()
        pid = uuid4()
        corr_id = "req_custom_corr_123"

        with patch("services.worker.celery_app.celery_app.send_task") as mock_send:
            mock_send.return_value = MagicMock(id="task_mock_001")
            result = dispatcher.dispatch_instant_payout(payment_id=pid, correlation_id=corr_id)

            mock_send.assert_called_once_with(
                "services.worker.tasks.payouts.process_instant_payout",
                args=[str(pid)],
                queue="critical",
                routing_key="payment.instant.payout",
                priority=10,
                headers={"correlation_id": corr_id},
            )
            assert result.id == "task_mock_001"

    def test_dispatch_instant_payout_inherits_contextvar(self) -> None:
        """Verify correlation_id is read from active ContextVar if not explicitly passed."""
        dispatcher = PaymentDispatcher()
        pid = uuid4()
        token = current_request_id.set("req_from_contextvar")

        try:
            with patch("services.worker.celery_app.celery_app.send_task") as mock_send:
                dispatcher.dispatch_instant_payout(payment_id=pid)
                mock_send.assert_called_once()
                headers = mock_send.call_args[1]["headers"]
                assert headers["correlation_id"] == "req_from_contextvar"
        finally:
            current_request_id.reset(token)

    def test_dispatch_batch_settlement_chunking(self) -> None:
        """Verify 250 items are partitioned into 3 chunks: [100, 100, 50]."""
        dispatcher = PaymentDispatcher()
        batch_id = uuid4()
        item_ids = [f"item_{i:04d}" for i in range(250)]

        with patch("services.worker.celery_app.celery_app.send_task") as mock_send:
            mock_send.return_value = MagicMock()
            results = dispatcher.dispatch_batch_settlement(
                batch_id=batch_id,
                disbursement_ids=item_ids,
                chunk_size=100,
            )

            assert len(results) == 3
            assert mock_send.call_count == 3

            # Chunk 0
            call_0_args = mock_send.call_args_list[0]
            assert call_0_args[1]["args"] == [str(batch_id), 0, item_ids[0:100]]
            assert call_0_args[1]["queue"] == "bulk"
            assert call_0_args[1]["routing_key"] == "settlement.batch.payroll"

            # Chunk 1
            call_1_args = mock_send.call_args_list[1]
            assert call_1_args[1]["args"] == [str(batch_id), 1, item_ids[100:200]]

            # Chunk 2 (remainder)
            call_2_args = mock_send.call_args_list[2]
            assert call_2_args[1]["args"] == [str(batch_id), 2, item_ids[200:250]]

    def test_dispatch_batch_custom_chunk_size(self) -> None:
        """Verify custom chunk sizing."""
        dispatcher = PaymentDispatcher()
        batch_id = uuid4()
        items = ["a", "b", "c", "d", "e"]

        with patch("services.worker.celery_app.celery_app.send_task") as mock_send:
            mock_send.return_value = MagicMock()
            results = dispatcher.dispatch_batch_settlement(
                batch_id=batch_id,
                disbursement_ids=items,
                chunk_size=2,
            )
            assert len(results) == 3  # [2, 2, 1]

