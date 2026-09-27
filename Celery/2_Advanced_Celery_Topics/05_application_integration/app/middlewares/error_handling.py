"""Centralized error handling middleware preventing server crash and normalizing 500 responses."""

from __future__ import annotations

import logging
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.logging_config import current_request_id

logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Intercepts unhandled exceptions and returns normalized JSON 500 error responses."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Execute request pipeline and intercept unexpected runtime exceptions."""
        try:
            return await call_next(request)
        except Exception:
            req_id = getattr(request.state, "request_id", None) or current_request_id.get() or str(uuid4())
            logger.exception(
                "unhandled_request_error",
                extra={
                    "request_id": req_id,
                    "method": request.method,
                    "path": request.url.path,
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
