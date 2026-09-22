"""Global Pytest fixtures and hybrid Testcontainers configuration.

Supports hybrid infrastructure: connects to local services if running,
or automatically spins up ephemeral PostgreSQL / RabbitMQ testcontainers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
import os
from pathlib import Path
import socket
import sys
from uuid import UUID

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

# Disable Ryuk for socket resilience in container / WSL environments
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
os.environ["ENVIRONMENT"] = "test"

MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from app.config import Settings, get_settings
from app.db import get_engine, get_session_factory
from app.dependencies import get_db
from app.main import create_app
from app.models import Account
from services.worker.celery_app import celery_app


def _check_tcp_port(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is open and accepting connections."""
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
async def test_database_url(postgres_container: PostgresContainer | None) -> str:
    """Initialize database schema via init.sql and return async database URL."""
    if os.getenv("TEST_DATABASE_URL"):
        db_url = os.environ["TEST_DATABASE_URL"]
    elif postgres_container is not None:
        db_url = postgres_container.get_connection_url(driver="asyncpg")
    elif _check_tcp_port("localhost", 5432):
        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/payments_db"
    else:
        db_url = "sqlite+aiosqlite:///:memory:"

    # Initialize tables using init.sql
    init_sql_path = MODULE_ROOT / "init.sql"
    if init_sql_path.exists() and "postgresql" in db_url:
        with open(init_sql_path) as f:
            ddl = f.read()
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                raw_conn = await conn.get_raw_connection()
                await raw_conn.driver_connection.execute(ddl)
        except Exception as exc:
            if "already exists" not in str(exc):
                raise
        await engine.dispose()

    # Override application settings database_url for testing
    settings = get_settings()
    settings.database_url = db_url
    settings.environment = "test"

    # Reset global engine in app.db to pick up test database URL
    import app.db as app_db
    if app_db._engine is not None:
        await app_db._engine.dispose()
        app_db._engine = None
        app_db._session_factory = None

    return db_url


@pytest.fixture
async def db_session(test_database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated transactional async database session with clean state per test."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # 1. Ensure seed accounts exist before running test
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                INSERT INTO accounts (account_id, account_number, account_mask, balance_cents, currency)
                VALUES
                    ('a0000000-0000-0000-0000-000000000001', '1000112233445501', '******5501', 1000000000, 'USD'),
                    ('a0000000-0000-0000-0000-000000000002', '2000223344556602', '******6602', 500000000, 'USD'),
                    ('a0000000-0000-0000-0000-000000000003', '3000334455667703', '******7703', 10000000, 'USD'),
                    ('a0000000-0000-0000-0000-000000000004', '4000445566778804', '******8804', 5000, 'USD')
                ON CONFLICT (account_id) DO UPDATE SET balance_cents = EXCLUDED.balance_cents;
            """)
        )

    async with session_factory() as session:
        yield session

    # 2. Truncate payments and disbursements between tests, reset account balances individually
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE disbursements, batch_settlements, payments CASCADE;"))
        reset_queries = [
            "UPDATE accounts SET balance_cents = 1000000000 WHERE account_id = 'a0000000-0000-0000-0000-000000000001'",
            "UPDATE accounts SET balance_cents = 500000000 WHERE account_id = 'a0000000-0000-0000-0000-000000000002'",
            "UPDATE accounts SET balance_cents = 10000000 WHERE account_id = 'a0000000-0000-0000-0000-000000000003'",
            "UPDATE accounts SET balance_cents = 5000 WHERE account_id = 'a0000000-0000-0000-0000-000000000004'",
        ]
        for q in reset_queries:
            await conn.execute(text(q))

    await engine.dispose()


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Standard authenticated headers for API gateway requests."""
    return {
        "X-API-Key": "sk_live_payment_orchestrator_secret_key_2026",
        "Content-Type": "application/json",
    }


@pytest.fixture
async def async_client(test_database_url: str, db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTP test client using Starlette ASGITransport with shared db_session."""
    test_app = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    test_app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def eager_celery():
    """Configure Celery to execute tasks eagerly (in-memory) for deterministic testing."""
    original_eager = celery_app.conf.task_always_eager
    original_propagate = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield celery_app
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.task_eager_propagates = original_propagate


@pytest.fixture(scope="session")
def rabbitmq_service_url() -> Generator[str, None, None]:
    """Provide RabbitMQ broker URL via existing environment, local port, or dynamic Testcontainer."""
    if os.getenv("RABBITMQ_URL"):
        yield os.environ["RABBITMQ_URL"]
        return
    if os.getenv("TEST_RABBITMQ_URL"):
        yield os.environ["TEST_RABBITMQ_URL"]
        return
    if _check_tcp_port("localhost", 5672):
        yield "amqp://guest:guest@localhost:5672//"
        return

    from testcontainers.core.container import DockerContainer
    import amqp
    import time

    try:
        with DockerContainer("rabbitmq:3.13-management-alpine").with_exposed_ports(5672) as rmq_cnt:
            port = rmq_cnt.get_exposed_port(5672)
            ready = False
            for _ in range(30):
                try:
                    conn = amqp.Connection(host=f"localhost:{port}", userid="guest", password="guest", timeout=1)
                    conn.connect()
                    conn.close()
                    ready = True
                    break
                except Exception:
                    time.sleep(1)
            if not ready:
                pytest.skip("RabbitMQ Testcontainer timed out waiting for AMQP readiness")
            yield f"amqp://guest:guest@localhost:{port}//"
    except Exception as exc:
        pytest.skip(f"RabbitMQ not available locally and Testcontainer failed: {exc}")

