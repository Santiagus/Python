"""Integration tests for container health probes and readiness checks (TC-17, TC-18)."""

from unittest.mock import AsyncMock, MagicMock, patch

import app.database
import httpx
import pytest
from app.database import close_database_pool, warm_database_pool


@pytest.mark.asyncio
async def test_liveness_probe(client: httpx.AsyncClient) -> None:
    """TC-17: Liveness probe returns HTTP 200 without polling external databases."""
    res = await client.get("/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_readiness_probe_healthy(client: httpx.AsyncClient) -> None:
    """TC-18: Readiness probe returns HTTP 200 when all backing services are reachable."""
    with (
        patch("redis.asyncio.from_url") as mock_redis_cls,
        patch("services.worker.celery_app.celery_app.connection_for_read") as mock_conn,
    ):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        mock_redis_cls.return_value = mock_redis

        mock_amqp = MagicMock()
        mock_amqp.__enter__.return_value = mock_amqp
        mock_conn.return_value = mock_amqp

        res = await client.get("/health/ready")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert data["redis"] == "connected"
        assert data["rabbitmq"] == "connected"


@pytest.mark.asyncio
async def test_readiness_probe_unhealthy_dependency(client: httpx.AsyncClient) -> None:
    """Verify readiness probe returns HTTP 503 when a subsystem dependency is unavailable."""
    with (
        patch("redis.asyncio.from_url") as mock_redis_cls,
        patch("services.worker.celery_app.celery_app.connection_for_read") as mock_conn,
    ):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis cluster unreachable"))
        mock_redis_cls.return_value = mock_redis

        mock_amqp = MagicMock()
        mock_amqp.__enter__.return_value = mock_amqp
        mock_conn.return_value = mock_amqp

        res = await client.get("/health/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "unhealthy"
        assert "Redis cluster unreachable" in data["redis"]


@pytest.mark.asyncio
async def test_database_pool_warmup_and_close() -> None:
    """Verify warm_database_pool and close_database_pool execution."""
    mock_engine = MagicMock()
    mock_conn = AsyncMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn
    mock_engine.dispose = AsyncMock()

    with patch.object(app.database, "engine", mock_engine):
        success = await warm_database_pool()
        assert success is True

        mock_engine.connect.side_effect = RuntimeError("Connection timeout")
        failure = await warm_database_pool()
        assert failure is False

        await close_database_pool()
        mock_engine.dispose.assert_called_once()


@pytest.mark.asyncio
async def test_get_session_dependency() -> None:
    """Verify get_session yields session and handles commit/rollback lifecycle."""
    from app.database import get_session

    gen1 = get_session()
    s1 = await anext(gen1)
    assert s1 is not None
    await gen1.aclose()

    gen2 = get_session()
    s2 = await anext(gen2)
    assert s2 is not None
    with pytest.raises(RuntimeError):
        await gen2.athrow(RuntimeError("Test error inside session"))


@pytest.mark.asyncio
async def test_lifespan_context() -> None:
    """Verify application lifespan startup warmup and shutdown disposal."""
    from app.main import app, lifespan

    with (
        patch("app.main.warm_database_pool", new_callable=AsyncMock) as mock_warm,
        patch("app.main.close_database_pool", new_callable=AsyncMock) as mock_close,
    ):
        async with lifespan(app):
            mock_warm.assert_called_once()
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_readiness_probe_database_error(client: httpx.AsyncClient) -> None:
    """Verify readiness probe returns 503 when database execution raises."""
    with (
        patch(
            "sqlalchemy.ext.asyncio.AsyncSession.execute",
            side_effect=RuntimeError("DB query failed"),
        ),
        patch("redis.asyncio.from_url") as mock_redis_cls,
        patch("services.worker.celery_app.celery_app.connection_for_read") as mock_conn,
    ):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        mock_redis_cls.return_value = mock_redis

        mock_amqp = MagicMock()
        mock_amqp.__enter__.return_value = mock_amqp
        mock_conn.return_value = mock_amqp

        res = await client.get("/health/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "unhealthy"
        assert "DB query failed" in data["database"]


@pytest.mark.asyncio
async def test_readiness_probe_broker_error(client: httpx.AsyncClient) -> None:
    """Verify readiness probe returns 503 when broker connection fails."""
    with (
        patch("redis.asyncio.from_url") as mock_redis_cls,
        patch(
            "services.worker.celery_app.celery_app.connection_for_read",
            side_effect=RuntimeError("RabbitMQ unreachable"),
        ),
    ):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        mock_redis_cls.return_value = mock_redis

        res = await client.get("/health/ready")
        assert res.status_code == 503
        data = res.json()
        assert data["status"] == "unhealthy"
        assert "RabbitMQ unreachable" in data["rabbitmq"]
