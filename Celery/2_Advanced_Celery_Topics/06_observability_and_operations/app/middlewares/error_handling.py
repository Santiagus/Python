"""Centralized error handling middleware intercepting unhandled exceptions.

Normalizes unhandled errors into standardized JSON 500 responses without leaking secrets.
"""

import logging
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.logging_config import current_request_id

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware catching unhandled exceptions and returning normalized JSON 500s."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Intercept unhandled exceptions and format normalized error responses.

        Args:
            request: Incoming HTTP request instance.
            call_next: Downstream ASGI application callable.

        Returns:
            Response: Validated HTTP response or sanitized JSON error response.
        """
        try:
            return await call_next(request)
        except Exception as exc:
            req_id: str = str(
                current_request_id.get() or getattr(request.state, "request_id", "unknown")
            )
            logger.exception(
                "unhandled_request_error",
                extra={
                    "request_id": req_id,
                    "path": request.url.path,
                    "method": request.method,
                    "error": str(exc),
                },
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error occurred",
                    "request_id": req_id,
                },
                headers={"X-Request-ID": req_id},
            )
