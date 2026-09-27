"""Middlewares package providing unified registration for FastAPI applications."""

from fastapi import FastAPI

from app.middlewares.correlation import CorrelationIdMiddleware
from app.middlewares.error_handling import ErrorHandlingMiddleware
from app.middlewares.profiling import ProfilingMiddleware


def register_middlewares(app: FastAPI) -> None:
    """Register all modular application middlewares in proper execution order.

    Order of registration:
    1. ErrorHandlingMiddleware (outermost: intercepts any unhandled exception)
    2. ProfilingMiddleware (measures total wall-clock duration)
    3. CorrelationIdMiddleware (innermost: binds request correlation ID)

    Args:
        app: Target FastAPI application instance.
    """
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(ProfilingMiddleware)
    app.add_middleware(CorrelationIdMiddleware)


__all__ = [
    "CorrelationIdMiddleware",
    "ErrorHandlingMiddleware",
    "ProfilingMiddleware",
    "register_middlewares",
]
