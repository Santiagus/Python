"""Celery application configuration and Kombu AMQP routing topology.

Defines the Driver/Protocol Layer using Kombu primitives (Exchange, Queue),
dead-letter exchanges (DLX), message TTLs, worker invariants (acks_late=True),
and context variable correlation ID propagation across worker processes.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Celery, signals
from kombu import Exchange, Queue

from app.config import get_settings
from app.logging_config import current_request_id

logger = logging.getLogger(__name__)
settings = get_settings()

# =============================================================================
# 1. Driver / Protocol Layer: Kombu AMQP Exchanges
# =============================================================================
payments_exchange = Exchange("payments.direct", type="direct", durable=True)
dead_letter_exchange = Exchange("payments.dlx", type="direct", durable=True)

# =============================================================================
# 2. Driver / Protocol Layer: Isolated AMQP Queues with Dead-Lettering
# =============================================================================
task_queues = [
    # Tier 1: Real-Time Critical Queue (FedNow / RTP, P99 < 100ms)
    Queue(
        "critical",
        exchange=payments_exchange,
        routing_key="payment.instant.payout",
        queue_arguments={
            "x-max-priority": 10,
            "x-dead-letter-exchange": "payments.dlx",
            "x-dead-letter-routing-key": "payment.rejected",
        },
    ),
    # Tier 2: Standard Operational Queue (Receipts, Webhooks)
    Queue(
        "default",
        exchange=payments_exchange,
        routing_key="payment.standard.#",
        queue_arguments={
            "x-dead-letter-exchange": "payments.dlx",
            "x-dead-letter-routing-key": "payment.rejected",
        },
    ),
    # Tier 3: High-Volume Bulk Queue (ACH / NACHA Payroll Batches)
    Queue(
        "bulk",
        exchange=payments_exchange,
        routing_key="settlement.batch.payroll",
        queue_arguments={
            "x-message-ttl": 86400000,  # 24-hour message expiry
            "x-dead-letter-exchange": "payments.dlx",
            "x-dead-letter-routing-key": "payment.rejected",
        },
    ),
    # Dead Letter Queue (Quarantine for Poison Pills & Expired Messages)
    Queue(
        "rejected_payments",
        exchange=dead_letter_exchange,
        routing_key="payment.rejected",
    ),
]

# =============================================================================
# 3. Application Layer: Domain Task Routes
# =============================================================================
task_routes = {
    # 1. Real-Time Critical Tasks (Domain: payouts)
    "services.worker.tasks.payouts.process_instant_payout": {
        "queue": "critical",
        "routing_key": "payment.instant.payout",
    },
    # 2. Standard Operational Tasks (Domain: notifications)
    "services.worker.tasks.notifications.send_payment_receipt": {
        "queue": "default",
        "routing_key": "payment.standard.receipt",
    },
    "services.worker.tasks.notifications.dispatch_merchant_webhook": {
        "queue": "default",
        "routing_key": "payment.standard.webhook",
    },
    # 3. High-Volume Batch Tasks (Domain: settlements)
    "services.worker.tasks.settlements.process_payroll_chunk": {
        "queue": "bulk",
        "routing_key": "settlement.batch.payroll",
    },
}

# =============================================================================
# 4. Celery Application Initialization & Settings
# =============================================================================
backend_url = settings.redis_url if settings.environment not in ("test", "testing") else None

celery_app = Celery(
    "payment_orchestrator",
    broker=settings.rabbitmq_url,
    backend=backend_url,
    include=["services.worker.tasks"],
)

celery_app.conf.update(
    task_queues=task_queues,
    task_routes=task_routes,
    task_default_queue="default",
    task_default_exchange="payments.direct",
    task_default_routing_key="payment.standard.default",
    # Serialization safety: strictly JSON primitives
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Operational reliability invariants
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_pool_limit=10,
    broker_connection_retry_on_startup=True,
    result_expires=86400,  # Results retain for 24h
)

# Token dictionary for ContextVar cleanup per task
_task_context_tokens: dict[str, Any] = {}


# =============================================================================
# 5. Distributed Tracing & ContextVar Signals
# =============================================================================
@signals.task_prerun.connect
def handle_task_prerun(sender, task_id: str, task, args, kwargs, **kw) -> None:
    """Extract correlation_id from AMQP task headers and bind to worker ContextVar."""
    # 1. Inspect request headers attached during API dispatcher publish
    headers = getattr(task.request, "headers", None) or {}
    correlation_id = headers.get("correlation_id") or headers.get("request_id") or task_id

    # 2. Bind to ContextVar so worker logs mirror the original HTTP request trace
    token = current_request_id.set(correlation_id)
    _task_context_tokens[task_id] = token

    logger.debug(
        "worker_task_started",
        extra={
            "task_name": task.name,
            "task_id": task_id,
            "correlation_id": correlation_id,
        },
    )


@signals.task_postrun.connect
def handle_task_postrun(sender, task_id: str, task, args, kwargs, retval, state, **kw) -> None:
    """Reset ContextVar token upon task completion to prevent context leakage."""
    token = _task_context_tokens.pop(task_id, None)
    if token is not None:
        current_request_id.reset(token)

    logger.debug(
        "worker_task_finished",
        extra={
            "task_name": task.name,
            "task_id": task_id,
            "state": state,
        },
    )


@signals.worker_process_init.connect
def handle_worker_process_init(sender, **kw) -> None:
    """Reset process-local database engine and event loop in child worker processes."""
    """Eagerly initialize process-local resources immediately on worker process boot."""
    import app.db as app_db
    from services.bank_simulator_api import client as bank_client_module
    from services.worker.tasks import utils

    # 1. Reset database connection pool inherited across process fork boundary
    app_db._engine = None
    app_db._session_factory = None

    # 2. Reset thread-local worker event loop
    # 1. Reset and eagerly initialize thread-local worker event loop
    utils.reset_worker_loop()
    utils.get_worker_loop()

    # 2. Eagerly initialize worker-budgeted database connection pool (pool_size=2, max_overflow=2)
    app_db.init_worker_db()

    # 3. Eagerly initialize worker-local bank simulator client
    bank_client_module.init_bank_client()


@signals.worker_process_shutdown.connect
def handle_worker_process_shutdown(sender, **kw) -> None:
    """Clean up process-local database connections and close event loop."""
    """Clean up process-local database connections, HTTP client, and event loop."""
    import app.db as app_db
    from services.bank_simulator_api import client as bank_client_module
    from services.worker.tasks import utils

    loop = getattr(utils._thread_local, "loop", None)
    if loop is not None and not loop.is_closed():
        # 1. Close external bank client connection pool
        try:
            loop.run_until_complete(bank_client_module.close_bank_client())
        except Exception:
            pass

        # 2. Dispose database connection pool
        if app_db._engine is not None:
            try:
                loop.run_until_complete(app_db.close_db())
            except Exception:
                pass

    # 3. Shut down synchronous worker thread pool
    utils.shutdown_sync_executor()

    # 4. Close thread-local event loop
    utils.reset_worker_loop()
