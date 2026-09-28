"""Unit test fixtures and auto-mocking configurations.

Provides automatic mocking of database persistence calls in Celery tasks
to ensure pure in-memory execution and sub-second runtimes for unit tests.
"""

from collections.abc import Generator
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def mock_worker_persistence(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Auto-mock database persistence functions for unit tests unless explicitly opted out."""
    if (
        "no_mock_persistence" in request.keywords
        or "test_screening_persistence" in request.node.nodeid
    ):
        yield
        return

    with (
        patch("services.worker.tasks.screening._persist_screening", return_value=None),
        patch("services.worker.tasks.screening._persist_failure", return_value=None),
    ):
        yield
