"""Unit tests for FastAPI main entry point and lifespan lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

import app.main as main_mod
from app.config import Settings


@pytest.mark.asyncio
async def test_lifespan_prewarm_success() -> None:
    """Verify lifespan successfully pre-warms database pool and calls close_db on exit."""
    mock_conn = AsyncMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__aenter__.return_value = mock_conn

    test_settings = Settings(
        environment="development",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
    )

    with (
        patch("app.main.get_settings", return_value=test_settings),
        patch("app.main.get_engine", return_value=mock_engine),
        patch("app.main.close_db", new_callable=AsyncMock) as mock_close,
    ):
        mock_app = MagicMock(spec=FastAPI)
        async with main_mod.lifespan(mock_app):
            assert mock_conn.execute.called

        assert mock_close.called


@pytest.mark.asyncio
async def test_lifespan_prewarm_failure_handled_gracefully() -> None:
    """Verify lifespan handles pre-warm connection failures without crashing startup."""
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = RuntimeError("database unreachable")

    test_settings = Settings(
        environment="production",
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/test_db",
    )

    with (
        patch("app.main.get_settings", return_value=test_settings),
        patch("app.main.get_engine", return_value=mock_engine),
        patch("app.main.close_db", new_callable=AsyncMock) as mock_close,
    ):
        mock_app = MagicMock(spec=FastAPI)
        async with main_mod.lifespan(mock_app):
            pass

        assert mock_close.called


def test_create_app() -> None:
    """Verify create_app instantiates FastAPI with routes and documentation metadata."""
    app = main_mod.create_app()
    assert app.title == "Card Dispute & Chargeback Engine"
    assert len(app.routes) > 0
