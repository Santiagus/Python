"""FastAPI Ingestion Gateway for High-Value Interbank Wire Settlement.

Handles high-throughput wire transfer ingestion, anti-blackhole persistence,
publisher-confirmed AMQP dispatch, and health checks.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.dispatcher import get_wire_dispatcher
from app.middlewares import register_middlewares
from app.routes.health import router as health_router
from app.routes.wires import get_engine, get_session_factory
from app.routes.wires import router as wires_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup pool pre-warming and graceful shutdown.

    Pre-warms the asynchronous database pool with a SELECT 1 ping and ensures
    eager singleton initialization of AMQP dispatchers. Disposes the database
    engine upon shutdown.

    Args:
        app: The FastAPI application instance.

    Yields:
        None
    """
    # 1. Pre-warm database connection pool on startup
    session_factory = get_session_factory()
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))

    # 2. Eagerly access AMQP dispatcher singleton to verify connection settings
    _ = get_wire_dispatcher()

    yield

    # 3. Graceful shutdown: dispose database connection pool
    await get_engine().dispose()


app: FastAPI = FastAPI(
    title="High-Value Interbank Wire Gateway",
    description="Wholesale wire transfer settlement ingestion gateway with ACID persistence and durable AMQP dispatch.",
    version="1.0.0",
    lifespan=lifespan,
)

# 4. Register modular correlation and error handling middlewares
register_middlewares(app)

# 5. Register application routes
app.include_router(health_router)
app.include_router(wires_router)
