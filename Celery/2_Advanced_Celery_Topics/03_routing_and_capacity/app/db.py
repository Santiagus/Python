"""Database engine, session management, and connection pooling.

Provides an asynchronous SQLAlchemy 2.0 engine configured with asyncpg, connection
pre-pinging, robust pool sizing, and session factory dependencies.
pre-pinging, robust pool sizing, and session factory dependencies. Eagerly initializes
singletons at module load to eliminate first-call warm time.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
import logging
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import get_settings

logger = logging.getLogger(__name__)

# Module-level engine and sessionmaker references
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _create_engine_and_factory(
    is_worker: bool = False,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Instantiate an AsyncEngine and async_sessionmaker according to environment and process role.

    Args:
        is_worker: If True, uses budgeted worker pool sizes (default 2/2) to prevent
                   PostgreSQL connection exhaustion across prefork processes.
                   If False, uses API gateway pool sizing (default 10/20).

    Returns:
        tuple[AsyncEngine, async_sessionmaker[AsyncSession]]: Configured engine and sessionmaker.
    """
    settings = get_settings()
    # 1. In testing, use NullPool to avoid connection sharing across async event loops
    if settings.environment in ("test", "testing"):
        engine = create_async_engine(
            settings.database_url,
            poolclass=NullPool,
            echo=False,
            future=True,
        )
    else:
        # 2. Budget connection pool sizing by process role
        pool_size = settings.db_worker_pool_size if is_worker else settings.db_pool_size
        max_overflow = settings.db_worker_max_overflow if is_worker else settings.db_max_overflow
        engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
            connect_args={"statement_cache_size": 0},
            echo=False,
            future=True,
        )

    # 3. Sessionmaker with expire_on_commit=False to keep objects accessible post-commit
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, factory


# Eagerly initialize module-level engine and sessionmaker at load time to eliminate first-call warm time
_engine: AsyncEngine | None
_session_factory: async_sessionmaker[AsyncSession] | None
_engine, _session_factory = _create_engine_and_factory(is_worker=False)


def get_engine() -> AsyncEngine:
    """Return the global async database engine, initializing it if necessary."""
    global _engine
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        # 1. In testing, use NullPool to avoid connection sharing across async event loops
        if settings.environment in ("test", "testing"):
            _engine = create_async_engine(
                settings.database_url,
                poolclass=NullPool,
                echo=False,
                future=True,
            )
        else:
            _engine = create_async_engine(
                settings.database_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                echo=False,
                future=True,
            )
        _engine, _session_factory = _create_engine_and_factory(is_worker=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the global async sessionmaker factory."""
    global _session_factory
    global _engine, _session_factory
    if _session_factory is None:
        engine = get_engine()
        # 2. Sessionmaker with expire_on_commit=False to keep objects accessible post-commit
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        _engine, _session_factory = _create_engine_and_factory(is_worker=False)
    return _session_factory


def init_worker_db() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Eagerly initialize worker process database engine and connection pool on boot.

    Configures lightweight connection pool sizes (2 connections per worker process)
    to prevent PostgreSQL connection pool exhaustion across Celery prefork processes.

    Returns:
        tuple[AsyncEngine, async_sessionmaker[AsyncSession]]: Process-local engine and factory.
    """
    global _engine, _session_factory
    _engine, _session_factory = _create_engine_and_factory(is_worker=True)
    return _engine, _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI route dependency providing an isolated asynchronous database session.

    Yields:
        AsyncSession: Active database session with transaction boundary.
    """
    session_maker = get_session_factory()
    async with session_maker() as session:
        try:
            # 3. Yield session to route handler
            # 1. Yield session to route handler
            yield session
        except Exception:
            # 4. Roll back transaction on any unhandled error
            # 2. Roll back transaction on any unhandled error
            await session.rollback()
            raise
        finally:
            # 5. Cleanly close session
            # 3. Cleanly close session
            await session.close()


async def close_db() -> None:
    """Dispose the engine connection pool cleanly on application shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        logger.info("Disposing database connection pool...")
        await _engine.dispose()
        _engine = None
        _session_factory = None

