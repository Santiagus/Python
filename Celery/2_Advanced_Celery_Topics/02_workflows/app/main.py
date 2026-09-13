"""FastAPI application factory, logging configuration, and centralized error handling."""

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .config import Settings, settings
from .db import Database, get_database
from .logging_config import configure_logging, current_request_id
from .routes import router

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Attach request IDs, log request lifecycles, and trap unhandled exceptions."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        """Intercept requests to ensure safe error normalization and trace logging."""
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        token = current_request_id.set(request_id)
        started = time.perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception:
                # Trap unexpected errors so they do not provoke server crashes or shutdowns
                logger.exception(
                    "unhandled_request_error",
                    extra={"request_id": request_id, "path": request.url.path},
                )
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "internal server error", "request_id": request_id},
                )

            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers["X-Request-ID"] = request_id

            if response.status_code >= 400 and not getattr(request.state, "error_logged", False):
                logger.warning(
                    "request_error",
                    extra={
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code,
                        "duration_ms": duration_ms,
                    },
                )

            logger.info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            current_request_id.reset(token)


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """Construct and configure the FastAPI application with error handling and database lifespan."""
    effective_settings = app_settings or settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Configure structured logging and manage database engine lifecycle."""
        configure_logging(
            level=effective_settings.log_level,
            log_format=effective_settings.effective_log_format,
        )
        logger.info(
            "service_startup",
            extra={
                "service": effective_settings.app_name,
                "environment": effective_settings.environment,
                "log_format": effective_settings.effective_log_format,
            },
        )
        database = Database(effective_settings)
        app.state.database = database
        try:
            yield
        finally:
            logger.info("service_shutdown", extra={"service": effective_settings.app_name})
            await database.close()

    app = FastAPI(
        title="Financial Document & KYC Underwriting API",
        version="1.0.0",
        description="Ingestion API and Celery Canvas orchestrator for commercial credit underwriting.",
        lifespan=lifespan,
    )

    @app.exception_handler(HTTPException)
    async def log_http_exception(request: Request, exc: HTTPException):
        """Log HTTP exceptions cleanly and return normalized responses with request IDs."""
        request.state.error_logged = True
        request_id = getattr(request.state, "request_id", "-")
        logger.warning(
            "%s %s failed with %s: %s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
            extra={"request_id": request_id},
        )
        headers = dict(exc.headers or {})
        headers["X-Request-ID"] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "request_id": request_id},
            headers=headers,
        )

    # Middleware execution
    app.add_middleware(ErrorHandlingMiddleware)

    # Mount API routers
    app.include_router(router, prefix=effective_settings.api_prefix)

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        """Liveness check endpoint."""
        return {"status": "ok", "service": effective_settings.app_name}

    def database_dependency(request: Request) -> Database:
        """Resolve database instance from application state."""
        return request.app.state.database

    app.dependency_overrides[get_database] = database_dependency

    return app


app = create_app()
