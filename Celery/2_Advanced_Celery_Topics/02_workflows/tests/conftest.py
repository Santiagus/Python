"""Pytest fixtures and configuration for Module 02 test suite."""

import os
import sys
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

# Disable Ryuk for socket resilience in container/WSL2 environments
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# Ensure 02_workflows root is in sys.path
MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from app.config import Settings
from app.db import Database, get_database, get_session
from app.main import create_app


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Return the absolute path to the tests/fixtures directory."""
    p = MODULE_ROOT / "tests" / "fixtures"
    assert p.exists(), f"Fixtures directory not found at {p}"
    return p


@pytest.fixture
def clean_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the happy path 4-page clean dossier."""
    clean_dir = fixtures_dir / "clean_4pages"
    return {
        "bank_statement": str(clean_dir / "bank_statement_4pages.pdf"),
        "kyc_id": str(clean_dir / "kyc_executive_id.jpg"),
        "tax_filing": str(clean_dir / "tax_filing_irs1120.pdf"),
    }


@pytest.fixture
def degraded_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the degraded statement dossier (Page 2 OCR noise)."""
    return {
        "bank_statement": str(fixtures_dir / "degraded_page2" / "bank_statement_degraded.pdf"),
        "kyc_id": str(fixtures_dir / "clean_4pages" / "kyc_executive_id.jpg"),
        "tax_filing": str(fixtures_dir / "clean_4pages" / "tax_filing_irs1120.pdf"),
    }


@pytest.fixture
def corrupted_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the corrupted statement dossier (malformed binary)."""
    return {
        "bank_statement": str(fixtures_dir / "corrupted" / "corrupted_statement.pdf"),
        "kyc_id": str(fixtures_dir / "clean_4pages" / "kyc_executive_id.jpg"),
        "tax_filing": str(fixtures_dir / "clean_4pages" / "tax_filing_irs1120.pdf"),
    }


@pytest.fixture
def benchmark_dossier_manifest(fixtures_dir: Path) -> dict[str, str]:
    """Return paths for the 16-page benchmark statement dossier."""
    return {
        "bank_statement": str(fixtures_dir / "benchmark_16pages" / "bank_statement_16pages.pdf"),
        "kyc_id": str(fixtures_dir / "clean_4pages" / "kyc_executive_id.jpg"),
        "tax_filing": str(fixtures_dir / "clean_4pages" / "tax_filing_irs1120.pdf"),
    }


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer | None, None, None]:
    """Launch a PostgreSQL 16 testcontainer for the test session if available."""
    if os.getenv("TEST_DATABASE_URL"):
        yield None
        return
    try:
        with PostgresContainer("postgres:16", driver="asyncpg") as container:
            yield container
    except Exception:
        yield None


@pytest.fixture(scope="session")
async def test_database_url(postgres_container: PostgresContainer | None) -> str:
    """Initialize schema using init.sql against testcontainer or local DB and return async DB URL."""
    if os.getenv("TEST_DATABASE_URL"):
        db_url = os.environ["TEST_DATABASE_URL"]
    elif postgres_container is not None:
        db_url = postgres_container.get_connection_url(driver="asyncpg")
    else:
        db_url = "postgresql+asyncpg://postgres:postgres@localhost:5433/underwriting_db"

    init_sql_path = MODULE_ROOT / "init.sql"
    with open(init_sql_path) as f:
        ddl = f.read()

    engine = create_async_engine(db_url)
    try:
        async with engine.begin() as conn:
            raw_conn = await conn.get_raw_connection()
            await raw_conn.driver_connection.execute(ddl)
    except Exception as exc:
        if "already exists" not in str(exc):
            raise
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE underwriting_memos, document_pages, documents, applications CASCADE;")
        )
    await engine.dispose()
    return db_url


@pytest.fixture
async def db_session(test_database_url: str) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated transactional async database session for tests."""
    engine = create_async_engine(test_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    # Clean up records after each test to ensure test isolation
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE underwriting_memos, document_pages, documents, applications CASCADE;")
        )
    await engine.dispose()


def _check_tcp_port(host: str, port: int, timeout: float = 0.5) -> bool:
    """Check if a TCP port is open and accepting connections."""
    import socket
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def redis_service_url() -> Generator[str, None, None]:
    """Provide Redis service URL via existing environment, local port, or dynamic Testcontainer."""
    if os.getenv("REDIS_URL"):
        yield os.environ["REDIS_URL"]
        return
    if _check_tcp_port("localhost", 6380):
        yield "redis://localhost:6380/0"
        return

    from testcontainers.core.container import DockerContainer
    try:
        with DockerContainer("redis:7-alpine").with_exposed_ports(6379) as redis_cnt:
            port = redis_cnt.get_exposed_port(6379)
            yield f"redis://localhost:{port}/0"
    except Exception as exc:
        pytest.skip(f"Redis not available locally and Testcontainer failed: {exc}")


@pytest.fixture(scope="session")
def rabbitmq_service_url() -> Generator[str, None, None]:
    """Provide RabbitMQ broker URL via existing environment, local port, or dynamic Testcontainer."""
    if os.getenv("RABBITMQ_URL"):
        yield os.environ["RABBITMQ_URL"]
        return
    if _check_tcp_port("localhost", 5673):
        yield "amqp://guest:guest@localhost:5673//"
        return

    from testcontainers.core.container import DockerContainer
    import amqp
    import time

    try:
        with DockerContainer("rabbitmq:3.13-management-alpine").with_exposed_ports(5672) as rmq_cnt:
            port = rmq_cnt.get_exposed_port(5672)
            # Wait for broker socket readiness
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


@pytest.fixture(autouse=True)
def configure_celery_for_tests():
    """Ensure Celery runs in eager mode during test executions."""
    from services.worker.celery_app import celery_app
    orig_eager = celery_app.conf.task_always_eager
    orig_prop = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = orig_eager
    celery_app.conf.task_eager_propagates = orig_prop


@pytest.fixture
async def app_instance(test_database_url: str):
    """Provide a FastAPI application instance wired to the testcontainer database."""
    from app.config import settings
    orig_url = settings.database_url
    settings.database_url = test_database_url
    os.environ["DATABASE_URL"] = test_database_url

    test_settings = Settings(database_url=test_database_url)
    app = create_app(app_settings=test_settings)
    async with app.router.lifespan_context(app):
        yield app

    settings.database_url = orig_url
    # Clean up after test
    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE underwriting_memos, document_pages, documents, applications CASCADE;")
        )
    await engine.dispose()


@pytest.fixture
async def async_client(app_instance) -> AsyncGenerator[AsyncClient, None]:
    """Provide an AsyncClient wired to the test application."""
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        yield client
