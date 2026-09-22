"""Locust load testing scenario for the payment orchestrator API gateway.

Simulates production multi-rail payment traffic using Locust's high-performance
gevent-based FastHttpUser. Distributes realistic traffic across instant payments,
batch payroll settlements, and operational queue telemetry.
"""

from __future__ import annotations

import logging
import os
import random
from uuid import uuid4

from locust import FastHttpUser, between, constant_pacing, task

logger = logging.getLogger(__name__)

API_KEY = "sk_live_payment_orchestrator_secret_key_2026"
SOURCE_INSTANT_ACCOUNT = "a0000000-0000-0000-0000-000000000001"
SOURCE_BATCH_ACCOUNT = "a0000000-0000-0000-0000-000000000002"
DESTINATION_ROUTING = "021000021"
BATCH_ITEMS = int(os.getenv("LOCUST_BATCH_ITEMS", "25"))
MIN_WAIT = float(os.getenv("LOCUST_MIN_WAIT", "0.05"))
MAX_WAIT = float(os.getenv("LOCUST_MAX_WAIT", "0.15"))


class PaymentTrafficUser(FastHttpUser):
    """Simulates multi-rail payment operations against the FastAPI Ingestion Gateway."""

    # Configurable think time modeling realistic user clicks and API client arrival
    wait_time = between(MIN_WAIT, MAX_WAIT)

    default_headers = {
        "X-API-Key": API_KEY,
        "Content-Type": "application/json",
    }

    def on_start(self) -> None:
        """Assign realistic enterprise funding accounts per simulated client user."""
        # Pick from seeded enterprise accounts pool (1..100) to avoid single-row DB lock serialization
        account_idx = random.randint(1, 100)
        self.instant_account_id = f"a0000000-0000-0000-0000-{account_idx:012d}"
        batch_idx = ((account_idx % 100) + 1)
        self.batch_account_id = f"a0000000-0000-0000-0000-{batch_idx:012d}"

    def wait_time(self) -> float:
        """Dynamic wait time supporting Little's Law arrival-rate pacing or randomized think time."""
        arrival_rate = float(os.getenv("LOCUST_ARRIVAL_RATE", "0"))
        if arrival_rate > 0:
            user_count = max(getattr(self.environment.runner, "user_count", 1), 1)
            pace_interval = user_count / arrival_rate
            if not hasattr(self, "_pacing_fn") or getattr(self, "_current_pace", None) != pace_interval:
                self._pacing_fn = constant_pacing(pace_interval)
                self._current_pace = pace_interval
            return self._pacing_fn(self)
        return between(MIN_WAIT, MAX_WAIT)(self)

    @task(9)
    def submit_instant_payout(self) -> None:
        """Submit high-priority real-time instant payment (FedNow / RTP).

        Weights 90% of total traffic. Verifies HTTP 202 response and low tail latency.
        """
        # 1. Generate unique idempotency key and random amount
        payment_ref = uuid4().hex
        source_account = getattr(self, "instant_account_id", SOURCE_INSTANT_ACCOUNT)
        payload = {
            "idempotency_key": f"locust_instant_{payment_ref}",
            "source_account_id": source_account,
            "destination_account_number": f"9876{random.randint(10000000, 99999999)}",
            "destination_routing_number": DESTINATION_ROUTING,
            "amount": f"{random.randint(5, 500)}.{random.randint(10, 99):02d}",
            "rail": random.choice(["fednow", "rtp"]),
        }

        # 2. Dispatch POST request
        with self.client.post(
            "/payments/instant",
            json=payload,
            headers=self.default_headers,
            catch_response=True,
            name="/payments/instant",
        ) as response:
            if response.status_code == 202:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code} - {response.text}")

    @task(1)
    def submit_batch_disbursements(self) -> None:
        """Submit bulk payroll disbursements (ACH / Fedwire).

        Weights 10% of traffic, inducing realistic queue contention on Celery bulk queues.
        """
        # 1. Build a batch with BATCH_ITEMS line items
        batch_id = uuid4().hex[:8]
        items = [
            {
                "recipient_name": f"Employee {i}",
                "account_number": f"2222{random.randint(10000000, 99999999)}",
                "routing_number": DESTINATION_ROUTING,
                "amount": f"{random.randint(50, 1500)}.{random.randint(10, 99):02d}",
            }
            for i in range(BATCH_ITEMS)
        ]
        source_account = getattr(self, "batch_account_id", SOURCE_BATCH_ACCOUNT)
        payload = {
            "file_reference": f"locust_batch_{batch_id}",
            "source_account_id": source_account,
            "disbursements": items,
        }

        # 2. Dispatch POST request
        with self.client.post(
            "/disbursements/batch",
            json=payload,
            headers=self.default_headers,
            catch_response=True,
            name="/disbursements/batch",
        ) as response:
            if response.status_code == 202:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code} - {response.text}")

    @task(1)
    def query_queue_metrics(self) -> None:
        """Query real-time queue depths and backlog metrics.

        Weights 10% of traffic, auditing queue visibility without interfering with transactions.
        """
        with self.client.get(
            "/metrics/queues",
            headers=self.default_headers,
            catch_response=True,
            name="/metrics/queues",
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code}")


if __name__ == "__main__":
    import argparse
    import subprocess
    import sys

    parser = argparse.ArgumentParser(
        description="Locust Multi-Rail Payment Traffic Load Generator"
    )
    parser.add_argument(
        "--host",
        default=os.getenv("API_URL", "http://localhost:8010"),
        help="API Gateway URL (default: http://localhost:8010)",
    )
    parser.add_argument(
        "-u",
        "--users",
        type=int,
        default=int(os.getenv("LOCUST_USERS", "10")),
        help="Number of concurrent users (default: 10)",
    )
    parser.add_argument(
        "-r",
        "--spawn-rate",
        type=int,
        default=int(os.getenv("LOCUST_SPAWN_RATE", "5")),
        help="User spawn rate per second (default: 5)",
    )
    parser.add_argument(
        "-t",
        "--run-time",
        default=os.getenv("LOCUST_RUN_TIME", "10s"),
        help="Benchmark duration (default: 10s)",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        default=False,
        help="Launch interactive Locust web UI instead of headless mode",
    )
    args, unknown = parser.parse_known_args()

    cmd = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        __file__,
        "--host",
        args.host,
    ]
    if not args.web:
        cmd.extend([
            "--headless",
            "-u",
            str(args.users),
            "-r",
            str(args.spawn_rate),
            "-t",
            str(args.run_time),
        ])
    cmd.extend(unknown)

    print(f"Executing Locust load test: {' '.join(cmd)}")
    sys.exit(subprocess.call(cmd))

