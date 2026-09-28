"""Unit tests for Kombu AMQP 0-9-1 topology and Celery configuration invariants (TC-06)."""

from unittest.mock import MagicMock

from services.worker.celery_app import (
    celery_app,
    dlx_exchange,
    fraud_aml_queue,
    fraud_dlq,
    fraud_exchange,
    fraud_screening_queue,
    on_task_postrun,
    on_task_prerun,
    on_task_retry,
    on_worker_process_init,
    on_worker_shutting_down,
)


def test_kombu_exchanges() -> None:
    """TC-06: Verify primary direct exchange and dead-letter exchange (DLX) parameters."""
    assert fraud_exchange.name == "fraud.direct"
    assert fraud_exchange.type == "direct"
    assert fraud_exchange.durable is True

    assert dlx_exchange.name == "fraud.dlx"
    assert dlx_exchange.type == "direct"
    assert dlx_exchange.durable is True


def test_kombu_queues_and_dlx_bindings() -> None:
    """TC-06: Verify critical and bulk queues declare appropriate DLX bindings."""
    assert fraud_screening_queue.name == "fraud.screening.critical"
    assert fraud_screening_queue.exchange.name == "fraud.direct"
    assert fraud_screening_queue.routing_key == "fraud.screening.critical"
    assert fraud_screening_queue.queue_arguments == {
        "x-dead-letter-exchange": "fraud.dlx",
        "x-dead-letter-routing-key": "fraud.screening.dlq",
    }

    assert fraud_aml_queue.name == "fraud.aml.bulk"
    assert fraud_aml_queue.exchange.name == "fraud.direct"
    assert fraud_aml_queue.routing_key == "fraud.aml.bulk"
    assert fraud_aml_queue.queue_arguments == {
        "x-dead-letter-exchange": "fraud.dlx",
        "x-dead-letter-routing-key": "fraud.screening.dlq",
    }

    assert fraud_dlq.name == "fraud.screening.dlq"
    assert fraud_dlq.exchange.name == "fraud.dlx"
    assert fraud_dlq.routing_key == "fraud.screening.dlq"


def test_celery_configuration_invariants() -> None:
    """TC-06: Verify Celery production settings: pooling, prefetch, serialization, acks."""
    conf = celery_app.conf
    assert conf.broker_pool_limit == 10
    assert conf.broker_connection_retry_on_startup is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert "json" in conf.accept_content
    assert conf.result_expires == 3600
    assert conf.timezone == "UTC"
    assert conf.enable_utc is True


def test_celery_task_routes() -> None:
    """TC-06: Verify task routes explicitly target expected AMQP queues."""
    routes = celery_app.conf.task_routes
    assert (
        routes["services.worker.tasks.scoring.evaluate_screening"]["queue"]
        == "fraud.screening.critical"
    )
    assert (
        routes["services.worker.tasks.screening.check_aml_watchlist"]["queue"] == "fraud.aml.bulk"
    )
    assert (
        routes["services.worker.tasks.screening.handle_screening_failure"]["queue"]
        == "fraud.screening.critical"
    )


def test_celery_signals_lifecycle() -> None:
    """Verify Celery task and process lifecycle signal callbacks execute cleanly."""
    mock_task = MagicMock()
    mock_task.name = "test_task"
    mock_task.request.delivery_info = {"routing_key": "fraud.screening.critical"}

    on_task_prerun(task_id="tx_sig_001", task=mock_task)

    on_task_postrun(
        task_id="tx_sig_001",
        task=mock_task,
        state="SUCCESS",
        retval={"status": "ok"},
    )

    on_task_postrun(
        task_id="tx_sig_002",
        task=mock_task,
        state="FAILURE",
        retval=None,
    )

    mock_request = MagicMock()
    mock_request.task = "test_task"
    on_task_retry(request=mock_request, reason=RuntimeError("connection_reset"), einfo=None)
    on_task_retry(request=mock_request, reason="Rate limit reached", einfo=None)

    on_worker_process_init()
    on_worker_shutting_down()
