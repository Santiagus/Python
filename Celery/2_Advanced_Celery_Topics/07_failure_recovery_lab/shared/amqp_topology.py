"""Kombu AMQP 0-9-1 topology definitions for the Wire Settlement Gateway.

Declares durable direct exchanges, dead-letter exchanges (DLX), critical settlement
queues, and quarantine queues (DLQ) with strict isolation and retry properties.
"""

from typing import Any

from kombu import Exchange, Queue

# AMQP 0-9-1 Exchange Identifiers
WIRE_DIRECT_EXCHANGE_NAME: str = "wire.direct"
WIRE_DLX_EXCHANGE_NAME: str = "wire.dlx"

# AMQP 0-9-1 Queue Identifiers
WIRE_CRITICAL_QUEUE_NAME: str = "wire.settlement.critical"
WIRE_DLQ_QUEUE_NAME: str = "wire.settlement.dlq"

# 1. Primary Direct Exchange for Inbound Wire Processing
wire_direct_exchange: Exchange = Exchange(
    name=WIRE_DIRECT_EXCHANGE_NAME,
    type="direct",
    durable=True,
)

# 2. Dead Letter Exchange (DLX) for Poison Pill and Failed Wire Quarantining
wire_dlx_exchange: Exchange = Exchange(
    name=WIRE_DLX_EXCHANGE_NAME,
    type="direct",
    durable=True,
)

# 3. High-Priority Durable Queue with Dead-Letter Routing
wire_critical_queue: Queue = Queue(
    name=WIRE_CRITICAL_QUEUE_NAME,
    exchange=wire_direct_exchange,
    routing_key=WIRE_CRITICAL_QUEUE_NAME,
    durable=True,
    queue_arguments={
        "x-dead-letter-exchange": WIRE_DLX_EXCHANGE_NAME,
        "x-dead-letter-routing-key": WIRE_DLQ_QUEUE_NAME,
    },
)

# 4. Dead Letter Queue (DLQ) Bound to DLX
wire_dlq_queue: Queue = Queue(
    name=WIRE_DLQ_QUEUE_NAME,
    exchange=wire_dlx_exchange,
    routing_key=WIRE_DLQ_QUEUE_NAME,
    durable=True,
)

ALL_EXCHANGES: list[Exchange] = [wire_direct_exchange, wire_dlx_exchange]
ALL_QUEUES: list[Queue] = [wire_critical_queue, wire_dlq_queue]


def get_task_queues() -> list[Queue]:
    """Retrieve all declared Kombu queues for Celery configuration.

    Returns:
        list[Queue]: List containing the critical wire settlement queue and DLQ.
    """
    # 1. Return a copy of all defined durable queues
    return list(ALL_QUEUES)


def declare_topology(channel: Any) -> None:
    """Declare all exchanges, queues, and bindings on an AMQP channel.

    Ensures the complete broker topology is created idempotently before task
    publishing or worker consumption begins.

    Args:
        channel: An open Kombu or AMQP channel instance.
    """
    # 1. Declare all direct and dead-letter exchanges
    for exchange in ALL_EXCHANGES:
        bound_exchange = exchange(channel)
        bound_exchange.declare()

    # 2. Declare all queues and establish binding routes
    for queue in ALL_QUEUES:
        bound_queue = queue(channel)
        bound_queue.declare()
