"""Database engine, session management, and connection pooling.

Provides an asynchronous SQLAlchemy 2.0 engine configured with asyncpg, connection
pre-pinging, role-budgeted pool sizing (lightweight for worker child processes,
higher capacity for API gateway), and eager singleton initialization at module load.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

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
_engine, _session_factory = _create_engine_and_factory(is_worker=False)


def get_engine() -> AsyncEngine:
    """Return the global async database engine, initializing it if necessary.

    Returns:
        AsyncEngine: Active SQLAlchemy asynchronous database engine.
    """
    global _engine, _session_factory
    if _engine is None:
        _engine, _session_factory = _create_engine_and_factory(is_worker=False)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the global async sessionmaker factory.

    Returns:
        async_sessionmaker[AsyncSession]: Configured sessionmaker instance.
    """
    global _engine, _session_factory
    if _session_factory is None:
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
        AsyncSession: Active asynchronous database session with auto-rollback on error.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Close and dispose all active connection pools."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
