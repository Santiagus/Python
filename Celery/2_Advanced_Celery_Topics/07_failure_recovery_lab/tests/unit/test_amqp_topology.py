"""Unit tests for Kombu AMQP 0-9-1 topology declaration.

Verifies durable direct exchanges, dead-letter exchanges (DLX), critical settlement
queues, quarantine queues (DLQ), and binding parameters.
"""

from unittest.mock import MagicMock

from shared.amqp_topology import (
    ALL_QUEUES,
    WIRE_CRITICAL_QUEUE_NAME,
    WIRE_DIRECT_EXCHANGE_NAME,
    WIRE_DLQ_QUEUE_NAME,
    WIRE_DLX_EXCHANGE_NAME,
    declare_topology,
    get_task_queues,
    wire_critical_queue,
    wire_direct_exchange,
    wire_dlq_queue,
    wire_dlx_exchange,
)


def test_exchange_specifications() -> None:
    """Verify that primary and dead-letter exchanges conform to AMQP durability standards."""
    # 1. Verify primary direct exchange properties
    assert wire_direct_exchange.name == WIRE_DIRECT_EXCHANGE_NAME
    assert wire_direct_exchange.type == "direct"
    assert wire_direct_exchange.durable is True

    # 2. Verify dead letter exchange properties
    assert wire_dlx_exchange.name == WIRE_DLX_EXCHANGE_NAME
    assert wire_dlx_exchange.type == "direct"
    assert wire_dlx_exchange.durable is True


def test_critical_queue_specifications() -> None:
    """Verify that the critical settlement queue is durable and binds to DLX."""
    # 1. Verify basic queue attributes and exchange binding
    assert wire_critical_queue.name == WIRE_CRITICAL_QUEUE_NAME
    assert wire_critical_queue.exchange == wire_direct_exchange
    assert wire_critical_queue.routing_key == WIRE_CRITICAL_QUEUE_NAME
    assert wire_critical_queue.durable is True

    # 2. Verify Dead Letter Exchange (DLX) routing arguments
    queue_args = wire_critical_queue.queue_arguments or {}
    assert queue_args.get("x-dead-letter-exchange") == WIRE_DLX_EXCHANGE_NAME
    assert queue_args.get("x-dead-letter-routing-key") == WIRE_DLQ_QUEUE_NAME


def test_dlq_specifications() -> None:
    """Verify that the quarantine dead-letter queue is durable and binds to wire.dlx."""
    # 1. Verify quarantine queue attributes
    assert wire_dlq_queue.name == WIRE_DLQ_QUEUE_NAME
    assert wire_dlq_queue.exchange == wire_dlx_exchange
    assert wire_dlq_queue.routing_key == WIRE_DLQ_QUEUE_NAME
    assert wire_dlq_queue.durable is True


def test_get_task_queues() -> None:
    """Verify get_task_queues returns a complete copy of all configured queues."""
    queues = get_task_queues()

    # 1. Check length and membership
    assert len(queues) == 2
    assert wire_critical_queue in queues
    assert wire_dlq_queue in queues

    # 2. Verify list immutability on mutation
    queues.pop()
    assert len(ALL_QUEUES) == 2


def test_declare_topology_on_channel() -> None:
    """Verify declare_topology binds and invokes declare on all exchanges and queues."""
    # 1. Create mock Kombu channel
    mock_channel = MagicMock()

    # 2. Execute topology declaration
    declare_topology(mock_channel)

    # 3. Assert exchange_declare was invoked for exchanges
    assert mock_channel.exchange_declare.call_count >= 2

    # 4. Assert queue_declare was invoked for queues
    assert mock_channel.queue_declare.call_count == 2

    # 5. Assert queue_bind was invoked for both critical and DLQ queues
    assert mock_channel.queue_bind.call_count == 2
