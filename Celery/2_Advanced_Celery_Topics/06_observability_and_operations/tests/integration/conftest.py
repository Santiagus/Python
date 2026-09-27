"""Test configuration and hybrid testcontainers fixtures for integration tests.

Provides automated ephemeral PostgreSQL testcontainers or fallback to local services.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from app.database import get_session
from app.main import app


@pytest.fixture(scope="session")
def postgres_url() -> Generator[str, None, None]:
    """Resolve PostgreSQL connection string using local environment or Testcontainers.

    Returns:
        str: asyncpg-compatible PostgreSQL connection URL.
    """
    env_url = os.getenv("TEST_DATABASE_URL")
    if env_url:
        yield env_url
        return

    container = PostgresContainer("postgres:16-alpine", driver="asyncpg")
    container.start()
    url = container.get_connection_url()

    # Register finalizer on container shutdown
    yield url
    container.stop()


@pytest.fixture(scope="session", autouse=True)
def init_test_database(postgres_url: str) -> None:
    """Synchronously provision relational DDL schema once for test session."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    init_sql_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "init.sql"
    )
    with open(init_sql_path, "r") as f:
        ddl_script = f.read()

    import re

    cleaned_sql = re.sub(r"--.*?\n", "\n", ddl_script)

    async def _init_ddl() -> None:
        async with engine.begin() as conn:
            for statement in cleaned_sql.split(";"):
                cleaned = statement.strip()
                if cleaned:
                    await conn.execute(text(cleaned))
        await engine.dispose()

    asyncio.run(_init_ddl())


@pytest_asyncio.fixture
async def async_engine(postgres_url: str) -> AsyncGenerator[AsyncEngine, None]:
    """Provide a function-scoped AsyncEngine with NullPool to prevent loop collisions."""
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session_factory(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return sessionmaker bound to function-scoped test database engine."""
    return async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def db_session(
    async_engine: AsyncEngine,
    async_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated database session per test and truncate tables afterwards."""
    async with async_session_factory() as session:
        yield session

    # Truncate tables cleanly between test cases
    async with async_engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE watchlist_hits, operational_events, screenings "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def mock_dispatcher() -> Generator[MagicMock, None, None]:
    """Mock Celery workflow dispatcher to isolate HTTP and DB layers."""
    with patch("app.main.dispatch_screening_workflow") as mock_dispatch:
        mock_result = MagicMock()
        mock_result.id = "mock-celery-task-id-1234"
        mock_dispatch.return_value = mock_result
        yield mock_dispatch


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    mock_dispatcher: MagicMock,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide test HTTP client with overridden session dependency and mocked dispatcher."""

    async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    app.dependency_overrides.clear()
