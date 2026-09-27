"""Unit tests for automated SRE incident walkthrough simulation script (TC-22)."""

from unittest.mock import MagicMock, patch

from scripts.incident_walkthrough import main as incident_main
from scripts.incident_walkthrough import run_walkthrough


def test_incident_walkthrough_happy_path() -> None:
    """Verify run_walkthrough executes all stages, from fault injection to recovery."""
    mock_client = MagicMock()

    # Pre-flight responses
    mock_live = MagicMock(status_code=200)
    mock_live.json.return_value = {"status": "alive"}

    mock_sanctions_health = MagicMock(status_code=200)
    mock_sanctions_health.json.return_value = {"status": "healthy"}

    mock_metrics = MagicMock(status_code=200, content=b"# HELP http_requests_total\n")

    # Fault injection response
    mock_fault = MagicMock(status_code=200)
    mock_fault.json.return_value = {"failure_mode": {"enabled": True, "status_code": 504}}

    # Ingestion responses
    mock_ingest = MagicMock(status_code=202)
    mock_ingest.json.return_value = {
        "id": "11223344-5566-7788-99aa-bbccddeeff00",
        "status": "processing",
    }

    # In-flight poll response (processing -> flagged_review)
    mock_poll_1 = MagicMock(status_code=200)
    mock_poll_1.json.return_value = {
        "id": "11223344-5566-7788-99aa-bbccddeeff00",
        "status": "processing",
    }

    mock_poll_2 = MagicMock(status_code=200)
    mock_poll_2.json.return_value = {
        "id": "11223344-5566-7788-99aa-bbccddeeff00",
        "status": "flagged_review",
    }

    # Clear fault injection response
    mock_clear = MagicMock(status_code=200)
    mock_clear.json.return_value = {"failure_mode": {"enabled": False}}

    # Post-incident recovery response
    mock_rec = MagicMock(status_code=202)
    mock_rec.json.return_value = {
        "id": "22334455-6677-8899-aabb-ccddeeff0011",
        "status": "processing",
    }

    mock_client.get.side_effect = [
        mock_live,
        mock_sanctions_health,
        mock_metrics,
        mock_poll_1,
        mock_poll_2,
        mock_metrics,
    ]
    mock_client.post.side_effect = [
        mock_fault,
        mock_ingest,
        mock_clear,
        mock_rec,
    ]

    with patch("httpx.Client", return_value=mock_client), patch("time.sleep"):
        success = run_walkthrough()
        assert success is True


def test_incident_walkthrough_preflight_failure() -> None:
    """Verify run_walkthrough aborts cleanly if pre-flight health check fails."""
    mock_client = MagicMock()
    mock_client.get.side_effect = RuntimeError("Connection refused")

    with patch("httpx.Client", return_value=mock_client):
        success = run_walkthrough()
        assert success is False


def test_incident_main_cli() -> None:
    """Verify incident_walkthrough CLI main() maps boolean result to process exit codes."""
    with patch("scripts.incident_walkthrough.run_walkthrough", return_value=True):
        with patch("sys.argv", ["incident_walkthrough.py"]):
            assert incident_main() == 0

    with patch("scripts.incident_walkthrough.run_walkthrough", return_value=False):
        with patch("sys.argv", ["incident_walkthrough.py"]):
            assert incident_main() == 1
