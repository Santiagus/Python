"""Correlation ID extraction, injection, and ContextVar propagation middleware.

Captures inbound correlation headers from wholesale banking clients or generates
truncated 8-character UUIDs, propagating them across asynchronous contexts and AMQP headers.
"""

import uuid
from contextvars import ContextVar, Token

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# ContextVar for asynchronous request-scoped correlation ID tracking
current_request_id: ContextVar[str | None] = ContextVar("current_request_id", default=None)


def get_current_request_id() -> str | None:
    """Retrieve the current request correlation ID from the async context.

    Returns:
        str | None: Active correlation ID or None if called outside an HTTP request.
    """
    return current_request_id.get()


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Propagates or generates correlation IDs across incoming HTTP requests.

    Extracts the incoming 'X-Request-ID' header, falling back to an 8-character
    hexadecimal identifier if omitted. Binds the correlation ID to request.state,
    stores it in the ContextVar for downstream logging and Kombu AMQP dispatch,
    and echoes it in the outgoing response headers.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Process an incoming request and ensure correlation ID propagation.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            Response: Outgoing HTTP response with 'X-Request-ID' header attached.
        """
        # 1. Extract existing X-Request-ID or generate a clean 8-character UUID
        raw_header = request.headers.get("X-Request-ID")
        request_id = raw_header.strip() if raw_header and raw_header.strip() else uuid.uuid4().hex[:8]

        # 2. Attach correlation ID to request state
        request.state.request_id = request_id

        # 3. Bind to ContextVar for async propagation
        token: Token[str | None] = current_request_id.set(request_id)

        try:
            # 4. Invoke downstream middleware and application handlers
            response: Response = await call_next(request)
        finally:
            # 5. Guarantee ContextVar token reset on exit
            current_request_id.reset(token)

        # 6. Inject X-Request-ID into outgoing response headers
        response.headers["X-Request-ID"] = request_id
        return response
