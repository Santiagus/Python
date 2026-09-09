"""Database session factory and lifecycle helpers for async SQLAlchemy access."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings


class Database:
    """Manage the async database engine and database sessions."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the SQLAlchemy engine and session factory for the app."""
        self.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a transactional session and roll back any unhandled exception."""
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        """Dispose of the database engine connection pool."""
        await self.engine.dispose()
