"""Unhandled exception shielding and error response normalization middleware.

Intercepts any uncaught Python exceptions escaping downstream route handlers,
logs the root cause with trace context, and emits a normalized JSON 500 response.
"""

from __future__ import annotations

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Shields public clients from raw server crashes and normalizes HTTP 500 responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Trap unhandled exceptions and format a standardized JSON error payload."""
        request_id = getattr(request.state, "request_id", "unknown")

        try:
            return await call_next(request)
        except Exception:
            # 1. Log full exception traceback with correlation ID
            logger.exception(
                "unhandled_request_error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )

            # 2. Return a safe, normalized JSON 500 without leaking stack traces or internal paths
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "internal server error",
                    "request_id": request_id,
                },
            )
            response.headers["X-Request-ID"] = request_id
            return response
