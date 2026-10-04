"""Pytest fixtures for integration tests and failure recovery suites.

Provides hybrid testcontainer connections, in-memory AMQP broker topologies,
stateful bank simulator mocks, and isolated async database sessions.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from kombu import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from shared.amqp_topology import declare_topology
from shared.models import WireStatus, WireTransfer

# Disable Ryuk for socket resilience in container/WSL2 environments
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture
def sample_wire_payload() -> dict[str, Any]:
    """Provide a specimen valid WireTaskPayload dictionary."""
    return {
        "wire_id": str(uuid.uuid4()),
        "client_id": "INTEG-CORP-001",
        "idempotency_key": f"integ-idem-{uuid.uuid4().hex[:8]}",
        "amount_cents": 15000000,  # $150,000.00
        "currency": "USD",
        "sender_account_mask": "******1234",
        "beneficiary_account_mask": "******4321",
        "routing_number": "121000358",
        "swift_bic": "CHASUS33",
        "disbursement_token": f"tok_{uuid.uuid4().hex[:16]}",
    }


@pytest.fixture
def sample_wire_transfer(sample_wire_payload: dict[str, Any]) -> WireTransfer:
    """Create a WireTransfer model instance initialized to in-flight processing status."""
    return WireTransfer(
        wire_id=uuid.UUID(sample_wire_payload["wire_id"]),
        client_id=sample_wire_payload["client_id"],
        idempotency_key=sample_wire_payload["idempotency_key"],
        amount_cents=sample_wire_payload["amount_cents"],
        currency=sample_wire_payload["currency"],
        sender_account_mask="******1234",
        beneficiary_account_mask=sample_wire_payload["beneficiary_account_mask"],
        routing_number=sample_wire_payload["routing_number"],
        swift_bic=sample_wire_payload["swift_bic"],
        status=WireStatus.PROCESSING.value,
        delivery_attempts=1,
        redelivered_flag=False,
    )


@pytest.fixture
def mock_db_session(sample_wire_transfer: WireTransfer) -> AsyncMock:
    """Provide a mock AsyncSession that tracks persistence and row locks."""
    session = AsyncMock(spec=AsyncSession)
    added_items: list[Any] = []

    def fake_add(item: Any) -> None:
        added_items.append(item)

    def fake_add_all(items: list[Any]) -> None:
        added_items.extend(items)

    session.add.side_effect = fake_add
    session.add_all.side_effect = fake_add_all

    # Mock execute returning the sample wire transfer
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = sample_wire_transfer
    session.execute.return_value = mock_result

    return session


@pytest.fixture
def stateful_bank_simulator() -> AsyncMock:
    """Provide a stateful bank simulator client tracking disbursements by idempotency key."""
    client = AsyncMock(spec=httpx.AsyncClient)
    cleared_wires: dict[str, dict[str, Any]] = {}

    async def fake_get(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        key = url.split("/")[-1]
        if key in cleared_wires:
            return httpx.Response(200, json=cleared_wires[key])
        return httpx.Response(404, json={"detail": "Wire transfer not found"})

    async def fake_post(url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        data = kwargs.get("json", {})
        key = data.get("idempotency_key", f"bank-{uuid.uuid4().hex[:6]}")
        if key in cleared_wires:
            return httpx.Response(200, json=cleared_wires[key])
        record = {
            "bank_reference_id": f"FED-WIRE-{uuid.uuid4().hex[:8].upper()}",
            "amount_cents": data.get("amount_cents", 0),
            "currency": data.get("currency", "USD"),
            "status": "settled",
            "settled_at": "2026-10-04T12:00:00Z",
        }
        cleared_wires[key] = record
        return httpx.Response(200, json=record)

    client.get.side_effect = fake_get
    client.post.side_effect = fake_post
    client.cleared_wires = cleared_wires  # type: ignore[attr-defined]

    return client


@pytest.fixture
def amqp_memory_connection() -> Generator[Connection, None, None]:
    """Provide an in-memory Kombu connection with declared topology."""
    conn = Connection("memory://")
    channel = conn.channel()
    declare_topology(channel)
    yield conn
    conn.close()
