"""Modular middleware package for HTTP interceptors and request lifecycles.

Exports individual middleware classes and a unified `register_middlewares(app)`
helper enforcing deterministic LIFO execution order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

from app.middlewares.correlation import CorrelationIdMiddleware
from app.middlewares.error_handling import ErrorHandlingMiddleware
from app.middlewares.profiling import ProfilingMiddleware
from app.middlewares.security import SecurityHeadersMiddleware

__all__ = [
    "CorrelationIdMiddleware",
    "ErrorHandlingMiddleware",
    "ProfilingMiddleware",
    "SecurityHeadersMiddleware",
    "register_middlewares",
]


def register_middlewares(app: FastAPI) -> None:
    """Register all application middlewares in deterministic execution order.

    In Starlette, middlewares wrap in Last-In First-Out (LIFO) order.
    The LAST middleware added via `app.add_middleware` is the FIRST to receive the request.

    Inbound Execution Order:
      1. CorrelationIdMiddleware   (Extracts/generates X-Request-ID, binds ContextVar)
      2. SecurityHeadersMiddleware (Passes inbound; sets headers outbound)
      3. ErrorHandlingMiddleware   (Shields and catches downstream exceptions)
      4. ProfilingMiddleware       (Starts timer, logs completion)
      5. Route Handlers
    """
    app.add_middleware(ProfilingMiddleware)
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CorrelationIdMiddleware)
