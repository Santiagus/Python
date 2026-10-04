"""Unit tests for FastAPI ingestion gateway routes, anti-blackhole persistence, and probes."""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app, lifespan
from app.routes.wires import (
    get_db_session,
    get_engine,
    get_session_factory,
)
from shared.models import WireStatus, WireTransfer


@pytest.fixture
def specimen_wire_entity() -> WireTransfer:
    """Create a specimen WireTransfer entity in processing state."""
    now = datetime.now(timezone.utc)
    return WireTransfer(
        wire_id=uuid.uuid4(),
        client_id="CORP-TREASURY-001",
        idempotency_key="idem-99214-alpha",
        amount_cents=250000000,
        currency="USD",
        sender_account_mask="******0001",
        beneficiary_account_mask="******3210",
        routing_number="121000358",
        swift_bic="CHASUS33XXX",
        status=WireStatus.PROCESSING.value,
        delivery_attempts=1,
        redelivered_flag=False,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def valid_ingest_payload() -> dict[str, object]:
    """Create a specimen valid wire creation payload."""
    return {
        "client_id": "CORP-TREASURY-001",
        "amount": "2500000.00",
        "currency": "USD",
        "beneficiary_account": "9876543210",
        "routing_number": "121000358",
        "swift_bic": "CHASUS33XXX",
    }


@pytest.mark.asyncio
async def test_ingest_wire_transfer_happy_path(
    valid_ingest_payload: dict[str, object],
) -> None:
    """Verify wire ingestion returns 202 Accepted, persists status='processing', and dispatches task."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        with patch("app.routes.wires.get_wire_dispatcher") as mock_dispatcher_getter:
            mock_dispatcher = MagicMock()
            mock_dispatcher.dispatch_wire.return_value = "dispatched-task-uuid"
            mock_dispatcher_getter.return_value = mock_dispatcher

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/wires",
                    json=valid_ingest_payload,
                    headers={"Idempotency-Key": "idem-99214-alpha"},
                )

            # 1. Assert status and payload contract
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "processing"
            assert data["client_id"] == "CORP-TREASURY-001"
            assert data["amount_cents"] == 250000000
            assert data["currency"] == "USD"
            assert data["beneficiary_account_mask"] == "******3210"
            assert data["routing_number"] == "121000358"
            assert data["swift_bic"] == "CHASUS33XXX"

            # 2. Assert database insertion
            assert mock_session.add.called
            added_wire = mock_session.add.call_args[0][0]
            assert isinstance(added_wire, WireTransfer)
            assert added_wire.status == "processing"
            assert mock_session.commit.called

            # 3. Assert AMQP dispatch
            assert mock_dispatcher.dispatch_wire.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_wire_transfer_in_flight_visibility(
    specimen_wire_entity: WireTransfer,
) -> None:
    """Verify in-flight visibility: GET /wires/{id} immediately returns 200 OK with status='processing'."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire_entity
    mock_session.execute.return_value = mock_result

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/wires/{specimen_wire_entity.wire_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["wire_id"] == str(specimen_wire_entity.wire_id)
        assert data["status"] == "processing"
        assert data["amount_cents"] == 250000000
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_wire_transfer_atomic_idempotency_duplicate(
    specimen_wire_entity: WireTransfer,
    valid_ingest_payload: dict[str, object],
) -> None:
    """Verify duplicate ingestion catches IntegrityError and returns existing record."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit.side_effect = IntegrityError("Unique violation", params=None, orig=Exception())

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = specimen_wire_entity
    mock_session.execute.return_value = mock_result

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/wires",
                json=valid_ingest_payload,
                headers={"Idempotency-Key": "idem-99214-alpha"},
            )

        assert response.status_code == 202
        data = response.json()
        assert data["wire_id"] == str(specimen_wire_entity.wire_id)
        assert data["client_id"] == specimen_wire_entity.client_id
        assert mock_session.rollback.called
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ingest_wire_transfer_auto_generates_idempotency_key(
    valid_ingest_payload: dict[str, object],
) -> None:
    """Verify omitting Idempotency-Key header auto-generates a unique key."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.commit = AsyncMock()

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        with patch("app.routes.wires.get_wire_dispatcher") as mock_dispatcher_getter:
            mock_dispatcher = MagicMock()
            mock_dispatcher.dispatch_wire.return_value = "dispatched-task-uuid"
            mock_dispatcher_getter.return_value = mock_dispatcher

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/api/v1/wires",
                    json=valid_ingest_payload,
                )

            assert response.status_code == 202
            added_wire = mock_session.add.call_args[0][0]
            assert added_wire.idempotency_key.startswith("idem-")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_wire_transfer_not_found() -> None:
    """Verify requesting a non-existent wire UUID returns 404 Not Found."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        random_uuid = uuid.uuid4()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(f"/api/v1/wires/{random_uuid}")

        assert response.status_code == 404
        assert response.json() == {"detail": f"Wire transfer '{random_uuid}' not found"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_wire_transfers(
    specimen_wire_entity: WireTransfer,
) -> None:
    """Verify listing wire transfers with client_id filter and limit."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [specimen_wire_entity]
    mock_session.execute.return_value = mock_result

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/wires?client_id=CORP-TREASURY-001&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["wire_id"] == str(specimen_wire_entity.wire_id)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_readiness_probe_healthy() -> None:
    """Verify /ready probe returns 200 ready when database ping succeeds."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute.return_value = MagicMock()

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ready", "database": "connected"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_readiness_probe_database_unreachable() -> None:
    """Verify /ready probe returns 503 Service Unavailable when database ping fails."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session.execute.side_effect = ConnectionRefusedError("Database down")

    async def override_get_db_session() -> AsyncGenerator[AsyncSession, None]:
        yield mock_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/ready")

        assert response.status_code == 503
        assert "Database unreachable" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_lifespan_startup_and_shutdown() -> None:
    """Verify application lifespan performs database pre-warm and shutdown dispose."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session_factory.return_value.__aexit__.return_value = None

    mock_engine = AsyncMock()

    with (
        patch("app.main.get_session_factory", return_value=mock_session_factory),
        patch("app.main.get_engine", return_value=mock_engine),
        patch("app.main.get_wire_dispatcher") as mock_dispatcher_getter,
    ):
        mock_dispatcher_getter.return_value = MagicMock()

        async with lifespan(app):
            # Verify startup pre-warm ping was executed
            assert mock_session.execute.called

        # Verify engine dispose was called upon exit
        assert mock_engine.dispose.called


@pytest.mark.asyncio
async def test_get_db_session_dependency() -> None:
    """Verify get_db_session yields an active session from the session factory."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__.return_value = mock_session
    mock_session_factory.return_value.__aexit__.return_value = None

    with patch("app.routes.wires._session_factory", mock_session_factory):
        sessions: list[AsyncSession] = []
        async for s in get_db_session():
            sessions.append(s)

        assert len(sessions) == 1
        assert sessions[0] is mock_session


def test_engine_and_session_factory_accessors() -> None:
    """Verify accessors get_engine and get_session_factory return module instances."""
    assert get_engine() is not None
    assert get_session_factory() is not None
