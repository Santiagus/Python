"""Resilient HTTP client for communicating with the Partner Bank Simulator API.

Provides connection pooling, timeout discipline, fault handling, and structured logging
for outgoing Celery worker clearing operations. Eagerly initializes connection pools
at module load to eliminate first-call warm time.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from app.config import get_settings

logger = logging.getLogger(__name__)

# Shared HTTP keepalive connection limits & pooling (reused across all client calls)
_default_limits = httpx.Limits(
    max_keepalive_connections=20,
    max_connections=50,
    keepalive_expiry=30.0,
)

# Eager initialization at module load to eliminate first-call warm time
_shared_client: httpx.AsyncClient = httpx.AsyncClient(
    limits=_default_limits,
    timeout=2.5,
)


class BankClearingError(Exception):
    """Raised when an external bank clearing call fails or times out."""

    def __init__(self, message: str, status_code: int | None = None, response_body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class BankSimulatorClient:
    """Async client for partner clearing rails (FedNow, RTP, ACH)."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 2.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize bank client with shared connection pool.

        Args:
            base_url: Bank simulator endpoint base URL.
            timeout: Maximum network wait in seconds. Default 2.5s guarantees
                     completion before the 3.0s Celery soft time limit.
            client: Optional pre-configured httpx.AsyncClient for connection reuse.
        """
        settings = get_settings()
        self.base_url = (base_url or settings.bank_api_url).rstrip("/")
        self.timeout = timeout
        self._client = client or _shared_client

    async def clear_instant_payment(
        self,
        payment_id: str,
        amount_cents: int,
        rail: str,
        destination_account_number: str,
        destination_routing_number: str,
        delay_ms: int | None = None,
        simulate_failure: bool = False,
    ) -> dict[str, Any]:
        """Submit a real-time payment to the clearing rail.

        Args:
            payment_id: Payment transaction UUID.
            amount_cents: Transfer amount in integer cents.
            rail: Target rail ('fednow' or 'rtp').
            destination_account_number: Recipient account number.
            destination_routing_number: Recipient 9-digit ABA routing transit number.
            delay_ms: Optional artificial latency injection.
            simulate_failure: If True, requests the bank to return 502 Bad Gateway.

        Returns:
            dict[str, Any]: Clearing confirmation with status and clearing reference.

        Raises:
            BankClearingError: If partner bank rejects the transaction or times out.
        """
        url = f"{self.base_url}/clearing/instant"
        headers: dict[str, str] = {}
        if delay_ms is not None:
            headers["X-Mock-Delay-Ms"] = str(delay_ms)
        if simulate_failure:
            headers["X-Simulate-Failure"] = "true"

        payload = {
            "payment_id": str(payment_id),
            "amount_cents": amount_cents,
            "rail": rail,
            "destination_account_number": destination_account_number,
            "destination_routing_number": destination_routing_number,
        }

        # Check rail circuit breaker before making outbound network call
        cb = get_circuit_breaker(rail)
        if not cb.can_execute():
            raise CircuitBreakerOpenError(rail=rail, message=f"Partner bank clearing circuit for rail '{rail}' is OPEN")

        client = self._client
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=self.timeout)
            if response.status_code != 200:
                cb.record_failure()
                raise BankClearingError(
                    f"Partner bank rejected payment with status {response.status_code}: {response.text}",
                    status_code=response.status_code,
                    response_body=response.text,
                )
            cb.record_success()
            return response.json()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            cb.record_failure()
            logger.error(
                "bank_network_timeout",
                extra={"payment_id": payment_id, "error": str(exc)},
            )
            raise BankClearingError(f"Partner bank network error: {exc}") from exc

    async def clear_batch_chunk(
        self,
        batch_id: str,
        chunk_index: int,
        items: list[dict[str, Any]],
        delay_ms: int | None = None,
    ) -> dict[str, Any]:
        """Submit a chunk of batch ACH disbursements for clearing.

        Args:
            batch_id: Batch settlement UUID.
            chunk_index: Index of current chunk.
            items: List of disbursement dictionaries.
            delay_ms: Optional latency injection.

        Returns:
            dict[str, Any]: Clearing acknowledgment.
        """
        url = f"{self.base_url}/clearing/batch-chunk"
        headers: dict[str, str] = {}
        if delay_ms is not None:
            headers["X-Mock-Delay-Ms"] = str(delay_ms)

        payload = {
            "batch_id": str(batch_id),
            "chunk_index": chunk_index,
            "items": items,
        }

        client = self._client
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if response.status_code != 200:
                raise BankClearingError(
                    f"Partner bank rejected batch chunk with status {response.status_code}",
                    status_code=response.status_code,
                )
            return response.json()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            logger.error("bank_batch_timeout", extra={"batch_id": batch_id, "error": str(exc)})
            raise BankClearingError(f"Partner bank batch network error: {exc}") from exc

    async def check_health(self) -> bool:
        """Verify connectivity to the partner bank simulator."""
        try:
            client = self._client
            res = await client.get(f"{self.base_url}/health", timeout=2.0)
            return res.status_code == 200
        except Exception:
            return False


# Eager singleton instance created at module load
bank_simulator_client: BankSimulatorClient = BankSimulatorClient(client=_shared_client)


def get_bank_simulator_client() -> BankSimulatorClient:
    """Return the eagerly initialized singleton bank simulator client."""
    return bank_simulator_client


def init_bank_client() -> BankSimulatorClient:
    """Eagerly re-initialize the shared client singleton (e.g., in worker child process)."""
    global _shared_client, bank_simulator_client
    _shared_client = httpx.AsyncClient(limits=_default_limits, timeout=2.5)
    bank_simulator_client = BankSimulatorClient(client=_shared_client)
    return bank_simulator_client


async def close_bank_client() -> None:
    """Dispose shared HTTP connection pool cleanly."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
