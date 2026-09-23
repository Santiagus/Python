"""FastAPI route dependencies for authentication, database sessions, and configuration.

Enforces enterprise M2M authentication via FastAPI Security dependencies (APIKeyHeader),
enabling automatic Swagger UI 'Authorize' button generation and declarative security.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session

logger = logging.getLogger(__name__)

# Enterprise API key header for OpenAPI 3.1 securitySchemes and Swagger Authorize modal
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Enterprise M2M API Key (format: sk_live_...)",
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an isolated asynchronous database session per request."""
    async for session in get_session():
        yield session


def get_app_settings() -> Settings:
    """Return cached application settings."""
    return get_settings()


async def verify_api_key(
    api_key: str | None = Security(api_key_header),
    settings: Settings = Depends(get_app_settings),
) -> str:
    """Authenticate incoming M2M requests via X-API-Key header.

    Args:
        api_key: Provided API key from request header.
        settings: Injected application settings.

    Returns:
        str: Validated API key string.

    Raises:
        HTTPException: 401 Unauthorized if key is missing or invalid.
    """
    # 1. Reject missing credentials
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required authentication header: X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # 2. Invariant: Validate key against configured secret
    if api_key != settings.api_key:
        logger.warning(
            "unauthorized_api_access_attempt",
            extra={"api_key_prefix": api_key[:7] if len(api_key) >= 7 else "short"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key credentials",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key


# Type aliases for clean FastAPI dependency injection in routes
DbSession = Annotated[AsyncSession, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
AuthenticatedUser = Annotated[str, Security(verify_api_key)]
