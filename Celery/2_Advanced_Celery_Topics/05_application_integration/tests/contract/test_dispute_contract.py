"""Contract tests validating AMQP topology, Celery task signatures, and Kombu routing contracts."""

from __future__ import annotations

import inspect

from kombu import Exchange, Queue

from services.worker.celery_app import (
    celery_app,
    dead_letter_exchange,
    disputes_exchange,
    task_queues,
    task_routes,
)
from services.worker.tasks.disputes import submit_card_dispute_task


def test_celery_task_registration_contract() -> None:
    """Verify that submit_card_dispute_task is registered under the expected task name."""
    expected_task_name = "services.worker.tasks.disputes.submit_card_dispute_task"
    assert expected_task_name in celery_app.tasks
    assert submit_card_dispute_task.name == expected_task_name


def test_amqp_task_routing_contract() -> None:
    """Verify that submit_card_dispute_task is routed to the designated queue and routing key."""
    expected_task_name = "services.worker.tasks.disputes.submit_card_dispute_task"
    assert expected_task_name in task_routes
    route = task_routes[expected_task_name]
    assert route["queue"] == "card_disputes"
    assert route["routing_key"] == "dispute.card.submit"


def test_kombu_exchanges_contract() -> None:
    """Verify AMQP direct exchanges for primary and dead-letter dispute routing."""
    assert isinstance(disputes_exchange, Exchange)
    assert disputes_exchange.name == "disputes.direct"
    assert disputes_exchange.type == "direct"
    assert disputes_exchange.durable is True

    assert isinstance(dead_letter_exchange, Exchange)
    assert dead_letter_exchange.name == "disputes.dlx"
    assert dead_letter_exchange.type == "direct"
    assert dead_letter_exchange.durable is True


def test_kombu_queues_and_dlx_bindings_contract() -> None:
    """Verify queue topology including dead-letter exchange arguments."""
    queue_map: dict[str, Queue] = {q.name: q for q in task_queues}
    assert "card_disputes" in queue_map
    assert "card_disputes_dlq" in queue_map

    # Primary Queue
    primary_q = queue_map["card_disputes"]
    assert primary_q.routing_key == "dispute.card.submit"
    assert primary_q.exchange.name == "disputes.direct"
    assert primary_q.queue_arguments is not None
    assert primary_q.queue_arguments.get("x-dead-letter-exchange") == "disputes.dlx"
    assert primary_q.queue_arguments.get("x-dead-letter-routing-key") == "dispute.card.dlq"

    # Dead Letter Queue
    dlq = queue_map["card_disputes_dlq"]
    assert dlq.routing_key == "dispute.card.dlq"
    assert dlq.exchange.name == "disputes.dlx"


def test_celery_broker_reliability_invariants_contract() -> None:
    """Verify Celery operational invariants: acks_late, prefetch_multiplier, and broker pooling."""
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.broker_pool_limit == 10
    assert conf.broker_connection_retry_on_startup is True
    assert conf.timezone == "UTC"
    assert conf.enable_utc is True


def test_serialization_security_contract() -> None:
    """Verify strict JSON serialization across brokers to prevent arbitrary code execution."""
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert conf.accept_content == ["json"]


def test_task_signature_primitives_only_contract() -> None:
    """Verify task parameters accept only JSON-serializable primitives (anti-ORM in task args)."""
    sig = inspect.signature(submit_card_dispute_task.run)
    params = sig.parameters

    assert "dispute_id" in params
    assert "simulate_failure" in params

    # Annotations or parameter types must not contain ORM / session types
    for name, param in params.items():
        if param.annotation != inspect.Parameter.empty:
            type_str = str(param.annotation)
            assert "Session" not in type_str
            assert "CardDispute" not in type_str
            assert "AsyncSession" not in type_str
