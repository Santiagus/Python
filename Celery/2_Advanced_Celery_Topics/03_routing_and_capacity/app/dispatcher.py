"""API Message Dispatcher & Task Producer.

The Producer layer is strictly decoupled from the worker consumers. It handles
payload preparation, batch .chunks(100) slicing, trace context injection (X-Request-ID),
and AMQP message dispatching across isolated queues.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from celery.result import AsyncResult

from app.config import get_settings
from app.logging_config import current_request_id
from services.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


class PaymentDispatcher:
    """Dispatches validated payment workflows to RabbitMQ broker queues."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def dispatch_instant_payout(
        self,
        payment_id: str | UUID,
        correlation_id: str | None = None,
    ) -> AsyncResult:
        """Dispatch real-time payment to the 'critical' queue with highest AMQP priority.

        Args:
            payment_id: UUID of payment record.
            correlation_id: Optional explicit tracing correlation ID.

        Returns:
            AsyncResult: Celery async task result handle.
        """
        # 1. Resolve correlation ID from parameter or ContextVar
        corr_id = correlation_id or current_request_id.get() or str(payment_id)

        # 2. Dispatch to dedicated critical queue with maximum priority (10)
        task_result = celery_app.send_task(
            "services.worker.tasks.payouts.process_instant_payout",
            args=[str(payment_id)],
            queue=self.settings.critical_queue,
            routing_key="payment.instant.payout",
            priority=10,
            headers={"correlation_id": corr_id},
        )

        logger.info(
            "instant_payout_dispatched",
            extra={
                "payment_id": str(payment_id),
                "task_id": task_result.id,
                "queue": self.settings.critical_queue,
                "correlation_id": corr_id,
            },
        )

        return task_result

    def dispatch_batch_settlement(
        self,
        batch_id: str | UUID,
        disbursement_ids: list[str],
        chunk_size: int | None = None,
        correlation_id: str | None = None,
    ) -> list[AsyncResult]:
        """Slice disbursement items into .chunks(100) and dispatch to the 'bulk' queue.

        Args:
            batch_id: UUID of parent batch settlement.
            disbursement_ids: List of string UUIDs for disbursement line items.
            chunk_size: Number of items per chunk. Defaults to settings.batch_chunk_size (100).
            correlation_id: Optional explicit tracing ID.

        Returns:
            list[AsyncResult]: List of task result handles for all chunks.
        """
        # 1. Resolve chunk size and correlation ID
        actual_chunk_size = chunk_size or self.settings.batch_chunk_size
        corr_id = correlation_id or current_request_id.get() or str(batch_id)

        # 2. Partition items into chunks of 100
        chunks = [
            disbursement_ids[i : i + actual_chunk_size]
            for i in range(0, len(disbursement_ids), actual_chunk_size)
        ]

        logger.info(
            "slicing_batch_into_chunks",
            extra={
                "batch_id": str(batch_id),
                "total_items": len(disbursement_ids),
                "chunk_size": actual_chunk_size,
                "total_chunks": len(chunks),
            },
        )

        # 3. Dispatch each chunk to the bulk queue
        task_results: list[AsyncResult] = []
        for index, chunk in enumerate(chunks):
            result = celery_app.send_task(
                "services.worker.tasks.settlements.process_payroll_chunk",
                args=[str(batch_id), index, chunk],
                queue=self.settings.bulk_queue,
                routing_key="settlement.batch.payroll",
                headers={"correlation_id": corr_id},
            )
            task_results.append(result)

        return task_results

