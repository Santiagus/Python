import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from .config import get_settings
from .db import Database
from .logging_config import configure_logging
from .routes import get_database, router

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled_request_error",
                extra={"request_id": request_id, "path": request.url.path},
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal server error", "request_id": request_id},
            )
        response.headers["X-Request-ID"] = request_id
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
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    app.state.database = database
    try:
        yield
    finally:
        await database.close()


def create_app() -> FastAPI:
    app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
    app.add_middleware(ErrorHandlingMiddleware)
    app.include_router(router)

    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_api_route("/health", health, methods=["GET"])

    def database_dependency(request: Request) -> Database:
        return request.app.state.database

    app.dependency_overrides[get_database] = database_dependency
    return app


app = create_app()
