"""Modular middlewares package for HTTP interceptors and request lifecycles.

Exports individual middleware classes and a unified `register_middlewares(app)`
helper enforcing the exact, deterministic execution order of the middleware stack.

Enterprise 5-Layer Middleware Pipeline:
1. CorrelationIdMiddleware  (Trace context & ContextVar lifecycle)
2. SecurityHeadersMiddleware(HSTS, CSP, X-Frame-Options, nosniff)
3. ErrorHandlingMiddleware  (Unhandled exception shielding & JSON 500 normalization)
4. HttpRateLimitMiddleware  (Inbound HTTP client rate limiting & 429 throttling)
5. ProfilingMiddleware      (High-resolution latency timing & APM hooks)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

from .correlation import CorrelationIdMiddleware
from .error_handling import ErrorHandlingMiddleware
from .profiling import ProfilingMiddleware
from .rate_limit import HttpRateLimitMiddleware
from .security import SecurityHeadersMiddleware

__all__ = [
    "CorrelationIdMiddleware",
    "ErrorHandlingMiddleware",
    "HttpRateLimitMiddleware",
    "ProfilingMiddleware",
    "SecurityHeadersMiddleware",
    "register_middlewares",
]


def register_middlewares(app: FastAPI, requests_per_minute: int | None = None) -> None:
    """Register all application middlewares in the correct, deterministic execution order.

    Note on Starlette/FastAPI Middleware Execution Order:
    In Starlette, middlewares wrap around the application in a Last-In, First-Out (LIFO) stack.
    The LAST middleware added via `app.add_middleware()` is the FIRST to receive the incoming request!

    Inbound Request Flow:
    Client Request
      ↳ 1. CorrelationIdMiddleware  (Extracts/generates X-Request-ID, binds ContextVar)
        ↳ 2. SecurityHeadersMiddleware(Pass-through inbound; injects defensive headers outbound)
          ↳ 3. ErrorHandlingMiddleware  (Enters outer try/except block to catch downstream errors)
            ↳ 4. HttpRateLimitMiddleware  (Checks client token budget; returns 429 if exceeded)
              ↳ 5. ProfilingMiddleware      (Starts high-res clock; measures true route duration)
                ↳ Route Handler             (Executes FastAPI endpoints & business logic)

    Outbound Response Flow:
    Route Handler
      ↳ 5. ProfilingMiddleware      (Stops clock, computes duration_ms, logs request_complete)
        ↳ 4. HttpRateLimitMiddleware  (Attaches rate-limit telemetry headers)
          ↳ 3. ErrorHandlingMiddleware  (Normalizes uncaught crashes to JSON 500)
            ↳ 2. SecurityHeadersMiddleware(Injects HSTS, CSP, nosniff, X-Frame-Options headers)
              ↳ 1. CorrelationIdMiddleware  (Attaches X-Request-ID header, resets ContextVar token)
                ↳ Client Response
    """
    # Added 1st -> Innermost wrapper around the route handler: Profiling
    app.add_middleware(ProfilingMiddleware)

    # Added 2nd -> Rate limiting: Protects route and profiler from abusive traffic
    from app.config import get_settings
    settings = get_settings()
    rpm = requests_per_minute if requests_per_minute is not None else settings.rate_limit_rpm
    app.add_middleware(HttpRateLimitMiddleware, requests_per_minute=rpm)

    # Added 3rd -> Error handling: Catches unhandled exceptions escaping downstream layers
    app.add_middleware(ErrorHandlingMiddleware)

    # Added 4th -> Security headers: Guarantees security headers on all responses
    app.add_middleware(SecurityHeadersMiddleware)

    # Added 5th -> Outermost wrapper on inbound: Establishes correlation ID first
    app.add_middleware(CorrelationIdMiddleware)
