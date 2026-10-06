"""Unit tests for Celery worker application configuration and failure recovery settings."""

from unittest.mock import patch

from services.worker.celery_app import celery_app, on_worker_process_init
from shared.amqp_topology import (
    WIRE_CRITICAL_QUEUE_NAME,
    WIRE_DIRECT_EXCHANGE_NAME,
)


def test_celery_app_instance() -> None:
    """Verify Celery app name and basic properties."""
    assert celery_app.main == "wire_settlement_worker"


def test_celery_failure_recovery_invariants() -> None:
    """Verify Celery task configuration preserves strict financial invariants."""
    conf = celery_app.conf

    # 1. Late acknowledgements (prevent message loss on crash)
    assert conf.task_acks_late is True

    # 2. Worker lost rejection (forces AMQP broker redelivery on SIGKILL)
    assert conf.task_reject_on_worker_lost is True

    # 3. Fair dispatch prefetch count
    assert conf.worker_prefetch_multiplier == 1

    # 4. Kombu AMQP broker connection pooling
    assert conf.broker_pool_limit == 10
    assert conf.broker_connection_retry_on_startup is True


def test_celery_queue_topology_binding() -> None:
    """Verify Celery task queues and routing defaults bind to wire settlement exchange."""
    conf = celery_app.conf

    # 1. Default exchange, routing key, and queue
    assert conf.task_default_exchange == WIRE_DIRECT_EXCHANGE_NAME
    assert conf.task_default_exchange_type == "direct"
    assert conf.task_default_routing_key == WIRE_CRITICAL_QUEUE_NAME
    assert conf.task_default_queue == WIRE_CRITICAL_QUEUE_NAME

    # 2. Configured task queues
    queue_names = [q.name for q in conf.task_queues]
    assert "wire.settlement.critical" in queue_names
    assert "wire.settlement.dlq" in queue_names


def test_worker_process_init_signal() -> None:
    """Verify on_worker_process_init signal listener resets process singletons."""
    with (
        patch("services.worker.tasks.settlement.reset_process_singletons") as mock_settle,
        patch("services.worker.tasks.audit.reset_process_singletons") as mock_audit,
    ):
        on_worker_process_init()
        assert mock_settle.called
        assert mock_audit.called
