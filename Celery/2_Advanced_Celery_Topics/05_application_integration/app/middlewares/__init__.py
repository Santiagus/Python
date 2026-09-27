"""Modular middlewares package for FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI

from app.middlewares.correlation import CorrelationMiddleware
from app.middlewares.error_handling import ErrorHandlingMiddleware
from app.middlewares.profiling import ProfilingMiddleware


def register_middlewares(app: FastAPI) -> None:
    """Register application middlewares in layered execution order.

    In Starlette/FastAPI, middlewares execute in reverse order of addition.
    Adding Profiling -> ErrorHandling -> Correlation ensures Correlation runs
    outermost (first to receive request, last to send response).

    Args:
        app: The FastAPI application instance.
    """
    app.add_middleware(ProfilingMiddleware)
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(CorrelationMiddleware)


__all__ = [
    "CorrelationMiddleware",
    "ErrorHandlingMiddleware",
    "ProfilingMiddleware",
    "register_middlewares",
]
