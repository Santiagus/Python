"""Pytest fixtures and configuration for Module 02 test suite."""

import os
import sys
from collections.abc import AsyncIterator, Generator
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
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Launch a PostgreSQL 16 testcontainer for the test session."""
    with PostgresContainer("postgres:16", driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
async def test_database_url(postgres_container: PostgresContainer) -> str:
    """Initialize schema using init.sql against testcontainer and return async DB URL."""
    db_url = postgres_container.get_connection_url(driver="asyncpg")
    init_sql_path = MODULE_ROOT / "init.sql"
    with open(init_sql_path) as f:
        ddl = f.read()

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        raw_conn = await conn.get_raw_connection()
        await raw_conn.driver_connection.execute(ddl)
    await engine.dispose()
    return db_url


@pytest.fixture
async def db_session(test_database_url: str) -> AsyncIterator[AsyncSession]:
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


@pytest.fixture
async def app_instance(test_database_url: str):
    """Provide a FastAPI application instance wired to the testcontainer database."""
    test_settings = Settings(database_url=test_database_url)
    app = create_app(app_settings=test_settings)
    async with app.router.lifespan_context(app):
        yield app
    # Clean up after test
    engine = create_async_engine(test_database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE TABLE underwriting_memos, document_pages, documents, applications CASCADE;")
        )
    await engine.dispose()


@pytest.fixture
async def async_client(app_instance) -> AsyncIterator[AsyncClient]:
    """Provide an AsyncClient wired to the test application."""
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as client:
        yield client
