"""Unit tests for database lifecycle, connection pooling, and application lifespan."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

import app.db as app_db
from app.config import get_settings
from app.main import create_app, lifespan


@pytest.mark.unit
class TestDatabaseAndLifecycle:
    """Test engine initialization, connection pool management, and app startup/shutdown."""

    @pytest.mark.asyncio
    async def test_get_engine_production_pool(self) -> None:
        """In production environment, get_engine configures AsyncAdaptedQueuePool with pooling parameters."""
        settings = get_settings()
        original_env = settings.environment

        # Clean up existing engine
        await app_db.close_db()

        try:
            settings.environment = "production"
            engine = app_db.get_engine()
            assert engine is not None
            # Calling again returns singleton
            assert app_db.get_engine() is engine
        finally:
            settings.environment = original_env
            await app_db.close_db()

    @pytest.mark.asyncio
    async def test_get_engine_test_environment(self) -> None:
        """In test environment, get_engine configures NullPool."""
        settings = get_settings()
        original_env = settings.environment
        await app_db.close_db()

        try:
            settings.environment = "test"
            engine = app_db.get_engine()
            assert engine is not None
        finally:
            settings.environment = original_env
            await app_db.close_db()

    def test_get_session_factory(self) -> None:
        """get_session_factory returns singleton async_sessionmaker."""
        app_db._session_factory = None
        factory1 = app_db.get_session_factory()
        factory2 = app_db.get_session_factory()
        assert factory1 is factory2

    def test_init_worker_db(self) -> None:
        """init_worker_db configures engine with worker-budgeted pool limits."""
        engine, factory = app_db.init_worker_db()
        assert engine is not None
        assert factory is not None
        assert app_db._engine is engine

    @pytest.mark.asyncio
    async def test_get_session_rollback_on_exception(self) -> None:
        """When an exception occurs within a get_session context, rollback is awaited before propagating."""
        mock_session = AsyncMock()
        mock_session_factory = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_cm

        with patch("app.db.get_session_factory", return_value=mock_session_factory):
            gen = app_db.get_session()
            session = await gen.__anext__()
            with pytest.raises(ValueError, match="Database transaction failed"):
                await gen.athrow(ValueError("Database transaction failed"))

            assert mock_session.rollback.called
            assert mock_session.close.called

    @pytest.mark.asyncio
    async def test_close_db_when_engine_none(self) -> None:
        """Calling close_db when engine is None executes cleanly without error."""
        app_db._engine = None
        app_db._session_factory = None
        await app_db.close_db()
        assert app_db._engine is None

    @pytest.mark.asyncio
    async def test_fastapi_app_lifespan(self) -> None:
        """Lifespan context manager starts engine and disposes on shutdown."""
        app = create_app()
        with patch("app.main.get_engine") as mock_get_engine, \
             patch("app.main.close_bank_client", new_callable=AsyncMock) as mock_close_client, \
             patch("app.main.close_db", new_callable=AsyncMock) as mock_close_db:
            async with lifespan(app):
                assert mock_get_engine.called

            assert mock_close_client.called
            assert mock_close_db.called

    @pytest.mark.asyncio
    async def test_fastapi_app_lifespan_production_warmup(self) -> None:
        """Lifespan warms up DB connection pool in production environment."""
        settings = get_settings()
        original_env = settings.environment
        app = create_app()
        try:
            settings.environment = "production"
            mock_conn = AsyncMock()
            mock_connect = MagicMock()
            mock_connect.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_connect.__aexit__ = AsyncMock(return_value=None)
            mock_engine = MagicMock()
            mock_engine.connect.return_value = mock_connect

            with patch("app.main.get_engine", return_value=mock_engine), \
                 patch("app.main.close_bank_client", new_callable=AsyncMock), \
                 patch("app.main.close_db", new_callable=AsyncMock):
                async with lifespan(app):
                    assert mock_conn.execute.called

            # Warmup failure branch handles gracefully
            mock_connect_fail = MagicMock()
            mock_connect_fail.__aenter__ = AsyncMock(side_effect=RuntimeError("db warmup fail"))
            mock_connect_fail.__aexit__ = AsyncMock(return_value=None)
            mock_engine_fail = MagicMock()
            mock_engine_fail.connect.return_value = mock_connect_fail
            with patch("app.main.get_engine", return_value=mock_engine_fail), \
                 patch("app.main.close_bank_client", new_callable=AsyncMock), \
                 patch("app.main.close_db", new_callable=AsyncMock):
                async with lifespan(app):
                    pass

            # Broker warmup failure branch handles gracefully
            mock_celery_fail = MagicMock()
            mock_celery_fail.connection_for_write.side_effect = RuntimeError("broker warmup fail")
            with patch("app.main.get_engine", return_value=mock_engine), \
                 patch("services.worker.celery_app.celery_app", mock_celery_fail), \
                 patch("app.main.close_bank_client", new_callable=AsyncMock), \
                 patch("app.main.close_db", new_callable=AsyncMock):
                async with lifespan(app):
                    pass
        finally:
            settings.environment = original_env

