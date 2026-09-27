"""API Key authentication dependency using constant-time string comparison."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(
    api_key: Annotated[str | None, Security(_api_key_header)] = None,
) -> str:
    """Validate incoming X-API-Key header using constant-time comparison.

    Args:
        api_key: Extracted X-API-Key header value from the HTTP request.

    Returns:
        str: Validated API key string.

    Raises:
        HTTPException: HTTP 401 Unauthorized if key is missing or invalid.
    """
    settings = get_settings()
    configured_key = settings.api_key_secret

    # Constant-time comparison against configured API key
    if not api_key or not hmac.compare_digest(api_key.strip(), configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_key
