"""Unit tests for Database engine and session lifecycle."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.config import Settings
from app.db import Database


@pytest.mark.asyncio
async def test_database_initialization() -> None:
    """Verify Database initializes engine and session factory with settings URL."""
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost:5432/testdb")
    with patch("app.db.create_async_engine") as mock_create_engine:
        db = Database(settings)
        mock_create_engine.assert_called_once_with(
            "postgresql+asyncpg://user:pass@localhost:5432/testdb",
            pool_pre_ping=True,
        )
        assert db.engine is not None
        assert db.session_factory is not None


@pytest.mark.asyncio
async def test_database_session_rollback_on_exception() -> None:
    """Verify Database.session triggers rollback when an exception occurs."""
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost:5432/testdb")
    with patch("app.db.create_async_engine") as mock_create_engine:
        db = Database(settings)
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_session_factory.return_value.__aexit__.return_value = False
        db.session_factory = mock_session_factory

        with pytest.raises(RuntimeError, match="DB operation error"):
            async with db.session() as session:
                raise RuntimeError("DB operation error")

        mock_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_database_close() -> None:
    """Verify Database.close disposes the engine."""
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost:5432/testdb")
    with patch("app.db.create_async_engine") as mock_create_engine:
        mock_engine = AsyncMock()
        mock_create_engine.return_value = mock_engine
        db = Database(settings)
        await db.close()
        mock_engine.dispose.assert_awaited_once()

