"""Request profiling, latency measurement, and performance instrumentation middleware.

Measures high-resolution wall-clock duration (duration_ms), emits structured lifecycle
logs, and provides an extension hook for APM tools, profilers, and SLA violation alerts.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Configurable SLA warning threshold (e.g. alert if an API call exceeds 100ms)
SLA_WARNING_THRESHOLD_MS: float = 100.0


class ProfilingMiddleware(BaseHTTPMiddleware):
    """Measures end-to-end request latency and logs structured performance metrics."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Record high-resolution request execution duration and emit performance metrics."""
        request_id = getattr(request.state, "request_id", "unknown")
        start_time = time.perf_counter()

        # =========================================================================
        # PROFILER EXTENSION HOOK (PLACEHOLDER)
        # =========================================================================
        # To enable deep CPU/memory profiling (e.g., cProfile, Py-Spy, or OpenTelemetry),
        # initialize profiler contexts or tracer spans here before calling downstream:
        #
        # profiler = cProfile.Profile()
        # profiler.enable()
        # =========================================================================

        response: Response = await call_next(request)

        # 1. Compute high-resolution elapsed duration in milliseconds
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Response-Time-Ms"] = str(duration_ms)

        # =========================================================================
        # PROFILER DUMP HOOK (PLACEHOLDER)
        # =========================================================================
        # If profiling was active, disable and export stats to APM collector:
        #
        # profiler.disable()
        # if duration_ms > SLA_WARNING_THRESHOLD_MS:
        #     profiler.dump_stats(f"profiles/{request_id}.prof")
        # =========================================================================

        # 2. Check for SLA threshold violations on real-time routes
        if duration_ms > SLA_WARNING_THRESHOLD_MS:
            logger.warning(
                "sla_latency_warning",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "threshold_ms": SLA_WARNING_THRESHOLD_MS,
                },
            )

        # 3. Emit structured request completion log event
        log_event = "request_complete" if response.status_code < 400 else "request_error"
        logger.info(
            log_event,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        return response

