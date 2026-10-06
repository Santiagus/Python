"""Kombu AMQP 0-9-1 task dispatcher with publisher confirms and persistent delivery.

Publishes wire settlement workflows to RabbitMQ using durable exchanges,
persistent messages (delivery_mode=2), publisher confirms (confirm_delivery=True),
and correlation ID propagation. Decoupled from the worker fleet to preserve service isolation.
"""

import os
import uuid
from typing import Any

from kombu import Connection, Exchange
from kombu.pools import producers

from app.middlewares.correlation import get_current_request_id
from shared.amqp_topology import (
    WIRE_CRITICAL_QUEUE_NAME,
    wire_direct_exchange,
)
from shared.schemas import WireTaskPayload

SETTLEMENT_TASK_NAME: str = "services.worker.tasks.settlement.settle_wire_transfer"
DEFAULT_BROKER_URL: str = os.getenv(
    "CELERY_BROKER_URL",
    "amqp://guest:guest@localhost:5672//",
)


class WireDispatcher:
    """Reliable AMQP publisher for wire settlement workflows with publisher confirms."""

    def __init__(
        self,
        broker_url: str | None = None,
        confirm_delivery: bool = True,
        connection: Connection | None = None,
        exchange: Exchange | None = None,
        routing_key: str = WIRE_CRITICAL_QUEUE_NAME,
    ) -> None:
        """Initialize WireDispatcher with broker connection and publisher confirms.

        Args:
            broker_url: Optional AMQP connection URL string.
            confirm_delivery: Whether to enforce broker publisher confirms.
            connection: Optional pre-configured Kombu connection instance.
            exchange: Kombu exchange to publish to (defaults to wire_direct_exchange).
            routing_key: AMQP routing key for critical settlement queue.
        """
        # 1. Store configuration parameters
        self.broker_url = broker_url or DEFAULT_BROKER_URL
        self.confirm_delivery = confirm_delivery
        self.exchange = exchange or wire_direct_exchange
        self.routing_key = routing_key

        # 2. Configure connection with publisher confirms if requested
        transport_options = {"confirm_publish": True} if confirm_delivery else {}
        self._connection = connection or Connection(
            self.broker_url,
            transport_options=transport_options,
        )

    @property
    def connection(self) -> Connection:
        """Retrieve the underlying Kombu connection instance."""
        return self._connection

    def dispatch_wire(
        self,
        task_payload: WireTaskPayload | dict[str, Any],
        correlation_id: str | None = None,
        task_id: str | None = None,
    ) -> str:
        """Publish wire settlement task with persistent delivery and publisher confirms.

        Formats the payload into a Celery v2 protocol task message and publishes
        it via Kombu connection pool with publisher confirmation.

        Args:
            task_payload: WireTaskPayload schema or dictionary.
            correlation_id: Optional correlation ID (falls back to active ContextVar or new 8-char hex).
            task_id: Optional UUID string for the task (generates new UUID4 if omitted).

        Returns:
            str: Dispatched Celery task ID.

        Raises:
            RuntimeError: If broker publisher confirmation fails or connection drops.
        """
        # 1. Standardize payload dictionary
        payload_dict = task_payload.model_dump() if isinstance(task_payload, WireTaskPayload) else dict(task_payload)

        # 2. Resolve correlation and task identifiers
        active_correl_id = correlation_id or get_current_request_id() or uuid.uuid4().hex[:8]
        tid = task_id or str(uuid.uuid4())

        # 3. Format message according to Celery v2 task protocol
        body: tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]] = (
            [payload_dict],
            {},
            {"callbacks": None, "errbacks": None, "chain": None, "chord": None},
        )
        headers: dict[str, Any] = {
            "lang": "py",
            "task": SETTLEMENT_TASK_NAME,
            "id": tid,
            "root_id": tid,
            "parent_id": None,
            "group": None,
            "correlation_id": active_correl_id,
            "X-Request-ID": active_correl_id,
            "retries": 0,
            "eta": None,
            "expires": None,
            "timelimit": [None, None],
            "argsrepr": f"[{payload_dict!r}]",
            "kwargsrepr": "{}",
        }

        # 4. Acquire pooled Kombu producer and publish with publisher confirms
        try:
            with producers[self._connection].acquire(block=True) as producer:
                producer.publish(
                    body=body,
                    exchange=self.exchange,
                    routing_key=self.routing_key,
                    serializer="json",
                    headers=headers,
                    delivery_mode=2,
                    correlation_id=active_correl_id,
                    retry=True,
                    retry_policy={
                        "max_retries": 3,
                        "interval_start": 0.2,
                        "interval_step": 0.2,
                        "interval_max": 1.0,
                    },
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to dispatch wire task to broker: {exc}") from exc

        return tid


# 5. Eager singleton initialization at module load
_shared_dispatcher: WireDispatcher = WireDispatcher()


def get_wire_dispatcher() -> WireDispatcher:
    """Retrieve the shared process-level WireDispatcher singleton.

    Returns:
        WireDispatcher: Active process-level dispatcher.
    """
    return _shared_dispatcher


def set_wire_dispatcher(dispatcher: WireDispatcher) -> None:
    """Override process-level WireDispatcher singleton.

    Args:
        dispatcher: Replacement WireDispatcher instance.
    """
    global _shared_dispatcher
    _shared_dispatcher = dispatcher
