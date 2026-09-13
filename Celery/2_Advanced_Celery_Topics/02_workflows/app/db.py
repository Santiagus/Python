"""Database connection factory and session management for async SQLAlchemy."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings


class Database:
    """Manage the async SQLAlchemy database engine and session factory."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the async engine and sessionmaker from application settings."""
        self.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Provide a transactional async session with automatic rollback on error."""
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        """Dispose of the database connection pool on shutdown."""
        await self.engine.dispose()


def get_database() -> Database:
    """FastAPI dependency placeholder for Database instance, injected at runtime."""
    raise RuntimeError("Database dependency has not been configured in application state")


async def get_session(database: Database = Depends(get_database)) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional AsyncSession for request handlers."""
    async with database.session() as session:
        yield session

