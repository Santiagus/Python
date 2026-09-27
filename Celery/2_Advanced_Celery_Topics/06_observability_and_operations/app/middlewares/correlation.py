"""Correlation ID propagation middleware for request tracing and distributed logs.

Extracts incoming X-Request-ID or generates a new UUIDv4, populating contextvars.
"""

import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import current_request_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware capturing or generating correlation IDs per HTTP request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process incoming request, setting correlation context for duration of call.

        Args:
            request: Active Starlette/FastAPI request instance.
            call_next: Next ASGI handler in middleware pipeline.

        Returns:
            Response: Outgoing HTTP response with attached correlation header.
        """
        # 1. Extract existing X-Request-ID header or provision new UUIDv4
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        # 2. Bind ID to context variable for thread/task isolation
        token = current_request_id.set(req_id)
        request.state.request_id = req_id

        try:
            # 3. Process downstream endpoint handlers
            response = await call_next(request)
        finally:
            # 4. Cleanly reset context token to prevent leakage
            current_request_id.reset(token)

        # 5. Echo correlation ID on outgoing response header
        response.headers["X-Request-ID"] = req_id
        return response
