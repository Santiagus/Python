"""Profiling middleware recording HTTP latency and Prometheus metrics.

Measures elapsed milliseconds per request and increments Prometheus counters and histograms.
"""

import time
from collections.abc import Callable

from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total incoming HTTP API requests partitioned by route and status",
    ["method", "endpoint", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request execution latency in seconds",
    ["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
)


class ProfilingMiddleware(BaseHTTPMiddleware):
    """Middleware tracking request duration and recording Prometheus telemetry."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Measure elapsed request duration and update telemetry metrics.

        Args:
            request: Incoming Starlette/FastAPI request.
            call_next: Downstream ASGI handler.

        Returns:
            Response: Outgoing response with X-Process-Time-Ms header.
        """
        start_time = time.perf_counter()
        endpoint = request.url.path
        method = request.method

        try:
            response = await call_next(request)
            status_code = str(response.status_code)
        except Exception:
            status_code = "500"
            raise
        finally:
            duration = time.perf_counter() - start_time
            duration_ms = duration * 1000.0

            # 1. Update Prometheus counter and histogram
            HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status=status_code).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)

        # 2. Attach execution time header in milliseconds
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response
