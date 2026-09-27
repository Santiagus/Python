"""Unit tests for database engine, role-budgeted pool management, and session lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool, QueuePool

import app.db as db_mod
from app.config import Settings


@pytest.mark.asyncio
async def test_create_engine_and_factory_development() -> None:
    """Verify engine and session factory creation with development pool budgeting."""
    dev_settings = Settings(
        environment="development",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
        db_pool_size=5,
        db_max_overflow=10,
        db_worker_pool_size=2,
        db_worker_max_overflow=2,
    )

    with patch("app.db.get_settings", return_value=dev_settings):
        # API gateway mode
        engine_api, factory_api = db_mod._create_engine_and_factory(is_worker=False)
        assert isinstance(engine_api.pool, QueuePool)
        assert engine_api.pool.size() == 5
        await engine_api.dispose()

        # Worker mode
        engine_worker, factory_worker = db_mod._create_engine_and_factory(is_worker=True)
        assert isinstance(engine_worker.pool, QueuePool)
        assert engine_worker.pool.size() == 2
        await engine_worker.dispose()


@pytest.mark.asyncio
async def test_create_engine_and_factory_test_environment() -> None:
    """Verify that test environment provisions NullPool."""
    test_settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
    )

    with patch("app.db.get_settings", return_value=test_settings):
        engine_test, _ = db_mod._create_engine_and_factory(is_worker=False)
        assert isinstance(engine_test.pool, NullPool)
        await engine_test.dispose()


@pytest.mark.asyncio
async def test_init_worker_db() -> None:
    """Verify init_worker_db initializes the worker engine and factory with worker budgeting."""
    mock_engine = MagicMock()
    mock_factory = MagicMock()
    with patch("app.db._create_engine_and_factory", return_value=(mock_engine, mock_factory)):
        eng, fac = db_mod.init_worker_db()
        assert eng is mock_engine
        assert fac is mock_factory
        assert db_mod.get_engine() is mock_engine
        assert db_mod.get_session_factory() is mock_factory


@pytest.mark.asyncio
async def test_get_engine_and_factory_fallback_initialization() -> None:
    """Verify get_engine and get_session_factory reinitialize if globals are None."""
    mock_engine = MagicMock()
    mock_factory = MagicMock()
    with patch("app.db._create_engine_and_factory", return_value=(mock_engine, mock_factory)):
        with patch("app.db._engine", None):
            assert db_mod.get_engine() is mock_engine
        with patch("app.db._session_factory", None):
            assert db_mod.get_session_factory() is mock_factory


@pytest.mark.asyncio
async def test_get_session_lifecycle() -> None:
    """Verify get_session yields an active session and triggers rollback on error."""
    mock_session = AsyncMock(spec=AsyncSession)
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_session

    with patch("app.db.get_session_factory", return_value=mock_factory):
        # 1. Clean exit
        async for session in db_mod.get_session():
            assert session is mock_session
        assert not mock_session.rollback.called

        # 2. Rollback on exception via athrow (FastAPI dependency lifecycle)
        gen = db_mod.get_session()
        session2 = await anext(gen)
        assert session2 is mock_session
        with pytest.raises(RuntimeError, match="simulated error"):
            await gen.athrow(RuntimeError("simulated error"))
        assert mock_session.rollback.called


@pytest.mark.asyncio
async def test_close_db() -> None:
    """Verify close_db disposes of the active engine cleanly."""
    mock_engine = AsyncMock()
    with (
        patch("app.db._engine", mock_engine),
        patch("app.db._session_factory", MagicMock()),
    ):
        await db_mod.close_db()
        assert mock_engine.dispose.called
        assert db_mod._engine is None
        assert db_mod._session_factory is None

    # Test closing when already None
    with (
        patch("app.db._engine", None),
        patch("app.db._session_factory", None),
    ):
        await db_mod.close_db()
