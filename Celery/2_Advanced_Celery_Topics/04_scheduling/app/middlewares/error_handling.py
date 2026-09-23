"""Centralized error handling middleware shielding unhandled exceptions."""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.logging_config import current_request_id

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Shields client from unhandled internal exceptions by normalizing them into RFC-compliant JSON responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Intercept unhandled exceptions, log with traceback, and return standard 500 JSON response."""
        try:
            return await call_next(request)
        except Exception as exc:
            req_id = current_request_id.get() or "unknown"
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
                    "detail": "Internal server error",
                    "request_id": req_id,
                },
                headers={"X-Request-ID": req_id},
            )
