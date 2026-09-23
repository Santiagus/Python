"""Correlation ID middleware for distributed request tracing and context propagation."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import current_request_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware that extracts or generates a UUID correlation ID for each incoming request."""

    HEADER_NAME = "X-Request-ID"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process incoming request, set correlation ContextVar, and attach header to response."""
        # 1. Extract existing correlation header or generate new UUID4
        req_id = request.headers.get(self.HEADER_NAME)
        if not req_id:
            req_id = str(uuid.uuid4())

        # 2. Bind current request ID to async ContextVar
        token = current_request_id.set(req_id)

        try:
            # 3. Continue execution down the middleware and route handler stack
            response = await call_next(request)
            # 4. Attach correlation ID to outbound response headers
            response.headers[self.HEADER_NAME] = req_id
            return response
        finally:
            # 5. Reset ContextVar token to avoid context leakage across coroutines
            current_request_id.reset(token)
