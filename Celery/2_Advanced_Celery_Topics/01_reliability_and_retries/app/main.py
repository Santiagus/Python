"""FastAPI application factory and request error handling for the transaction API."""

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .config import get_settings
from .db import Database
from .logging_config import configure_logging
from .routes import get_database, router

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Attach a request id and emit access logs for every HTTP request."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        """Log request lifecycle events and normalize unexpected exceptions."""
        # Keep one request identifier across the response and every log entry so
        # failures can be followed through the API and worker logs.
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Do not expose internal exception details to clients, but retain the
            # traceback in server logs for diagnosis.
            logger.exception(
                "unhandled_request_error",
                extra={"request_id": request_id, "path": request.url.path},
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal server error", "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
        # HTTP exceptions are logged by the exception handler; avoid emitting a
        # second error event while still recording one completion event here.
        if response.status_code >= 400 and not getattr(request.state, "error_logged", False):
            logger.warning(
                "request_error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
        logger.info(
            "request_complete",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application state during startup and close resources on shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    database = Database(settings)
    app.state.database = database
    try:
        yield
    finally:
        await database.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title=get_settings().app_name, lifespan=lifespan)

    @app.exception_handler(HTTPException)
    async def log_http_exception(request: Request, exc: HTTPException):
        """Log HTTP exceptions and return the original API response without losing context."""
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
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    app.add_middleware(ErrorHandlingMiddleware)
    app.include_router(router)

    async def health() -> dict[str, str]:
        """Return a simple readiness response for the API."""
        return {"status": "ok"}

    app.add_api_route("/health", health, methods=["GET"])

    def database_dependency(request: Request) -> Database:
        """Resolve the application database instance from the request state."""
        return request.app.state.database

    app.dependency_overrides[get_database] = database_dependency
    return app


app = create_app()
