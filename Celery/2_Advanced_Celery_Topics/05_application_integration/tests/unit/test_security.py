"""Unit tests for API key authentication security dependency."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, status

from app.config import Settings
from app.security import get_api_key


@pytest.mark.asyncio
async def test_get_api_key_valid() -> None:
    """Verify get_api_key succeeds with valid configured key."""
    settings = Settings(api_key_secret="test_secret_key_123")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.security.get_settings", lambda: settings)
        key = await get_api_key("test_secret_key_123")
        assert key == "test_secret_key_123"

        # Key with leading/trailing whitespace
        key_ws = await get_api_key("  test_secret_key_123  ")
        assert key_ws == "  test_secret_key_123  "


@pytest.mark.asyncio
async def test_get_api_key_invalid() -> None:
    """Verify get_api_key raises HTTP 401 on invalid key."""
    settings = Settings(api_key_secret="test_secret_key_123")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await get_api_key("wrong_secret_key")

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid or missing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_api_key_missing_or_none() -> None:
    """Verify get_api_key raises HTTP 401 when key is missing or None."""
    settings = Settings(api_key_secret="test_secret_key_123")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.security.get_settings", lambda: settings)
        with pytest.raises(HTTPException) as exc_info:
            await get_api_key(None)

        assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid or missing" in exc_info.value.detail
