"""Live distributed multi-process E2E test fixtures and hybrid Testcontainers.

Provisions real PostgreSQL, Redis, RabbitMQ, Celery Worker subprocess, and Sanctions Simulator API.
"""

from __future__ import annotations

import asyncio
import os
import re
import socket
import subprocess
import sys
import time
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer
from testcontainers.core.container import DockerContainer

from app.database import get_session
from app.main import app

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
os.environ["ENVIRONMENT"] = "test"

MODULE_ROOT = Path(__file__).resolve().parent.parent.parent


def _check_tcp_port(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is open and accepting socket connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _get_free_port() -> int:
    """Find and return an ephemeral open TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


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
def rabbitmq_service_url() -> Generator[str, None, None]:
    """Provide RabbitMQ broker URL via environment, local port, or dynamic Testcontainer."""
    if os.getenv("RABBITMQ_URL"):
        yield os.environ["RABBITMQ_URL"]
        return
    if os.getenv("TEST_RABBITMQ_URL"):
        yield os.environ["TEST_RABBITMQ_URL"]
        return
    if _check_tcp_port("localhost", 5672):
        yield "amqp://guest:guest@localhost:5672//"
        return

    import amqp

    try:
        with DockerContainer("rabbitmq:3.13-management-alpine").with_exposed_ports(5672) as rmq_cnt:
            port = rmq_cnt.get_exposed_port(5672)
            ready = False
            for _ in range(30):
                try:
                    conn = amqp.Connection(
                        host=f"localhost:{port}",
                        userid="guest",
                        password="guest",
                        timeout=1,
                    )
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


@pytest.fixture(scope="session")
def test_database_url(postgres_container: PostgresContainer | None) -> str:
    """Initialize database schema via init.sql and return async database URL."""
    if os.getenv("TEST_DATABASE_URL"):
        db_url = os.environ["TEST_DATABASE_URL"]
    elif postgres_container is not None:
        db_url = postgres_container.get_connection_url(driver="asyncpg")
    elif _check_tcp_port("localhost", 5432):
        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/screenings_db"
    else:
        db_url = "sqlite+aiosqlite:///:memory:"

    # Initialize tables using init.sql
    init_sql_path = MODULE_ROOT / "init.sql"
    if init_sql_path.exists() and "postgresql" in db_url:
        ddl = init_sql_path.read_text(encoding="utf-8")
        cleaned_sql = re.sub(r"--.*?\n", "\n", ddl)
        engine = create_async_engine(db_url, poolclass=NullPool)

        async def _init_ddl() -> None:
            async with engine.begin() as conn:
                for statement in cleaned_sql.split(";"):
                    cleaned = statement.strip()
                    if cleaned:
                        await conn.execute(text(cleaned))
            await engine.dispose()

        asyncio.run(_init_ddl())

    return db_url


@pytest.fixture(scope="session")
def test_redis_url(redis_container: RedisContainer | None) -> str:
    """Return Redis service URL string."""
    if os.getenv("TEST_REDIS_URL"):
        return os.environ["TEST_REDIS_URL"]
    if os.getenv("REDIS_URL"):
        return os.environ["REDIS_URL"]
    if redis_container is not None:
        return f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}/0"
    if _check_tcp_port("localhost", 6379):
        return "redis://localhost:6379/0"
    return "redis://localhost:6379/0"


@pytest.fixture(scope="module")
def live_sanctions_api() -> Generator[str, None, None]:
    """Launch the standalone Sanctions Watchlist Simulator API on an ephemeral port."""
    port = _get_free_port()
    base_url = f"http://127.0.0.1:{port}"

    log_file = open("/tmp/live_sanctions_api_06.log", "w")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "services.sanctions_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "info",
        ],
        cwd=str(MODULE_ROOT),
        env={**os.environ, "PYTHONPATH": f"{MODULE_ROOT}:{os.environ.get('PYTHONPATH', '')}"},
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    # Poll /health until server responds HTTP 200
    ready = False
    for _ in range(50):
        try:
            with httpx.Client(timeout=0.5) as client:
                res = client.get(f"{base_url}/health")
                if res.status_code == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.1)

    if not ready:
        proc.kill()
        log_file.close()
        raise RuntimeError("Sanctions API simulator failed to boot within timeout")

    os.environ["SANCTIONS_API_URL"] = base_url

    # Re-wire local process screening client if called directly
    from services.worker.tasks import screening

    orig_client = screening._shared_client
    orig_url = screening._SANCTIONS_API_URL
    screening._SANCTIONS_API_URL = base_url
    screening._shared_client = httpx.Client(
        base_url=base_url,
        limits=screening._HTTP_LIMITS,
        timeout=2.0,
    )

    try:
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()
        screening._SANCTIONS_API_URL = orig_url
        screening._shared_client = orig_client


@pytest.fixture(scope="module")
def live_celery_worker(
    test_database_url: str,
    test_redis_url: str,
    rabbitmq_service_url: str,
    live_sanctions_api: str,
) -> Generator[subprocess.Popen[bytes], None, None]:
    """Launch an isolated Celery worker daemon subprocess for live multi-process E2E testing."""
    from services.worker.celery_app import celery_app

    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    orig_broker = celery_app.conf.broker_url
    orig_backend = celery_app.conf.result_backend

    celery_app.conf.update(
        task_always_eager=False,
        task_eager_propagates=False,
        broker_url=rabbitmq_service_url,
        result_backend=test_redis_url,
    )

    # Re-wire main app database and settings for live dispatcher
    from app.config import settings

    settings.database_url = test_database_url
    settings.celery_broker_url = rabbitmq_service_url
    settings.celery_result_backend = test_redis_url

    worker_env = {
        **os.environ,
        "PYTHONPATH": f"{MODULE_ROOT}:{os.environ.get('PYTHONPATH', '')}",
        "DATABASE_URL": test_database_url,
        "CELERY_BROKER_URL": rabbitmq_service_url,
        "CELERY_RESULT_BACKEND": test_redis_url,
        "SANCTIONS_API_URL": live_sanctions_api,
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "INFO",
    }

    log_file = open("/tmp/live_celery_worker_06.log", "w")
    worker_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "services.worker.celery_app:celery_app",
            "worker",
            "-P",
            "solo",
            "--loglevel=INFO",
            "-Q",
            "fraud.screening.critical,fraud.aml.bulk",
        ],
        cwd=str(MODULE_ROOT),
        env=worker_env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    # Pre-declare and purge queues on RabbitMQ broker
    try:
        with celery_app.connection_or_acquire() as conn:
            for q in celery_app.conf.task_queues:
                bound = q(conn.default_channel)
                bound.declare()
                bound.purge()
    except Exception:
        pass

    time.sleep(2.5)

    try:
        yield worker_proc
    finally:
        worker_proc.terminate()
        try:
            worker_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker_proc.kill()
        log_file.close()

        celery_app.conf.update(
            task_always_eager=orig_eager,
            task_eager_propagates=orig_prop,
            broker_url=orig_broker,
            result_backend=orig_backend,
        )


@pytest_asyncio.fixture
async def e2e_engine(test_database_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """Provide a dedicated test AsyncEngine with NullPool."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def e2e_session_factory(
    e2e_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return async sessionmaker bound to test engine."""
    return async_sessionmaker(
        bind=e2e_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def e2e_db_session(
    e2e_engine: AsyncEngine,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide isolated database session per test and truncate tables cleanly afterwards."""
    async with e2e_session_factory() as session:
        yield session

    async with e2e_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE watchlist_hits, operational_events, screenings "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest_asyncio.fixture
async def live_async_client(
    e2e_db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Provide test HTTP client targeting the FastAPI application."""

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield e2e_db_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
