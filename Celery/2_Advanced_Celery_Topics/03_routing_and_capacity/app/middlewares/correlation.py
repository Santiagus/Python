"""Correlation ID middleware for distributed request tracing.

Extracts incoming X-Request-ID or generates a fresh UUID, binds it to the
asynchronous ContextVar lifecycle, and attaches X-Request-ID to response headers.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

from app.logging_config import current_request_id


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Binds request correlation IDs to asynchronous context and response headers."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Extract or generate request correlation ID and manage ContextVar token scope."""
        # 1. Extract existing X-Request-ID from inbound header or generate a new UUID
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id

        # 2. Bind to ContextVar so downstream logs, DB queries, and task dispatches inherit it
        token = current_request_id.set(request_id)

        try:
            # 3. Proceed to downstream middleware and route handler
            response = await call_next(request)

            # 4. Attach correlation ID to outbound response headers
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # 5. Invariant: Always reset ContextVar token to avoid context pollution in asyncio
            current_request_id.reset(token)

