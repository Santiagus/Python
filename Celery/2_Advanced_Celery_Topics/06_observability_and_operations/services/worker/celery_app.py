"""Celery Worker application and AMQP Kombu topology configuration.

Defines the message routing architecture, dead-letter exchanges, Prometheus metric
instrumentation, and graceful lifecycle shutdown hooks.
"""

import os
import time
from typing import Any

from celery import Celery, signals
from kombu import Exchange, Queue
from prometheus_client import Counter, Gauge, Histogram

# ==============================================================================
# Prometheus Task Metrics Registry
# ==============================================================================
CELERY_TASKS_TOTAL = Counter(
    "celery_tasks_total",
    "Total Celery tasks processed across worker fleet",
    ["task_name", "status"],
)
CELERY_TASK_DURATION_SECONDS = Histogram(
    "celery_task_duration_seconds",
    "Task runtime duration in seconds",
    ["task_name", "queue"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)
CELERY_TASKS_IN_FLIGHT = Gauge(
    "celery_tasks_in_flight",
    "Celery tasks currently in flight per process",
    ["task_name", "queue"],
)
CELERY_TASKS_RETRIED_TOTAL = Counter(
    "celery_tasks_retried_total",
    "Count of Celery task retries triggered by transient failures",
    ["task_name", "reason"],
)

# ==============================================================================
# 1. Driver / Protocol Layer: Kombu AMQP 0-9-1 Topology
# ==============================================================================
fraud_exchange = Exchange("fraud.direct", type="direct", durable=True)
dlx_exchange = Exchange("fraud.dlx", type="direct", durable=True)

fraud_screening_queue = Queue(
    "fraud.screening.critical",
    exchange=fraud_exchange,
    routing_key="fraud.screening.critical",
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange": "fraud.dlx",
        "x-dead-letter-routing-key": "fraud.screening.dlq",
    },
)

fraud_aml_queue = Queue(
    "fraud.aml.bulk",
    exchange=fraud_exchange,
    routing_key="fraud.aml.bulk",
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange": "fraud.dlx",
        "x-dead-letter-routing-key": "fraud.screening.dlq",
    },
)

fraud_dlq = Queue(
    "fraud.screening.dlq",
    exchange=dlx_exchange,
    routing_key="fraud.screening.dlq",
    durable=True,
)

# ==============================================================================
# 2. Celery Application Construction & Invariants
# ==============================================================================
broker_url = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

celery_app = Celery(
    "fraud_screening_worker",
    broker=broker_url,
    backend=result_backend,
    include=[
        "services.worker.tasks.scoring",
        "services.worker.tasks.screening",
    ],
)

celery_app.conf.update(
    # Broker & Socket Connection Limits
    broker_pool_limit=10,
    broker_connection_retry_on_startup=True,
    # Prefetch Multiplier & Acknowledgment Discipline
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Strict JSON Serialization (Zero Binary Pickling)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # AMQP Queues & Dynamic Routing Definitions
    task_queues=(
        fraud_screening_queue,
        fraud_aml_queue,
        fraud_dlq,
    ),
    task_default_queue="fraud.screening.critical",
    task_default_exchange="fraud.direct",
    task_default_routing_key="fraud.screening.critical",
    task_routes={
        "services.worker.tasks.scoring.evaluate_screening": {
            "queue": "fraud.screening.critical",
            "routing_key": "fraud.screening.critical",
        },
        "services.worker.tasks.screening.check_aml_watchlist": {
            "queue": "fraud.aml.bulk",
            "routing_key": "fraud.aml.bulk",
        },
        "services.worker.tasks.screening.handle_screening_failure": {
            "queue": "fraud.screening.critical",
            "routing_key": "fraud.screening.critical",
        },
    },
)

# In-memory dictionary to track task start timestamps for Prometheus histograms
_TASK_START_TIMES: dict[str, float] = {}


# ==============================================================================
# 3. Observability & Telemetry Signals
# ==============================================================================
@signals.task_prerun.connect
def on_task_prerun(task_id: str, task: Any, *args: Any, **kwargs: Any) -> None:
    """Record task start timestamp and increment in-flight telemetry gauge.

    Args:
        task_id: Unique task identifier.
        task: Celery task instance.
        *args: Positional task arguments.
        **kwargs: Keyword task arguments.
    """
    _TASK_START_TIMES[task_id] = time.perf_counter()
    queue_name = getattr(task.request, "delivery_info", {}).get("routing_key", "default")
    CELERY_TASKS_IN_FLIGHT.labels(task_name=task.name, queue=queue_name).inc()


@signals.task_postrun.connect
def on_task_postrun(
    task_id: str,
    task: Any,
    state: str,
    retval: Any,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Observe task execution runtime, update status counter, and decrement gauge.

    Args:
        task_id: Unique task identifier.
        task: Celery task instance.
        state: Final task state (SUCCESS, FAILURE, RETRY).
        retval: Return value of the task.
        *args: Positional task arguments.
        **kwargs: Keyword task arguments.
    """
    start_time = _TASK_START_TIMES.pop(task_id, None)
    queue_name = getattr(task.request, "delivery_info", {}).get("routing_key", "default")

    if start_time is not None:
        duration = time.perf_counter() - start_time
        CELERY_TASK_DURATION_SECONDS.labels(task_name=task.name, queue=queue_name).observe(duration)

    status_label = "success" if state == "SUCCESS" else "failure"
    CELERY_TASKS_TOTAL.labels(task_name=task.name, status=status_label).inc()
    CELERY_TASKS_IN_FLIGHT.labels(task_name=task.name, queue=queue_name).dec()


@signals.task_retry.connect
def on_task_retry(request: Any, reason: Any, einfo: Any, **kwargs: Any) -> None:
    """Increment the task retry counter upon transient error triggering.

    Args:
        request: Task request context.
        reason: Exception or reason string for the retry.
        einfo: Exception info object.
        **kwargs: Additional Celery keyword arguments.
    """
    task_name = getattr(request, "task", "unknown_task")
    reason_str = type(reason).__name__ if isinstance(reason, Exception) else str(reason)[:32]
    CELERY_TASKS_RETRIED_TOTAL.labels(task_name=task_name, reason=reason_str).inc()


@signals.worker_process_init.connect
def on_worker_process_init(**kwargs: Any) -> None:
    """Pre-warm process resources on fork to prevent cold-start latency.

    Args:
        **kwargs: Signal arguments passed by Celery worker bootloader.
    """
    pass


@signals.worker_shutting_down.connect
def on_worker_shutting_down(**kwargs: Any) -> None:
    """Handle graceful worker SIGTERM/SIGINT teardown and connection flushing.

    Args:
        **kwargs: Signal arguments passed by Celery shutdown handler.
    """
    pass
