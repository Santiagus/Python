"""Pytest configuration and global test fixtures for the Failure Recovery Lab."""

from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def workspace_root() -> Path:
    """Provide the absolute path to the workspace root directory."""
    return WORKSPACE_ROOT


@pytest.fixture(scope="session")
def init_sql_content(workspace_root: Path) -> str:
    """Read and provide the contents of init.sql."""
    init_sql_path = workspace_root / "init.sql"
    return init_sql_path.read_text(encoding="utf-8")
