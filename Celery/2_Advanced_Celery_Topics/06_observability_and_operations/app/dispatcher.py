"""Celery canvas dispatcher for real-time fraud scoring and sanctions compliance workflows.

Prepares JSON payloads, propagates distributed correlation context, and dispatches canvases.
"""

import logging
from typing import Any
from uuid import UUID

from celery import chain
from celery.result import AsyncResult
from services.worker.tasks.scoring import evaluate_screening
from services.worker.tasks.screening import check_aml_watchlist, handle_screening_failure

from app.logging_config import current_request_id
from app.schemas import ScreeningRequest

logger = logging.getLogger(__name__)


def dispatch_screening_workflow(
    screening_id: UUID,
    request: ScreeningRequest,
    correlation_id: str | None = None,
) -> AsyncResult:
    """Construct and dispatch the asynchronous distributed screening canvas workflow.

    Workflow architecture:
    1. evaluate_screening (fraud.screening.critical): real-time velocity & heuristic scoring
    2. check_aml_watchlist (fraud.aml.bulk): external sanctions & watchlist verification
    3. handle_screening_failure: compensating errback linked via link_error

    Args:
        screening_id: Persistent UUID assigned to the in-flight screening record.
        request: Validated incoming screening request model.
        correlation_id: Optional correlation identifier; defaults to current_request_id.

    Returns:
        AsyncResult: Handle to the initiated Celery canvas execution.
    """
    # 1. Resolve active request correlation ID for distributed tracing
    req_id = correlation_id or current_request_id.get() or str(screening_id)

    # 2. Prepare JSON-serializable primitives for AMQP broker safety
    payload_data: dict[str, Any] = {
        "screening_id": str(screening_id),
        "transaction_id": request.transaction_id,
        "account_id": request.account_id,
        "amount_cents": request.amount_cents,
        "currency": request.currency,
        "client_ip": request.client_ip,
        "entity_name": request.entity_name,
        "velocity_5m_count": request.velocity_5m_count,
    }

    logger.info(
        "dispatching_screening_workflow",
        extra={
            "screening_id": str(screening_id),
            "transaction_id": request.transaction_id,
            "request_id": req_id,
        },
    )

    # 3. Assemble Celery canvas chain with compensating errback
    workflow = chain(
        evaluate_screening.s(payload_data),
        check_aml_watchlist.s(),
    )

    # 4. Attach link_error errback for unrecoverable task exceptions
    errback_sig = handle_screening_failure.s(screening_id=str(screening_id))

    # 5. Publish to AMQP broker with trace context headers
    async_result = workflow.apply_async(
        headers={"X-Request-ID": req_id},
        link_error=errback_sig,
    )

    return async_result
