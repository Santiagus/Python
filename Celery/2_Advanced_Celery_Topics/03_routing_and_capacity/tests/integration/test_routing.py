"""Integration tests for Kombu AMQP exchange topology, dead-letter routing, and task mappings."""

from __future__ import annotations

import pytest
from kombu import Exchange, Queue

from services.worker.celery_app import (
    celery_app,
    dead_letter_exchange,
    payments_exchange,
    task_queues,
    task_routes,
)


@pytest.mark.integration
class TestKombuRoutingArchitecture:
    """Test Kombu AMQP 0-9-1 driver topology and queue declarations."""

    def test_exchange_specifications(self) -> None:
        """Verify durability, naming, and types of AMQP exchanges."""
        assert payments_exchange.name == "payments.direct"
        assert payments_exchange.type == "direct"
        assert payments_exchange.durable is True

        assert dead_letter_exchange.name == "payments.dlx"
        assert dead_letter_exchange.type == "direct"
        assert dead_letter_exchange.durable is True

    def test_queue_specifications_and_dlx_arguments(self) -> None:
        """Verify queue isolation, priorities, message TTL, and dead-lettering."""
        queue_dict: dict[str, Queue] = {q.name: q for q in task_queues}

        # 1. Critical Queue (FedNow / RTP)
        assert "critical" in queue_dict
        q_crit = queue_dict["critical"]
        assert q_crit.exchange.name == "payments.direct"
        assert q_crit.routing_key == "payment.instant.payout"
        assert q_crit.queue_arguments["x-max-priority"] == 10
        assert q_crit.queue_arguments["x-dead-letter-exchange"] == "payments.dlx"
        assert q_crit.queue_arguments["x-dead-letter-routing-key"] == "payment.rejected"

        # 2. Default Queue (Webhooks / Receipts)
        assert "default" in queue_dict
        q_def = queue_dict["default"]
        assert q_def.exchange.name == "payments.direct"
        assert q_def.routing_key == "payment.standard.#"
        assert q_def.queue_arguments["x-dead-letter-exchange"] == "payments.dlx"
        assert q_def.queue_arguments["x-dead-letter-routing-key"] == "payment.rejected"

        # 3. Bulk Queue (ACH Payroll Chunks)
        assert "bulk" in queue_dict
        q_bulk = queue_dict["bulk"]
        assert q_bulk.exchange.name == "payments.direct"
        assert q_bulk.routing_key == "settlement.batch.payroll"
        assert q_bulk.queue_arguments["x-message-ttl"] == 86400000  # 24 hours
        assert q_bulk.queue_arguments["x-dead-letter-exchange"] == "payments.dlx"
        assert q_bulk.queue_arguments["x-dead-letter-routing-key"] == "payment.rejected"

        # 4. Dead Letter Queue (DLQ)
        assert "rejected_payments" in queue_dict
        q_dlq = queue_dict["rejected_payments"]
        assert q_dlq.exchange.name == "payments.dlx"
        assert q_dlq.routing_key == "payment.rejected"

    def test_domain_task_routes_mapping(self) -> None:
        """Verify that tasks route strictly by business domain and not priority names."""
        assert task_routes["services.worker.tasks.payouts.process_instant_payout"] == {
            "queue": "critical",
            "routing_key": "payment.instant.payout",
        }
        assert task_routes["services.worker.tasks.notifications.send_payment_receipt"] == {
            "queue": "default",
            "routing_key": "payment.standard.receipt",
        }
        assert task_routes["services.worker.tasks.notifications.dispatch_merchant_webhook"] == {
            "queue": "default",
            "routing_key": "payment.standard.webhook",
        }
        assert task_routes["services.worker.tasks.settlements.process_payroll_chunk"] == {
            "queue": "bulk",
            "routing_key": "settlement.batch.payroll",
        }

    def test_celery_operational_invariants(self) -> None:
        """Verify worker reliability and safety invariants."""
        conf = celery_app.conf
        assert conf.task_acks_late is True
        assert conf.task_reject_on_worker_lost is True
        assert conf.task_serializer == "json"
        assert conf.result_serializer == "json"
        assert "json" in conf.accept_content

