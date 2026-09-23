"""Database engine, session management, and connection pooling.

Provides an asynchronous SQLAlchemy 2.0 engine configured with asyncpg, connection
pre-pinging, robust pool sizing, and session factory dependencies. Eagerly initializes
singletons at module load to eliminate first-call warm time.
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
            echo=False,
            future=True,
        )

    # 3. Create session factory with autocommit/autoflush disabled
    factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    return engine, factory


def init_db(is_worker: bool = False) -> None:
    """Explicitly initialize or reconfigure the database engine and session factory.

    Useful for worker fork initialization hooks or runtime environment overrides.

    Args:
        is_worker: Whether to configure worker-budgeted pools.
    """
    global _engine, _session_factory
    _engine, _session_factory = _create_engine_and_factory(is_worker=is_worker)
    logger.info(
        "Database initialized (role=%s, pool=%s)",
        "worker" if is_worker else "api",
        type(_engine.pool).__name__,
    )


# Eager Singleton Initialization at Module Load (Zero Cold-Start Invariant)
init_db(is_worker=False)


def get_engine() -> AsyncEngine:
    """Retrieve the shared AsyncEngine singleton.

    Returns:
        AsyncEngine: Active SQLAlchemy async engine.
    """
    global _engine
    if _engine is None:
        init_db(is_worker=False)
    assert _engine is not None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retrieve the shared session factory singleton.

    Returns:
        async_sessionmaker[AsyncSession]: Active SQLAlchemy session factory.
    """
    global _session_factory
    if _session_factory is None:
        init_db(is_worker=False)
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an isolated, auto-closing AsyncSession.

    Yields:
        AsyncSession: Active async database session context.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def close_db_engine() -> None:
    """Dispose of the shared AsyncEngine pool gracefully during shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine connection pool disposed")

