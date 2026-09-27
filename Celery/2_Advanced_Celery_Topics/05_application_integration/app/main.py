"""FastAPI Application entry point for Card Dispute & Chargeback Engine."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.db import close_db, get_engine
from app.logging_config import configure_logging
from app.middlewares import register_middlewares
from app.routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI application lifespan managing startup pre-warming and shutdown cleanup.

    Pre-warms the asynchronous database pool on boot with a 'SELECT 1' ping to eliminate
    first-request cold-start latency, and disposes of all engine pools on termination.
    """
    settings = get_settings()
    configure_logging(log_level="DEBUG" if settings.environment == "development" else "INFO")
    logger.info("app_startup_begin", extra={"environment": settings.environment})

    # Pre-warm the database connection pool
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_pool_prewarmed", extra={"database_url": settings.database_url})
    except Exception as exc:
        logger.warning("database_prewarm_skipped_or_failed", extra={"error": str(exc)})

    yield

    # Clean up and dispose database pools on shutdown
    logger.info("app_shutdown_begin")
    await close_db()
    logger.info("app_shutdown_complete")


def create_app() -> FastAPI:
    """Instantiate and configure the FastAPI gateway application.

    Returns:
        FastAPI: Fully configured ASGI application.
    """
    app = FastAPI(
        title="Card Dispute & Chargeback Engine",
        description=(
            "Production-grade distributed card dispute and chargeback lifecycle management platform. "
            "Implements anti-blackhole state machines, atomic cooperative cancellation, and 4-to-1 "
            "SQL query minimization."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Register layered middlewares (Profiling, ErrorHandling, Correlation)
    register_middlewares(app)

    # 2. Register API routers
    app.include_router(router)

    return app


app = create_app()
