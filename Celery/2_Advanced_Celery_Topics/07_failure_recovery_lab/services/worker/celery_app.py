"""Celery application configuration for the distributed wire settlement worker.

Configures late acknowledgements (acks_late=True), worker lost rejections,
prefetch constraints, Kombu AMQP 0-9-1 durable queue topologies, and broker connection pooling.
"""

import os

from celery import Celery, signals

from shared.amqp_topology import (
    WIRE_CRITICAL_QUEUE_NAME,
    WIRE_DIRECT_EXCHANGE_NAME,
    get_task_queues,
)

# 1. Resolve environment broker configuration
BROKER_URL: str = os.getenv(
    "CELERY_BROKER_URL",
    "amqp://guest:guest@localhost:5672//",
)

# 2. Instantiate Celery application
celery_app: Celery = Celery(
    "wire_settlement_worker",
    broker=BROKER_URL,
    include=[
        "services.worker.tasks.settlement",
        "services.worker.tasks.audit",
    ],
)

# 3. Configure strict financial failure recovery invariants
celery_app.conf.update(
    # Message serialization discipline
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # High-Performance Kombu AMQP Broker Pooling
    broker_pool_limit=10,
    broker_connection_retry_on_startup=True,
    # Strict Financial Failure Recovery Invariants
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Durable Hybrid Queue Topology
    task_queues=get_task_queues(),
    task_default_exchange=WIRE_DIRECT_EXCHANGE_NAME,
    task_default_exchange_type="direct",
    task_default_routing_key=WIRE_CRITICAL_QUEUE_NAME,
    task_default_queue=WIRE_CRITICAL_QUEUE_NAME,
)


@signals.worker_process_init.connect
def on_worker_process_init(**kwargs: object) -> None:
    """Re-initialize event loop and connection pools on worker child process fork."""
    from services.worker.tasks.audit import reset_process_singletons as reset_audit
    from services.worker.tasks.settlement import (
        reset_process_singletons as reset_settlement,
    )

    reset_settlement()
    reset_audit()
