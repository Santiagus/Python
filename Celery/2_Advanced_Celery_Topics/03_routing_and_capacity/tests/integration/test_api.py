"""Integration tests for FastAPI Ingestion Gateway endpoints."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from httpx import AsyncClient
import pytest
from sqlalchemy import select

from app.models import Account, Payment


@pytest.mark.integration
class TestAuthentication:
    """Test M2M API Key authentication on protected endpoints."""

    @pytest.mark.asyncio
    async def test_missing_api_key_rejected(self, async_client: AsyncClient) -> None:
        """Requests without X-API-Key header receive HTTP 401 Unauthorized."""
        res = await async_client.get("/accounts/a0000000-0000-0000-0000-000000000001")
        assert res.status_code == 401
        assert "Missing required authentication header" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_invalid_api_key_rejected(self, async_client: AsyncClient) -> None:
        """Requests with an invalid API key receive HTTP 401 Unauthorized."""
        headers = {"X-API-Key": "sk_live_invalid_entropy_key_000"}
        res = await async_client.get("/accounts/a0000000-0000-0000-0000-000000000001", headers=headers)
        assert res.status_code == 401
        assert "Invalid API Key credentials" in res.json()["detail"]


@pytest.mark.integration
class TestInstantPayoutEndpoints:
    """Test instant payout creation, idempotency enforcement, and querying."""

    @pytest.mark.asyncio
    async def test_submit_instant_payout_happy_path(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Submit valid instant payment, verify DB insertion and Celery dispatch."""
        idemp_key = f"idemp_test_{uuid4().hex}"
        payload = {
            "idempotency_key": idemp_key,
            "source_account_id": "a0000000-0000-0000-0000-000000000001",
            "destination_account_number": "9876543210",
            "destination_routing_number": "021000021",
            "amount": "1250.00",
            "rail": "rtp",
            "description": "Executive payout",
        }

        with patch("app.routes.dispatcher.dispatch_instant_payout") as mock_dispatch:
            res = await async_client.post("/payments/instant", json=payload, headers=auth_headers)
            assert res.status_code == 202
            body = res.json()
            assert body["idempotency_key"] == idemp_key
            assert body["amount"] == "1250.00"
            assert body["amount_cents"] == 125000
            assert body["status"] == "pending"
            assert body["priority"] == "critical"
            assert body["destination_account_mask"] == "******3210"
            assert mock_dispatch.called

            # Query payment by ID
            pid = body["payment_id"]
            get_res = await async_client.get(f"/payments/{pid}", headers=auth_headers)
            assert get_res.status_code == 200
            assert get_res.json()["payment_id"] == pid

    @pytest.mark.asyncio
    async def test_instant_payout_idempotency_duplicate_intercepted(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Resending identical idempotency key returns existing record without duplicate dispatch."""
        idemp_key = f"idemp_dup_{uuid4().hex}"
        payload = {
            "idempotency_key": idemp_key,
            "source_account_id": "a0000000-0000-0000-0000-000000000001",
            "destination_account_number": "9876543210",
            "destination_routing_number": "021000021",
            "amount": "500.00",
            "rail": "fednow",
        }

        with patch("app.routes.dispatcher.dispatch_instant_payout") as mock_dispatch:
            # First submission
            res1 = await async_client.post("/payments/instant", json=payload, headers=auth_headers)
            assert res1.status_code == 202
            pid1 = res1.json()["payment_id"]
            assert mock_dispatch.call_count == 1

            # Duplicate submission
            res2 = await async_client.post("/payments/instant", json=payload, headers=auth_headers)
            assert res2.status_code == 202
            pid2 = res2.json()["payment_id"]

            # Must return the exact same payment_id without calling dispatcher again
            assert pid1 == pid2
            assert mock_dispatch.call_count == 1

    @pytest.mark.asyncio
    async def test_instant_payout_source_account_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Submission with non-existent source account returns 404."""
        payload = {
            "idempotency_key": f"idemp_missing_{uuid4().hex}",
            "source_account_id": str(uuid4()),
            "destination_account_number": "9876543210",
            "destination_routing_number": "021000021",
            "amount": "100.00",
            "rail": "rtp",
        }
        res = await async_client.post("/payments/instant", json=payload, headers=auth_headers)
        assert res.status_code == 404
        assert "not found" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_payment_status_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Querying an unknown payment ID returns 404."""
        res = await async_client.get(f"/payments/{uuid4()}", headers=auth_headers)
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_account_validation_cache_and_clear(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Verify in-memory account cache hits and clear_account_cache behavior."""
        from app.routes import _ACCOUNT_CACHE, clear_account_cache

        clear_account_cache()
        assert len(_ACCOUNT_CACHE) == 0

        acc_id = UUID("a0000000-0000-0000-0000-000000000001")
        payload = {
            "idempotency_key": f"idemp_cache_{uuid4().hex}",
            "source_account_id": str(acc_id),
            "destination_account_number": "9876543210",
            "destination_routing_number": "021000021",
            "amount": "10.00",
            "rail": "rtp",
        }
        with patch("app.routes.dispatcher.dispatch_instant_payout"):
            # First call: cache miss, populates cache
            res1 = await async_client.post("/payments/instant", json=payload, headers=auth_headers)
            assert res1.status_code == 202
            assert acc_id in _ACCOUNT_CACHE

            # Second call: cache hit
            payload["idempotency_key"] = f"idemp_cache_{uuid4().hex}"
            res2 = await async_client.post("/payments/instant", json=payload, headers=auth_headers)
            assert res2.status_code == 202

        clear_account_cache()
        assert len(_ACCOUNT_CACHE) == 0


@pytest.mark.integration
class TestBatchDisbursementEndpoints:
    """Test batch payroll submission, chunking dispatch, and progress monitoring."""

    @pytest.mark.asyncio
    async def test_submit_batch_disbursement_happy_path(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Submit payroll batch, verify total calculation, persistence, and chunk dispatch."""
        payload = {
            "file_reference": "nacha_payroll_2026_q3",
            "source_account_id": "a0000000-0000-0000-0000-000000000002",
            "disbursements": [
                {
                    "recipient_name": "Alice Developer",
                    "account_number": "111122223333",
                    "routing_number": "021000021",
                    "amount": "3000.00",
                },
                {
                    "recipient_name": "Bob Architect",
                    "account_number": "444455556666",
                    "routing_number": "021000021",
                    "amount": "4500.50",
                },
            ],
        }

        with patch("app.routes.dispatcher.dispatch_batch_settlement") as mock_dispatch:
            res = await async_client.post("/disbursements/batch", json=payload, headers=auth_headers)
            assert res.status_code == 202
            body = res.json()
            assert body["total_items"] == 2
            assert body["total_amount"] == "7500.50"
            assert body["total_amount_cents"] == 750050
            assert body["status"] == "pending"
            assert mock_dispatch.called

            # Check batch progress query
            batch_id = body["batch_id"]
            get_res = await async_client.get(f"/disbursements/batch/{batch_id}", headers=auth_headers)
            assert get_res.status_code == 200
            assert get_res.json()["batch_id"] == batch_id

    @pytest.mark.asyncio
    async def test_submit_batch_source_account_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Batch submission fails with 404 if source account does not exist."""
        payload = {
            "file_reference": "nacha_invalid_acc",
            "source_account_id": str(uuid4()),
            "disbursements": [
                {
                    "recipient_name": "Ghost",
                    "account_number": "1111",
                    "routing_number": "021000021",
                    "amount": "10.00",
                }
            ],
        }
        res = await async_client.post("/disbursements/batch", json=payload, headers=auth_headers)
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_get_batch_status_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Querying an unknown batch ID returns 404."""
        res = await async_client.get(f"/disbursements/batch/{uuid4()}", headers=auth_headers)
        assert res.status_code == 404


@pytest.mark.integration
class TestAccountEndpoints:
    """Test account details and balance retrieval."""

    @pytest.mark.asyncio
    async def test_get_account_details_happy_path(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Query master treasury account returns masked number and liquidity."""
        acc_id = "a0000000-0000-0000-0000-000000000001"
        res = await async_client.get(f"/accounts/{acc_id}", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["account_id"] == acc_id
        assert body["account_number_mask"] == "******5501"
        assert body["balance_cents"] == 1000000000
        assert body["balance"] == "10000000.00"

    @pytest.mark.asyncio
    async def test_get_account_details_not_found(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
        db_session,
    ) -> None:
        """Querying unknown account returns 404."""
        res = await async_client.get(f"/accounts/{uuid4()}", headers=auth_headers)
        assert res.status_code == 404


@pytest.mark.integration
class TestOperationalEndpoints:
    """Test queue metrics, DLQ redrive, and health probes."""

    @pytest.mark.asyncio
    async def test_get_service_metrics_connected(self, async_client: AsyncClient) -> None:
        """Service metrics endpoint returns 200 with runtime DB pool and broker telemetry."""
        mock_channel = MagicMock()
        mock_channel.queue_declare.side_effect = [
            ("critical", 2, 1),
            Exception("Queue not declared"),
            ("bulk", 0, 1),
            ("rejected_payments", 0, 0),
        ]
        mock_conn = MagicMock()
        mock_conn.channel.return_value = mock_channel
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.routes.Connection", return_value=mock_conn):
            res = await async_client.get("/metrics")
            assert res.status_code == 200
            body = res.json()
            assert body["service"] == "api"
            assert "db_pool" in body
            assert len(body["queues"]) == 4

    @pytest.mark.asyncio
    async def test_get_service_metrics_broker_unreachable(self, async_client: AsyncClient) -> None:
        """When broker fails during /metrics, returns graceful fallback metrics."""
        with patch("app.routes.Connection", side_effect=RuntimeError("Broker failure")):
            res = await async_client.get("/metrics")
            assert res.status_code == 200
            body = res.json()
            assert body["service"] == "api"
            assert all(q["messages_ready"] == 0 for q in body["queues"])

    @pytest.mark.asyncio
    async def test_get_queue_metrics(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Inspect queue depths."""
        res = await async_client.get("/metrics/queues", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert "queues" in body
        queue_names = [q["name"] for q in body["queues"]]
        assert "critical" in queue_names
        assert "bulk" in queue_names

    @pytest.mark.asyncio
    async def test_get_queue_metrics_with_connected_broker(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Inspect queue depths when broker channel successfully declares queues or raises per-queue error."""
        mock_channel = MagicMock()
        mock_channel.queue_declare.side_effect = [
            ("critical", 5, 2),
            Exception("Queue not declared yet"),
            ("bulk", 0, 1),
            ("rejected_payments", 0, 0),
        ]
        mock_conn = MagicMock()
        mock_conn.channel.return_value = mock_channel
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.routes.Connection", return_value=mock_conn):
            res = await async_client.get("/metrics/queues", headers=auth_headers)
            assert res.status_code == 200
            body = res.json()
            assert body["total_ready"] == 5
            assert len(body["queues"]) == 4

    @pytest.mark.asyncio
    async def test_get_queue_metrics_broker_unreachable(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """When broker is unreachable, returns graceful zeros and logs warning."""
        with patch("app.routes.Connection", side_effect=RuntimeError("Broker connection failed")):
            res = await async_client.get("/metrics/queues", headers=auth_headers)
            assert res.status_code == 200
            body = res.json()
            assert body["total_ready"] == 0
            assert len(body["queues"]) == 4
            assert all(q["messages_ready"] == 0 for q in body["queues"])

    @pytest.mark.asyncio
    async def test_dlq_redrive(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Redrive messages from DLQ with mocked broker connection to critical queue."""
        mock_msg = MagicMock(delivery_tag=1, message=b"payload")
        mock_channel = MagicMock()
        mock_channel.basic_get.side_effect = [mock_msg, None]

        mock_conn = MagicMock()
        mock_conn.channel.return_value = mock_channel
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.routes.Connection", return_value=mock_conn):
            payload = {
                "source_queue": "rejected_payments",
                "destination_queue": "critical",
                "max_messages": 10,
            }
            res = await async_client.post("/admin/queues/dlq/redrive", json=payload, headers=auth_headers)
            assert res.status_code == 200
            body = res.json()
            assert body["source_queue"] == "rejected_payments"
            assert body["destination_queue"] == "critical"
            assert body["messages_redriven"] == 1
            assert mock_channel.basic_ack.called

    @pytest.mark.asyncio
    async def test_dlq_redrive_to_default_queue(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Redrive messages to default operational queue with alternate routing key."""
        mock_msg = MagicMock(delivery_tag=2, message=b"payload_default")
        mock_channel = MagicMock()
        mock_channel.basic_get.side_effect = [mock_msg, None]

        mock_conn = MagicMock()
        mock_conn.channel.return_value = mock_channel
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.routes.Connection", return_value=mock_conn):
            payload = {
                "source_queue": "rejected_payments",
                "destination_queue": "default",
                "max_messages": 5,
            }
            res = await async_client.post("/admin/queues/dlq/redrive", json=payload, headers=auth_headers)
            assert res.status_code == 200
            assert res.json()["messages_redriven"] == 1

    @pytest.mark.asyncio
    async def test_dlq_redrive_all_messages_without_break(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Redrive completes all requested messages without hitting early break."""
        mock_msg1 = MagicMock(delivery_tag=1, message=b"payload_1")
        mock_msg2 = MagicMock(delivery_tag=2, message=b"payload_2")
        mock_channel = MagicMock()
        mock_channel.basic_get.side_effect = [mock_msg1, mock_msg2]

        mock_conn = MagicMock()
        mock_conn.channel.return_value = mock_channel
        mock_conn.__enter__.return_value = mock_conn

        with patch("app.routes.Connection", return_value=mock_conn):
            payload = {
                "source_queue": "rejected_payments",
                "destination_queue": "critical",
                "max_messages": 2,
            }
            res = await async_client.post("/admin/queues/dlq/redrive", json=payload, headers=auth_headers)
            assert res.status_code == 200
            assert res.json()["messages_redriven"] == 2

    @pytest.mark.asyncio
    async def test_dlq_redrive_broker_error(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Broker failure during DLQ redrive returns HTTP 500 error."""
        with patch("app.routes.Connection", side_effect=RuntimeError("Broker AMQP error")):
            payload = {
                "source_queue": "rejected_payments",
                "destination_queue": "critical",
                "max_messages": 5,
            }
            res = await async_client.post("/admin/queues/dlq/redrive", json=payload, headers=auth_headers)
            assert res.status_code == 500
            assert "DLQ redrive failed" in res.json()["detail"]

    @pytest.mark.asyncio
    async def test_health_check_endpoint(self, async_client: AsyncClient, db_session) -> None:
        """General /health endpoint returns 200 and HealthResponse."""
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        with patch("app.routes.Connection", return_value=mock_conn):
            res = await async_client.get("/health")
            assert res.status_code == 200
            body = res.json()
            assert body["status"] == "healthy"
            assert body["service"] == "api"
            assert body["database"] == "connected"
            assert body["rabbitmq"] == "connected"

    @pytest.mark.asyncio
    async def test_health_live_probe(self, async_client: AsyncClient) -> None:
        """Liveness probe is public and returns 200 with service identifier."""
        res = await async_client.get("/health/live")
        assert res.status_code == 200
        assert res.json()["status"] == "alive"
        assert res.json()["service"] == "api"

    @pytest.mark.asyncio
    async def test_health_live_probe_with_delay(self, async_client: AsyncClient) -> None:
        """Liveness probe supports simulated delay for load balancing tests."""
        res = await async_client.get("/health/live", params={"delay_ms": 10})
        assert res.status_code == 200
        assert res.json()["status"] == "alive"
        assert res.json()["service"] == "api"

    @pytest.mark.asyncio
    async def test_health_ready_probe(self, async_client: AsyncClient, db_session) -> None:
        """Readiness probe verifies database connectivity and broker socket."""
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        with patch("app.routes.Connection", return_value=mock_conn):
            res = await async_client.get("/health/ready")
            assert res.status_code == 200
            body = res.json()
            assert body["status"] == "healthy"
            assert body["service"] == "api"
            assert body["database"] == "connected"
            assert body["rabbitmq"] == "connected"

    @pytest.mark.asyncio
    async def test_health_ready_probe_degraded_when_unreachable(self, async_client: AsyncClient, db_session) -> None:
        """Readiness probe returns 503 when broker or db fails."""
        with patch("app.routes.Connection", side_effect=Exception("Broker unreachable")):
            res = await async_client.get("/health/ready")
            assert res.status_code == 503
            assert "degraded" in res.json()["detail"]["status"]
            assert res.json()["detail"]["service"] == "api"

    @pytest.mark.asyncio
    async def test_health_ready_probe_database_error(self, async_client: AsyncClient, db_session) -> None:
        """Readiness probe returns 503 when database query fails."""
        with patch.object(db_session, "execute", side_effect=RuntimeError("DB disconnected")):
            res = await async_client.get("/health/ready")
            assert res.status_code == 503
            assert "unhealthy" in res.json()["detail"]["database"]
            assert res.json()["detail"]["service"] == "api"

    @pytest.mark.asyncio
    async def test_invalidate_account_cache_endpoint(
        self,
        async_client: AsyncClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Invalidate account cache endpoint broadcasts invalidation across cluster."""
        from unittest.mock import AsyncMock
        aid = uuid4()
        with patch("app.routes.get_account_cache") as mock_get_cache:
            mock_cache = MagicMock()
            mock_cache.invalidate = AsyncMock()
            mock_get_cache.return_value = mock_cache

            res = await async_client.post(f"/accounts/{aid}/invalidate-cache", headers=auth_headers)
            assert res.status_code == 200
            assert res.json()["status"] == "ok"
            assert res.json()["account_id"] == str(aid)
            mock_cache.invalidate.assert_awaited_once_with(aid)

