"""Unit tests for Result Envelope degradation and Celery errbacks (TC-05, TC-08)."""

from unittest.mock import MagicMock, patch

import httpx
from services.worker.tasks.screening import check_aml_watchlist, handle_screening_failure


def test_check_aml_watchlist_clean_entity() -> None:
    """TC-05: Verify check_aml_watchlist produces clean approved envelope when no matches exist."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "entity_name": "Safe Enterprise Inc",
        "matches": [],
        "is_sanctioned": False,
    }

    with patch("services.worker.tasks.screening.get_shared_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_aml_watchlist.apply(
            args=["11223344-5566-7788-99aa-bbccddeeff00", "Safe Enterprise Inc", 15]
        ).result

    assert result["status"] == "ok"
    assert result["is_sanctioned"] is False
    assert result["matches"] == []
    assert result["decision"] == "approved"
    assert result["risk_score"] == 15


def test_check_aml_watchlist_clean_entity_with_high_upstream_score() -> None:
    """TC-05: Verify clean sanctions check with high upstream score remains flagged_review."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "entity_name": "Clean But Risky LLC",
        "matches": [],
        "is_sanctioned": False,
    }

    with patch("services.worker.tasks.screening.get_shared_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_aml_watchlist.apply(
            args=["11223344-5566-7788-99aa-bbccddeeff00", "Clean But Risky LLC", 60]
        ).result

    assert result["status"] == "ok"
    assert result["is_sanctioned"] is False
    assert result["decision"] == "flagged_review"
    assert result["risk_score"] == 60


def test_check_aml_watchlist_positive_match_blocked() -> None:
    """TC-05: Verify high confidence watchlist match triggers blocked decision."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "entity_name": "VLADIMIR ROSTOV",
        "matches": [
            {
                "entity_name": "VLADIMIR ROSTOV",
                "watchlist_type": "OFAC_SDN",
                "match_confidence": 99.20,
            }
        ],
        "is_sanctioned": True,
    }

    with patch("services.worker.tasks.screening.get_shared_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_aml_watchlist.apply(
            args=["11223344-5566-7788-99aa-bbccddeeff00", "VLADIMIR ROSTOV", 20]
        ).result

    assert result["status"] == "ok"
    assert result["is_sanctioned"] is True
    assert result["decision"] == "blocked"
    assert result["risk_score"] == 95


def test_check_aml_watchlist_lower_confidence_flagged() -> None:
    """TC-05: Verify lower confidence match (<98%) triggers flagged_review rather than blocked."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "entity_name": "Carlos Mendez",
        "matches": [
            {
                "entity_name": "CARLOS MENDEZ",
                "watchlist_type": "PEP",
                "match_confidence": 92.00,
            }
        ],
        "is_sanctioned": True,
    }

    with patch("services.worker.tasks.screening.get_shared_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = check_aml_watchlist.apply(
            args=["11223344-5566-7788-99aa-bbccddeeff00", "Carlos Mendez", 10]
        ).result

    assert result["status"] == "ok"
    assert result["decision"] == "flagged_review"
    assert result["risk_score"] == 95


def test_check_aml_watchlist_timeout_degradation() -> None:
    """TC-05: Assert timeout synthesizes degraded Result Envelope with fallback score."""
    with patch("services.worker.tasks.screening.get_shared_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Connection timed out after 2.0s")
        mock_client_factory.return_value = mock_client

        result = check_aml_watchlist.apply(
            args=["11223344-5566-7788-99aa-bbccddeeff00", "Slow Partner Corp", 10]
        ).result

    assert result["status"] == "degraded"
    assert result["is_sanctioned"] is False
    assert result["decision"] == "flagged_review"
    assert result["fallback_score"] == 40
    assert "aml_watchlist_timeout" in result["reasons"]
    assert len(result["errors"]) == 1


def test_check_aml_watchlist_http_error_degradation() -> None:
    """TC-05: Assert HTTP 500 error synthesizes degraded Result Envelope."""
    mock_request = httpx.Request("POST", "http://localhost:8015/api/v1/watchlists/check")
    mock_response = httpx.Response(500, request=mock_request)

    with patch("services.worker.tasks.screening.get_shared_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Internal Server Error", request=mock_request, response=mock_response
        )
        mock_client_factory.return_value = mock_client

        result = check_aml_watchlist.apply(
            args=["11223344-5566-7788-99aa-bbccddeeff00", "Error Partner Corp", 10]
        ).result

    assert result["status"] == "degraded"
    assert result["fallback_score"] == 40


def test_handle_screening_failure_errback() -> None:
    """TC-08: Verify Celery link_error errback produces failure audit envelope."""
    exc = RuntimeError("Database deadlock detected during transaction commit")
    result = handle_screening_failure.apply(
        args=[
            None,
            exc,
            "Traceback (most recent call last)...",
            "11223344-5566-7788-99aa-bbccddeeff00",
        ]
    ).result

    assert result["status"] == "failed"
    assert result["screening_id"] == "11223344-5566-7788-99aa-bbccddeeff00"
    assert "Database deadlock" in result["error"]
    assert result["decision"] == "failed"
    assert result["decision_reason"] == "fatal_worker_error"


def test_get_shared_client_singleton() -> None:
    """Verify get_shared_client returns the singleton httpx.Client instance."""
    from services.worker.tasks.screening import get_shared_client

    client = get_shared_client()
    assert isinstance(client, httpx.Client)


def test_check_aml_watchlist_with_dict_payload() -> None:
    """TC-05: Verify check_aml_watchlist unpacks upstream dictionary payload in canvas chain."""
    upstream_payload = {
        "status": "ok",
        "screening_id": "11223344-5566-7788-99aa-bbccddeeff00",
        "entity_name": "Dict Entity Corp",
        "risk_score": 15,
    }
    with patch("services.worker.tasks.screening.get_shared_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"is_sanctioned": False, "matches": []}
        mock_resp.raise_for_status.return_value = None
        mock_client.post.return_value = mock_resp
        mock_client_factory.return_value = mock_client

        result = check_aml_watchlist.apply(args=[upstream_payload]).result

    assert result["status"] == "ok"
    assert result["screening_id"] == "11223344-5566-7788-99aa-bbccddeeff00"
    assert result["risk_score"] == 15
    assert result["decision"] == "approved"
