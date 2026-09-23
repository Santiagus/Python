"""Integration tests for Partner Bank Simulator API and BankSimulatorClient."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
import pytest

from services.bank_simulator_api.client import BankClearingError, BankSimulatorClient
from services.bank_simulator_api.client import (
    BankClearingError,
    BankSimulatorClient,
    close_bank_client,
    get_bank_simulator_client,
    init_bank_client,
)
from services.bank_simulator_api.main import app as bank_app


@pytest.mark.integration
class TestBankSimulatorEndpoints:
    """Test mock bank endpoints, clearing rails, and fault injection."""

    @pytest.mark.asyncio
    async def test_bank_simulator_health(self) -> None:
        """Health check returns healthy."""
        transport = ASGITransport(app=bank_app)
        async with AsyncClient(transport=transport, base_url="http://bank") as client:
            res = await client.get("/health")
            assert res.status_code == 200
            assert res.json()["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_instant_clearing_happy_path(self) -> None:
        """Instant clearing generates authoritative reference number."""
        transport = ASGITransport(app=bank_app)
        async with AsyncClient(transport=transport, base_url="http://bank") as client:
            pid = str(uuid4())
            payload = {
                "payment_id": pid,
                "amount_cents": 50000,
                "rail": "rtp",
                "destination_account_number": "12345678",
                "destination_routing_number": "021000021",
            }
            res = await client.post("/clearing/instant", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "settled"
            assert data["clearing_reference"].startswith("CLR_RTP_")
            assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_instant_clearing_latency_injection(self) -> None:
        """X-Mock-Delay-Ms introduces artificial latency."""
        transport = ASGITransport(app=bank_app)
        async with AsyncClient(transport=transport, base_url="http://bank") as client:
            payload = {
                "payment_id": str(uuid4()),
                "amount_cents": 1000,
                "rail": "fednow",
                "destination_account_number": "12345678",
                "destination_routing_number": "021000021",
            }
            headers = {"X-Mock-Delay-Ms": "80"}
            t0 = time.perf_counter()
            res = await client.post("/clearing/instant", json=payload, headers=headers)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            assert res.status_code == 200
            assert elapsed_ms >= 70.0

    @pytest.mark.asyncio
    async def test_instant_clearing_simulated_failure_header(self) -> None:
        """X-Simulate-Failure header returns HTTP 502 Bad Gateway."""
        transport = ASGITransport(app=bank_app)
        async with AsyncClient(transport=transport, base_url="http://bank") as client:
            payload = {
                "payment_id": str(uuid4()),
                "amount_cents": 1000,
                "rail": "rtp",
                "destination_account_number": "1234",
                "destination_routing_number": "021000021",
            }
            headers = {"X-Simulate-Failure": "true"}
            res = await client.post("/clearing/instant", json=payload, headers=headers)
            assert res.status_code == 502
            assert "temporarily unavailable" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_instant_clearing_deterministic_999_routing_rejection(self) -> None:
        """Routing transit numbers starting with 999 trigger 502 rejection."""
        transport = ASGITransport(app=bank_app)
        async with AsyncClient(transport=transport, base_url="http://bank") as client:
            payload = {
                "payment_id": str(uuid4()),
                "amount_cents": 1000,
                "rail": "fednow",
                "destination_account_number": "1234",
                "destination_routing_number": "999123456",
            }
            res = await client.post("/clearing/instant", json=payload)
            assert res.status_code == 502

    @pytest.mark.asyncio
    async def test_batch_chunk_clearing_happy_path(self) -> None:
        """Batch chunk endpoint accepts items and echoes count."""
        transport = ASGITransport(app=bank_app)
        async with AsyncClient(transport=transport, base_url="http://bank") as client:
            payload = {
                "batch_id": str(uuid4()),
                "chunk_index": 0,
                "items": [
                    {"disbursement_id": str(uuid4()), "account_number": "111", "routing_number": "021", "amount_cents": 100},
                    {"disbursement_id": str(uuid4()), "account_number": "222", "routing_number": "021", "amount_cents": 200},
                ],
            }
            res = await client.post("/clearing/batch-chunk", json=payload, headers={"X-Mock-Delay-Ms": "10"})
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "accepted"
            assert data["cleared_count"] == 2

            # Test without delay header (branch x_mock_delay_ms is None)
            res_no_delay = await client.post("/clearing/batch-chunk", json=payload)
            assert res_no_delay.status_code == 200


@pytest.mark.integration
class TestBankSimulatorClient:
    """Test BankSimulatorClient network wrapper."""

    @pytest.mark.asyncio
    async def test_client_clear_instant_payment_success(self) -> None:
        """Client clear_instant_payment returns dict with clearing_reference."""
        client = BankSimulatorClient(base_url="http://testbank")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "settled", "clearing_reference": "CLR_RTP_OK"}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            res = await client.clear_instant_payment(
                payment_id=str(uuid4()),
                amount_cents=1000,
                rail="rtp",
                destination_account_number="123",
                destination_routing_number="021000021",
                delay_ms=10,
                simulate_failure=True,
            )
            assert res["status"] == "settled"
            assert res["clearing_reference"] == "CLR_RTP_OK"

    @pytest.mark.asyncio
    async def test_client_clear_instant_payment_raises_on_502(self) -> None:
        """Client raises BankClearingError when partner bank returns non-200."""
        client = BankSimulatorClient(base_url="http://testbank")
        mock_response = MagicMock()
        mock_response.status_code = 502
        mock_response.text = "Partner bank offline"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(BankClearingError) as exc:
                await client.clear_instant_payment(
                    payment_id=str(uuid4()),
                    amount_cents=1000,
                    rail="rtp",
                    destination_account_number="123",
                    destination_routing_number="021000021",
                )
            assert exc.value.status_code == 502

    @pytest.mark.asyncio
    async def test_client_clear_instant_payment_timeout_error(self) -> None:
        """Client raises BankClearingError on httpx TimeoutException."""
        import httpx
        client = BankSimulatorClient(base_url="http://testbank")
        with patch("httpx.AsyncClient.post", side_effect=httpx.ReadTimeout("Timeout")):
            with pytest.raises(BankClearingError):
                await client.clear_instant_payment(
                    payment_id=str(uuid4()),
                    amount_cents=1000,
                    rail="rtp",
                    destination_account_number="123",
                    destination_routing_number="021000021",
                )

    @pytest.mark.asyncio
    async def test_client_clear_batch_chunk_success(self) -> None:
        """Client clear_batch_chunk returns accepted confirmation."""
        client = BankSimulatorClient(base_url="http://testbank")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "accepted", "cleared_count": 5}

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            res = await client.clear_batch_chunk(
                batch_id=str(uuid4()),
                chunk_index=0,
                items=[{"id": 1}],
                delay_ms=10,
            )
            assert res["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_client_clear_batch_chunk_error(self) -> None:
        """Client clear_batch_chunk raises BankClearingError on non-200."""
        import httpx
        client = BankSimulatorClient(base_url="http://testbank")
        mock_response = MagicMock()
        mock_response.status_code = 500
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(BankClearingError) as exc:
                await client.clear_batch_chunk(
                    batch_id=str(uuid4()),
                    chunk_index=0,
                    items=[{"id": 1}],
                )
            assert exc.value.status_code == 500

        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Network drop")):
            with pytest.raises(BankClearingError):
                await client.clear_batch_chunk(
                    batch_id=str(uuid4()),
                    chunk_index=0,
                    items=[{"id": 1}],
                )

    @pytest.mark.asyncio
    async def test_client_check_health(self) -> None:
        """Client check_health returns True on 200, False on error."""
        client = BankSimulatorClient(base_url="http://testbank")
        mock_ok = MagicMock(status_code=200)
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_ok):
            assert await client.check_health() is True

        with patch("httpx.AsyncClient.get", side_effect=Exception("Failed")):
            assert await client.check_health() is False

    @pytest.mark.asyncio
    async def test_get_bank_simulator_client_singleton(self) -> None:
        """get_bank_simulator_client returns eager singleton instance."""
        c1 = get_bank_simulator_client()
        c2 = get_bank_simulator_client()
        assert c1 is c2
        assert isinstance(c1, BankSimulatorClient)

    @pytest.mark.asyncio
    async def test_init_bank_client(self) -> None:
        """init_bank_client creates a new process-local client instance."""
        old_client = get_bank_simulator_client()
        new_client = init_bank_client()
        assert new_client is not old_client
        assert get_bank_simulator_client() is new_client

    @pytest.mark.asyncio
    async def test_close_bank_client(self) -> None:
        """close_bank_client closes the shared HTTP connection pool cleanly."""
        await close_bank_client()
        # Should be callable repeatedly without error
        await close_bank_client()
        # Re-initialize for subsequent tests
        init_bank_client()

    @pytest.mark.asyncio
    async def test_client_clear_instant_circuit_breaker_open(self) -> None:
        """When rail circuit is open, clear_instant_payment fails fast with CircuitBreakerOpenError."""
        from app.circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
        cb = get_circuit_breaker("rtp")
        cb._trip(now=time.monotonic())
        client = BankSimulatorClient(base_url="http://testbank")
        try:
            with pytest.raises(CircuitBreakerOpenError) as exc:
                await client.clear_instant_payment(
                    payment_id=str(uuid4()),
                    amount_cents=1000,
                    rail="rtp",
                    destination_account_number="123",
                    destination_routing_number="021000021",
                )
            assert exc.value.rail == "rtp"
        finally:
            cb.reset()
