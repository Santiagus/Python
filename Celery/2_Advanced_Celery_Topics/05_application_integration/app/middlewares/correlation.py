"""Correlation ID middleware for distributed request tracing."""

from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import current_request_id


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Extracts or generates X-Request-ID and propagates it across async context."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process incoming request, bind ContextVar, and attach header to response."""
        # 1. Extract incoming request correlation ID or generate a new UUID
        incoming_id = request.headers.get("X-Request-ID")
        req_id = incoming_id.strip() if incoming_id and incoming_id.strip() else str(uuid4())

        # 2. Store on request state and bind to thread/coroutine ContextVar
        request.state.request_id = req_id
        token = current_request_id.set(req_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            current_request_id.reset(token)
