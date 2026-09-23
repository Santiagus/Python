"""Inbound HTTP client rate limiting and traffic throttling middleware.

Protects the API gateway from Denial of Service (DoS) and abusive client polling.
Supports atomic distributed token-bucket rate limiting via Redis Lua scripts with
automatic graceful fallback to an in-memory sliding window when Redis is offline.
"""

from __future__ import annotations

from collections import defaultdict
import logging
import math
import time
from typing import Any

from fastapi import Request
import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.config import get_settings

logger = logging.getLogger(__name__)

# Default inbound rate limit configuration baseline
DEFAULT_REQUESTS_PER_MINUTE: int = 600

# Redis Lua Token-Bucket Algorithm (Atomic execution across distributed pods)
LUA_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if tokens == nil then
    tokens = capacity
    last_updated = now
else
    local elapsed = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + elapsed * refill_rate)
    last_updated = now
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
    local ttl = math.max(120, math.ceil(capacity / math.max(refill_rate, 0.001) * 2))
    redis.call('EXPIRE', key, ttl)
    return {1, math.floor(tokens), 0}
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_updated', last_updated)
    local ttl = math.max(120, math.ceil(capacity / math.max(refill_rate, 0.001) * 2))
    redis.call('EXPIRE', key, ttl)
    local missing = requested - tokens
    local retry_after = math.max(1, math.ceil(missing / math.max(refill_rate, 0.001)))
    return {0, math.floor(tokens), retry_after}
end
"""


class HttpRateLimitMiddleware(BaseHTTPMiddleware):
    """Inbound HTTP traffic throttle guarding API endpoints from client saturation.

    =============================================================================
    ARCHITECTURAL DISTINCTION: INBOUND API vs OUTBOUND CELERY RATE LIMITING
    =============================================================================
    1. INBOUND RATE LIMITING (This Middleware):
       - Location: FastAPI HTTP Gateway (`app/middlewares/rate_limit.py`).
       - Purpose: Protects web servers from malicious clients, script loops, or
         abusive polling. Rejects traffic with HTTP 429 Too Many Requests.
       - Implementation: Distributed Redis Lua token-bucket algorithm with local fallback.

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
        redis_client: aioredis.Redis | None = None,
        redis_url: str | None = None,
    ):
        """Initialize HTTP rate limiting middleware.

        Args:
            app: ASGI application instance.
            requests_per_minute: Requests allowed per 60-second window.
            rate_per_minute: Explicit RPM alias.
            burst_capacity: Maximum token bucket size (burst allowance).
            redis_client: Optional pre-configured Redis client.
            redis_url: Optional Redis URL string.
        """
        super().__init__(app)
        self.rpm = rate_per_minute if rate_per_minute is not None else requests_per_minute
        self.capacity = burst_capacity if burst_capacity is not None else self.rpm
        self.refill_rate = self.rpm / 60.0  # tokens per second
        self._history: dict[str, list[float]] = defaultdict(list)
        self._redis_client = redis_client
        self._redis_url = redis_url
        self._redis_script_sha: str | None = None
        self._use_redis = True

    def _get_redis(self) -> aioredis.Redis | None:
        """Return initialized Redis client or None if unconfigured/disabled."""
        if not self._use_redis:
            return None
        if self._redis_client is None:
            settings = get_settings()
            url = self._redis_url or settings.redis_url
            if not url or settings.environment in ("test", "testing"):
                self._use_redis = False
                return None
            try:
                self._redis_client = aioredis.from_url(
                    url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_timeout=1.0,
                    socket_connect_timeout=1.0,
                )
            except Exception as exc:
                logger.warning("redis_rate_limiter_init_failed", extra={"error": str(exc)})
                self._use_redis = False
                return None
        return self._redis_client

    async def _check_redis(self, client_ip: str, now: float) -> tuple[bool, int, int] | None:
        """Execute atomic Redis token bucket Lua script."""
        redis = self._get_redis()
        if redis is None:
            return None

        key = f"ratelimit:{client_ip}"
        try:
            res = await redis.eval(
                LUA_TOKEN_BUCKET_SCRIPT,
                1,
                key,
                str(self.capacity),
                str(self.refill_rate),
                str(now),
                "1",
            )
            allowed = bool(res[0] == 1)
            remaining = int(res[1])
            retry_after = int(res[2])
            return allowed, remaining, retry_after
        except Exception as exc:
            logger.debug("redis_rate_limit_eval_fallback", extra={"error": str(exc), "client_ip": client_ip})
            return None

    def _check_in_memory(self, client_ip: str, now: float) -> tuple[bool, int, int]:
        """Sliding-window in-memory fallback counter."""
        cutoff = now - 60.0
        self._history[client_ip] = [ts for ts in self._history[client_ip] if ts > cutoff]

        if len(self._history[client_ip]) >= self.capacity:
            return False, 0, 60

        self._history[client_ip].append(now)
        remaining = max(0, self.rpm - len(self._history[client_ip]))
        return True, remaining, 0

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Evaluate client rate limit budget before executing downstream routes."""
        if self.capacity <= 0:
            response: Response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = "unlimited"
            response.headers["X-RateLimit-Remaining"] = "unlimited"
            return response

        client_ip = request.client.host if request.client else "unknown"
        request_id = getattr(request.state, "request_id", "unknown")
        now = time.time()

        # 1. Try distributed Redis token bucket first
        redis_res = await self._check_redis(client_ip, now)
        if redis_res is not None:
            allowed, remaining, retry_after = redis_res
        else:
            # 2. Fall back to process-local in-memory sliding window
            allowed, remaining, retry_after = self._check_in_memory(client_ip, now)

        # 3. Reject with HTTP 429 if budget exhausted
        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "client_ip": client_ip,
                    "request_id": request_id,
                    "capacity": self.capacity,
                    "retry_after": retry_after,
                },
            )
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after), "X-Request-ID": request_id},
            )

        # 4. Proceed downstream
        response = await call_next(request)

        # Standard rate limit telemetry headers
        response.headers["X-RateLimit-Limit"] = str(self.rpm)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        return response


# Backward-compatible alias
RateLimitMiddleware = HttpRateLimitMiddleware

