"""Centralized error handling and structured request duration logging middleware.

Catches unhandled server exceptions, logs full tracebacks with request correlation context,
and returns sanitized 500 JSON responses while profiling execution latency.
"""

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger("app.middlewares.error_handling")


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Traps unhandled server exceptions, logs durations, and emits standardized 500 JSON payloads."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Wrap request execution in exception handler and performance profiler.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler in the chain.

        Returns:
            Response: Route response or standardized JSON error response.
        """
        # 1. Resolve request correlation ID if previously attached
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID", "unknown")
        start_time = time.perf_counter()

        try:
            # 2. Invoke downstream request processing
            response: Response = await call_next(request)
        except Exception as exc:
            # 3. Trap unhandled exceptions and log full traceback
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.exception(
                "unhandled_request_error",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
            )
            # 4. Return sanitized RFC 7807 compatible 500 response
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "request_id": request_id,
                },
            )

        # 5. Measure duration and ensure X-Request-ID header is present
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = request_id

        # 6. Log completion metric or warning based on status code
        log_extra = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }
        if response.status_code >= 400:
            logger.warning("request_error", extra=log_extra)
        else:
            logger.info("request_complete", extra=log_extra)

        return response
