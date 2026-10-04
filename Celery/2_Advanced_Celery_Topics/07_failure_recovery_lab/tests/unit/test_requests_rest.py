"""Unit tests validating the syntax and structure of requests/requests.rest."""

import os
import re

import pytest


@pytest.fixture
def requests_rest_content() -> str:
    """Read the contents of requests/requests.rest."""
    file_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "requests",
        "requests.rest",
    )
    assert os.path.exists(file_path), f"File not found: {file_path}"
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def test_requests_rest_file_exists_and_declares_variables(
    requests_rest_content: str,
) -> None:
    """Verify that requests.rest defines baseUrl, apiPrefix, and bankUrl variables."""
    assert "@baseUrl = http://localhost:8000" in requests_rest_content
    assert "@apiPrefix = /api/v1" in requests_rest_content
    assert "@bankUrl = http://localhost:8010" in requests_rest_content


def test_requests_rest_contains_health_and_ready_scenarios(
    requests_rest_content: str,
) -> None:
    """Verify system health and readiness probe endpoints."""
    assert "GET {{baseUrl}}/health" in requests_rest_content
    assert "GET {{baseUrl}}/ready" in requests_rest_content
    assert "GET {{bankUrl}}/health" in requests_rest_content
    assert "GET {{bankUrl}}/ready" in requests_rest_content


def test_requests_rest_contains_happy_path_workflow(
    requests_rest_content: str,
) -> None:
    """Verify happy path ingestion, named request, and variable chaining."""
    assert "# @name ingestWireHappyPath" in requests_rest_content
    assert "POST {{baseUrl}}{{apiPrefix}}/wires" in requests_rest_content
    assert "Idempotency-Key: idem-treasury-2026-alpha-001" in requests_rest_content
    assert "X-Request-ID: req-client-treasury-001" in requests_rest_content
    assert (
        "GET {{baseUrl}}{{apiPrefix}}/wires/{{ingestWireHappyPath.response.body.wire_id}}"
        in requests_rest_content
    )


def test_requests_rest_contains_idempotency_and_auto_key_workflows(
    requests_rest_content: str,
) -> None:
    """Verify idempotency replay and auto-generated key workflows."""
    assert "# @name ingestAutoIdemWire" in requests_rest_content
    assert (
        "GET {{baseUrl}}{{apiPrefix}}/wires/{{ingestAutoIdemWire.response.body.wire_id}}"
        in requests_rest_content
    )
    assert "idem-treasury-2026-alpha-001" in requests_rest_content


def test_requests_rest_contains_validation_and_error_scenarios(
    requests_rest_content: str,
) -> None:
    """Verify invalid routing number, negative amount, and 404 query test scenarios."""
    assert '"routing_number": "1234"' in requests_rest_content
    assert '"amount": "-500.00"' in requests_rest_content
    assert (
        "GET {{baseUrl}}{{apiPrefix}}/wires/00000000-0000-0000-0000-000000000000"
        in requests_rest_content
    )


def test_requests_rest_request_blocks_syntax(
    requests_rest_content: str,
) -> None:
    """Verify that requests.rest request blocks are separated by ### delimiters."""
    blocks = re.split(r"^###\s*$", requests_rest_content, flags=re.MULTILINE)
    # The file has a header block followed by multiple delimited request blocks
    assert len(blocks) >= 8
    for block in blocks[1:]:
        stripped = block.strip()
        assert any(
            stripped.startswith(method)
            or (stripped.startswith("#") and any(f"\n{method}" in stripped for method in ["GET", "POST"]))
            for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]
        )
