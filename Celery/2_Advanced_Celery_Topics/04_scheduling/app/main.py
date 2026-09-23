"""FastAPI application entry point, lifespan management, and middleware orchestration.

Initializes connection pools, configures structured logging, registers middleware pipelines,
and binds the reconciliation management router.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.db import close_db_engine, get_engine
from app.logging_config import configure_logging
from app.middlewares import register_middlewares
from app.routes import router as reconciliation_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager initializing resources at startup and disposing on shutdown."""
    settings = get_settings()

    # 1. Initialize logging configuration
    configure_logging(log_level=settings.log_level)
    logger.info("Application starting up in %s environment", settings.environment)

    # 2. Pre-warm database connection pool
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection pool warmed successfully")
    except Exception as exc:
        logger.warning("Database pre-warm check failed: %s", exc)

    yield

    # 3. Clean up database engine pool on graceful shutdown
    logger.info("Application shutting down, disposing database connection pool")
    await close_db_engine()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance.

    Returns:
        FastAPI: Fully configured FastAPI application.
    """
    app = FastAPI(
        title="EOD Banking Cut-Off & Ledger Reconciliation API",
        description=(
            "Control plane API for End-of-Day banking cut-off scheduling, "
            "double-entry ledger reconciliation, gap audit backfills, and Celery task tracking."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # Register modular middleware stack (correlation, security, error handling, profiling)
    register_middlewares(app)

    # Include routes at root and /api/v1 for versioned & unversioned compatibility
    app.include_router(reconciliation_router, prefix="/api/v1")
    app.include_router(reconciliation_router)

    return app


app = create_app()
