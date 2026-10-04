"""Modular middleware package for correlation tracking and error handling.

Provides unified registration for request correlation tracking and RFC 7807 compatible
centralized error handling across the FastAPI Ingestion Gateway.
"""

from fastapi import FastAPI

from app.middlewares.correlation import (
    CorrelationMiddleware,
    current_request_id,
    get_current_request_id,
)
from app.middlewares.error_handling import ErrorHandlingMiddleware


def register_middlewares(app: FastAPI) -> None:
    """Register application middlewares in outer-to-inner execution order.

    In Starlette and FastAPI, middlewares execute in reverse order of addition.
    ErrorHandlingMiddleware is registered first, followed by CorrelationMiddleware,
    guaranteeing that incoming requests enter CorrelationMiddleware first so that
    request_id is initialized before downstream error handling and route dispatch.

    Args:
        app: The FastAPI application instance to configure.
    """
    # 1. Register inner error handling middleware
    app.add_middleware(ErrorHandlingMiddleware)

    # 2. Register outer correlation middleware
    app.add_middleware(CorrelationMiddleware)


__all__ = [
    "CorrelationMiddleware",
    "ErrorHandlingMiddleware",
    "current_request_id",
    "get_current_request_id",
    "register_middlewares",
]
