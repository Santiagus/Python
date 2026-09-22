"""Inbound HTTP client rate limiting and traffic throttling middleware.

Protects the API gateway from Denial of Service (DoS) and abusive client polling.
Provides extension hooks for distributed Redis token-bucket or sliding-window algorithms.
"""

from __future__ import annotations

import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from collections import defaultdict
import time

logger = logging.getLogger(__name__)

# Default inbound rate limit configuration baseline
DEFAULT_REQUESTS_PER_MINUTE: int = 600


class HttpRateLimitMiddleware(BaseHTTPMiddleware):
    """Inbound HTTP traffic throttle guarding API endpoints from client saturation.

    =============================================================================
    ARCHITECTURAL DISTINCTION: INBOUND API vs OUTBOUND CELERY RATE LIMITING
    =============================================================================
    1. INBOUND RATE LIMITING (This Middleware):
       - Location: FastAPI HTTP Gateway (`app/middlewares/rate_limit.py`).
       - Purpose: Protects our web servers from malicious clients, script loops, or
         abusive polling. Rejects traffic with HTTP 429 Too Many Requests.
       - Implementation: In-memory sliding-window counter per client IP (with Redis hook).

    2. OUTBOUND RATE LIMITING (Celery Worker Tasks):
       - Location: Celery Worker (`services/worker/tasks/`).
       - Purpose: Protects external third-party banking APIs (e.g. FedNow/ACH rails)
         from being flooded during bulk sweeps.
       - Implementation: Celery's native `rate_limit="500/m"` token-bucket algorithm.
    =============================================================================
    """

    def __init__(
        self,
        app,
        requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE,
        rate_per_minute: int | None = None,
        burst_capacity: int | None = None,
    ):
        super().__init__(app)
        self.rpm = rate_per_minute if rate_per_minute is not None else requests_per_minute
        self.capacity = burst_capacity if burst_capacity is not None else self.rpm
        self._history: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Evaluate client rate limit budget before executing downstream routes."""
        if self.capacity <= 0:
            response: Response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = "unlimited"
            response.headers["X-RateLimit-Remaining"] = "unlimited"
            return response

        client_ip = request.client.host if request.client else "unknown"
        request_id = getattr(request.state, "request_id", "unknown")
        now = time.monotonic()

        # 1. Clean history older than 60 seconds
        cutoff = now - 60.0
        self._history[client_ip] = [ts for ts in self._history[client_ip] if ts > cutoff]

        # 2. Check if client exceeded limit
        if len(self._history[client_ip]) >= self.capacity:
            logger.warning(
                "rate_limit_exceeded",
                extra={"client_ip": client_ip, "request_id": request_id, "capacity": self.capacity},
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "retry_after": 60},
                headers={"Retry-After": "60", "X-Request-ID": request_id},
            )

        # 3. Record current timestamp
        self._history[client_ip].append(now)
        remaining = max(0, self.rpm - len(self._history[client_ip]))

        # 4. Proceed downstream
        response: Response = await call_next(request)

        # Standard rate limit telemetry headers
        response.headers["X-RateLimit-Limit"] = str(self.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response

