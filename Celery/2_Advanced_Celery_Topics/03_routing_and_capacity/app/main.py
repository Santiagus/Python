"""FastAPI Application Entrypoint & Lifespan Management.

Wires the modular 5-layer middleware pipeline, registers payment orchestration routes,
configures structured logging, and manages database connection pool lifecycles.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.config import get_settings
from app.db import close_db, get_engine
from app.logging_config import configure_logging
from app.middlewares import register_middlewares
from app.routes import router
from services.bank_simulator_api.client import close_bank_client

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager managing startup and shutdown hooks."""
    # 1. Startup: Warm database connection pool and start hybrid cache listener
    logger.info(
        "starting_payment_orchestrator_gateway",
        extra={"environment": settings.environment, "log_level": settings.log_level},
    )
    engine = get_engine()
    from app.cache import get_account_cache

    cache_mgr = get_account_cache()

    if settings.environment not in ("test", "testing"):
        try:
            from sqlalchemy import text

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("db_warmup_failed", extra={"error": str(exc)})

        # Eagerly warm Celery Kombu AMQP broker connection pool
        try:
            from services.worker.celery_app import celery_app

            with celery_app.connection_for_write() as conn:
                conn.connect()
        except Exception as exc:
            logger.warning("broker_warmup_failed", extra={"error": str(exc)})

        # Start Redis Pub/Sub cache invalidation listener
        try:
            await cache_mgr.start_listener()
        except Exception as exc:
            logger.warning("cache_listener_start_failed", extra={"error": str(exc)})

    yield

    # 2. Shutdown: Gracefully dispose cache listener, database pool, and shared HTTP client
    logger.info("shutting_down_payment_orchestrator_gateway")
    await cache_mgr.stop_listener()
    await close_bank_client()
    await close_db()


def create_app() -> FastAPI:
    """Application factory for the Payment Orchestrator API Gateway."""
    app = FastAPI(
        title="Multi-Rail Payment Orchestrator & Batch Settlement Engine",
        version="1.0.0",
        description=(
            "Enterprise-grade distributed payment orchestration engine powered by Celery, "
            "RabbitMQ, and FastAPI. Demonstrates queue isolation, rate limiting, and 100% coverage."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Register 5-layer modular middleware stack in deterministic LIFO order
    register_middlewares(app)

    # 2. Register API endpoints
    app.include_router(router)

    return app


app = create_app()
