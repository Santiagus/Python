"""Asynchronous database connection factory and connection pool management.

Provides SQLAlchemy 2.0 AsyncEngine, session factories, and pre-ping warmup hooks.
"""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

logger = logging.getLogger(__name__)

# 1. Eager Singleton Initialization at Module Load (API Gateway pool budget: 10/20)
engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0},
)

session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def warm_database_pool() -> bool:
    """Pre-warm connection pool with an initial SELECT 1 ping during boot.

    Returns:
        bool: True if database connection ping succeeded.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_pool_warmed_successfully")
        return True
    except Exception as exc:
        logger.error(f"database_pool_warmup_failed: {exc}")
        return False


async def close_database_pool() -> None:
    """Dispose the asynchronous database engine connection pool cleanly."""
    await engine.dispose()
    logger.info("database_pool_disposed")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an isolated transaction session per request.

    Yields:
        AsyncSession: Active asynchronous database session.
    """
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
