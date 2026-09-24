"""Global Pytest fixtures and hybrid Testcontainers configuration for 04_scheduling.

Supports hybrid infrastructure: connects to local PostgreSQL/Redis if running,
or automatically spins up ephemeral Testcontainers for integration test runs.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

# Disable Ryuk for socket resilience in container / WSL environments
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
os.environ["ENVIRONMENT"] = "test"

MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from app.config import get_settings
from app.db import get_session_factory, init_db


def _check_tcp_port(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is open and accepting connections.

    Args:
        host: Hostname or IP to inspect.
        port: Port number.
        timeout: Socket connect timeout.

    Returns:
        bool: True if port is reachable, False otherwise.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer | None, None, None]:
    """Launch a PostgreSQL 16 testcontainer if no local PostgreSQL is active."""
    if os.getenv("TEST_DATABASE_URL"):
        yield None
        return
    if _check_tcp_port("localhost", 5432):
        yield None
        return
    try:
        with PostgresContainer("postgres:16-alpine", driver="asyncpg") as container:
            yield container
    except Exception:
        yield None


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer | None, None, None]:
    """Launch a Redis 7 testcontainer if no local Redis is active."""
    if os.getenv("TEST_REDIS_URL") or os.getenv("REDIS_URL"):
        yield None
        return
    if _check_tcp_port("localhost", 6379):
        yield None
        return
    try:
        with RedisContainer("redis:7-alpine") as container:
            yield container
    except Exception:
        yield None


@pytest.fixture(scope="session")
async def test_database_url(postgres_container: PostgresContainer | None) -> str:
    """Initialize database schema via init.sql and return async database URL."""
    if os.getenv("TEST_DATABASE_URL"):
        db_url = os.environ["TEST_DATABASE_URL"]
    elif postgres_container is not None:
        db_url = postgres_container.get_connection_url(driver="asyncpg")
    elif _check_tcp_port("localhost", 5432):
        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/scheduling_db"
    else:
        db_url = "sqlite+aiosqlite:///:memory:"

    # Initialize tables using init.sql
    init_sql_path = MODULE_ROOT / "init.sql"
    if init_sql_path.exists() and "postgresql" in db_url:
        ddl = init_sql_path.read_text(encoding="utf-8")
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                raw_conn = await conn.get_raw_connection()
                assert raw_conn.driver_connection is not None
                await raw_conn.driver_connection.execute(ddl)
        except Exception as exc:
            if "already exists" not in str(exc):
                raise
        await engine.dispose()

    # Override application settings database_url for testing
    settings = get_settings()
    settings.database_url = db_url
    settings.environment = "test"

    # Re-initialize global engine
    init_db(is_worker=False)

    return db_url


@pytest.fixture(scope="session")
def test_redis_url(redis_container: RedisContainer | None) -> str:
    """Return active Redis URL and configure application settings."""
    if os.getenv("TEST_REDIS_URL"):
        redis_url = os.environ["TEST_REDIS_URL"]
    elif os.getenv("REDIS_URL"):
        redis_url = os.environ["REDIS_URL"]
    elif redis_container is not None:
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}/0"
    elif _check_tcp_port("localhost", 6379):
        redis_url = "redis://localhost:6379/0"
    else:
        redis_url = "redis://localhost:6379/0"

    settings = get_settings()
    settings.redis_url = redis_url

    from services.worker.locks import close_redis_client

    close_redis_client()

    return redis_url


@pytest.fixture(autouse=True)
def auto_setup_integration_infrastructure(request: pytest.FixtureRequest) -> None:
    """Automatically wire database and Redis testcontainers for integration tests."""
    if request.node.get_closest_marker("integration"):
        request.getfixturevalue("test_database_url")
        request.getfixturevalue("test_redis_url")


@pytest.fixture
async def db_session(test_database_url: str, test_redis_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated, self-rolling-back AsyncSession for database tests."""
    factory = get_session_factory()

    async with factory() as session:
        try:
            yield session
        finally:
            await session.rollback()
            await session.close()

    # Clean tables between tests
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text("TRUNCATE TABLE idempotency_records, reconciliation_reports, ledger_entries, accounts CASCADE;")
            )
            await session.commit()
        except Exception:
            await session.rollback()


@pytest.fixture
async def api_client(test_database_url: str, test_redis_url: str) -> AsyncGenerator[AsyncClient, None]:
    """Yield an HTTPX AsyncClient bound to the FastAPI application."""
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client
