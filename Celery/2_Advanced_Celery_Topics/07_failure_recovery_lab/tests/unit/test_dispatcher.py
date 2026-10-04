"""Unit tests for Kombu AMQP wire dispatcher with publisher confirms."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from kombu import Connection, Queue

from app.dispatcher import (
    SETTLEMENT_TASK_NAME,
    WireDispatcher,
    get_wire_dispatcher,
    set_wire_dispatcher,
)
from app.middlewares.correlation import current_request_id
from shared.amqp_topology import (
    WIRE_CRITICAL_QUEUE_NAME,
    wire_direct_exchange,
)
from shared.schemas import WireTaskPayload


def test_dispatcher_initialization_defaults_and_options() -> None:
    """Verify default and customized initialization of WireDispatcher."""
    # 1. Default initialization
    d1 = WireDispatcher()
    assert d1.confirm_delivery is True
    assert d1.exchange == wire_direct_exchange
    assert d1.routing_key == WIRE_CRITICAL_QUEUE_NAME
    assert isinstance(d1.connection, Connection)

    # 2. Custom initialization with disabled confirms
    custom_conn = Connection("memory://")
    d2 = WireDispatcher(
        broker_url="memory://custom",
        confirm_delivery=False,
        connection=custom_conn,
        routing_key="custom.key",
    )
    assert d2.confirm_delivery is False
    assert d2.connection is custom_conn
    assert d2.routing_key == "custom.key"


def test_dispatcher_dispatch_with_wire_task_payload() -> None:
    """Verify dispatching a WireTaskPayload instance to an in-memory AMQP broker."""
    conn = Connection("memory://", transport_options={"confirm_publish": True})
    ch = conn.channel()

    queue = Queue(WIRE_CRITICAL_QUEUE_NAME, exchange=wire_direct_exchange, routing_key=WIRE_CRITICAL_QUEUE_NAME)
    queue(ch).declare()

    dispatcher = WireDispatcher(connection=conn)

    payload = WireTaskPayload(
        wire_id="11111111-2222-3333-4444-555555555555",
        client_id="CORP-CLIENT-001",
        idempotency_key="idem-key-99214",
        amount_cents=5000000,
        currency="USD",
        sender_account_mask="******1001",
        beneficiary_account_mask="******9999",
        routing_number="121000358",
        swift_bic="CHASUS33XXX",
        disbursement_token="tok_abc123xyz456",
    )

    task_id = dispatcher.dispatch_wire(payload, correlation_id="CORREL-8899")

    # 1. Assert task_id is returned
    assert task_id is not None
    uuid.UUID(task_id)

    # 2. Consume message from queue and verify Celery v2 contract
    msg = queue(ch).get()
    assert msg is not None
    decoded = msg.decode()
    assert isinstance(decoded, list)
    body_args, _body_kwargs, _body_embed = decoded
    assert body_args[0]["wire_id"] == "11111111-2222-3333-4444-555555555555"
    assert body_args[0]["amount_cents"] == 5000000

    # 3. Verify message headers and delivery mode
    headers = msg.headers
    assert headers["task"] == SETTLEMENT_TASK_NAME
    assert headers["id"] == task_id
    assert headers["correlation_id"] == "CORREL-8899"
    assert headers["X-Request-ID"] == "CORREL-8899"
    assert msg.properties["delivery_mode"] == 2


def test_dispatcher_dispatch_with_dict_and_explicit_task_id() -> None:
    """Verify dispatching a raw dictionary with pre-assigned task ID."""
    conn = Connection("memory://")
    ch = conn.channel()

    queue = Queue(WIRE_CRITICAL_QUEUE_NAME, exchange=wire_direct_exchange, routing_key=WIRE_CRITICAL_QUEUE_NAME)
    queue(ch).declare()

    dispatcher = WireDispatcher(connection=conn)
    raw_dict = {"wire_id": "test-uuid-raw", "client_id": "RAW-CLIENT"}
    explicit_tid = "custom-task-uuid-007"

    returned_tid = dispatcher.dispatch_wire(
        raw_dict,
        correlation_id="EXPLICIT-REQ",
        task_id=explicit_tid,
    )

    assert returned_tid == explicit_tid

    msg = queue(ch).get()
    assert msg is not None
    assert msg.headers["id"] == explicit_tid
    assert msg.headers["correlation_id"] == "EXPLICIT-REQ"


def test_dispatcher_inherits_contextvar_correlation_id() -> None:
    """Verify correlation ID inheritance from active ContextVar."""
    conn = Connection("memory://")
    ch = conn.channel()

    queue = Queue(WIRE_CRITICAL_QUEUE_NAME, exchange=wire_direct_exchange, routing_key=WIRE_CRITICAL_QUEUE_NAME)
    queue(ch).declare()

    dispatcher = WireDispatcher(connection=conn)

    token = current_request_id.set("CTX-REQ-9988")
    try:
        dispatcher.dispatch_wire({"sample": "data"})
    finally:
        current_request_id.reset(token)

    msg = queue(ch).get()
    assert msg is not None
    assert msg.headers["correlation_id"] == "CTX-REQ-9988"
    assert msg.headers["X-Request-ID"] == "CTX-REQ-9988"


def test_dispatcher_generates_correlation_id_when_no_context() -> None:
    """Verify fallback 8-character correlation ID generation when ContextVar is unset."""
    conn = Connection("memory://")
    ch = conn.channel()

    queue = Queue(WIRE_CRITICAL_QUEUE_NAME, exchange=wire_direct_exchange, routing_key=WIRE_CRITICAL_QUEUE_NAME)
    queue(ch).declare()

    dispatcher = WireDispatcher(connection=conn)

    # Ensure context is empty
    token = current_request_id.set(None)
    try:
        dispatcher.dispatch_wire({"sample": "data"})
    finally:
        current_request_id.reset(token)

    msg = queue(ch).get()
    assert msg is not None
    correl = msg.headers["correlation_id"]
    assert correl is not None
    assert len(correl) == 8


def test_dispatcher_raises_runtime_error_on_broker_failure() -> None:
    """Verify that AMQP publishing failures raise RuntimeError."""
    mock_conn = MagicMock()
    dispatcher = WireDispatcher(connection=mock_conn)

    with patch("app.dispatcher.producers") as mock_producers:
        mock_producer_cm = MagicMock()
        mock_producer_cm.__enter__.side_effect = ConnectionRefusedError("RabbitMQ broker unreachable")
        mock_producers.__getitem__.return_value.acquire.return_value = mock_producer_cm

        with pytest.raises(RuntimeError, match="Failed to dispatch wire task to broker"):
            dispatcher.dispatch_wire({"sample": "data"})


def test_get_and_set_wire_dispatcher_singleton() -> None:
    """Verify access and override of process-level dispatcher singleton."""
    original = get_wire_dispatcher()
    assert isinstance(original, WireDispatcher)

    dummy_conn = Connection("memory://dummy")
    custom_dispatcher = WireDispatcher(connection=dummy_conn)

    set_wire_dispatcher(custom_dispatcher)
    assert get_wire_dispatcher() is custom_dispatcher

    # Restore original dispatcher
    set_wire_dispatcher(original)
    assert get_wire_dispatcher() is original
