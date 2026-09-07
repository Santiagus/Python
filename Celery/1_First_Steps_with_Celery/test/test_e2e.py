import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from kombu import pools
from testcontainers.community.rabbitmq import RabbitMqContainer

from tasks import add, app


@pytest.fixture(scope="module")
def rabbitmq() -> Iterator[RabbitMqContainer]:
    """Start the RabbitMQ service boundary used by the E2E test."""
    with RabbitMqContainer("rabbitmq:3-management") as container:
        yield container


@pytest.fixture
def broker_url(rabbitmq: RabbitMqContainer) -> str:
    """Build the AMQP URL using the container's mapped host and port."""
    host = rabbitmq.get_container_host_ip()
    port = rabbitmq.get_exposed_port(rabbitmq.port)
    return f"pyamqp://{rabbitmq.username}:{rabbitmq.password}@{host}:{port}//"


@pytest.fixture
def celery_runtime(broker_url: str) -> Iterator[None]:
    """Configure the imported Celery app for the containerized broker."""
    original_broker = app.conf.broker_url
    original_backend = app.conf.result_backend
    original_timeout = app.conf.broker_connection_timeout
    app.conf.update(
        broker_url=broker_url,
        result_backend="rpc://",
        broker_connection_timeout=2,
    )

    try:
        yield
    finally:
        pools.reset()
        app._pool = None
        app.amqp._producer_pool = None
        app._backend_cache = None
        if hasattr(app._local, "backend"):
            del app._local.backend
        app.conf.update(
            broker_url=original_broker,
            result_backend=original_backend,
            broker_connection_timeout=original_timeout,
        )


@pytest.fixture
def worker_environment(broker_url: str) -> dict[str, str]:
    """Build the environment passed to the external Celery worker process."""
    project_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update(
        {
            "CELERY_BROKER_URL": broker_url,
            "CELERY_RESULT_BACKEND": "rpc://",
            "PYTHONPATH": str(project_root),
        }
    )
    return environment


@pytest.fixture
def celery_worker(
    worker_environment: dict[str, str],
    celery_runtime: None,
) -> Iterator[None]:
    """Run Celery in a separate process against the containerized broker."""
    project_root = Path(__file__).resolve().parents[1]

    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "tasks",
            "worker",
            "--loglevel=WARNING",
            "--pool=solo",
            "--concurrency=1",
            "--hostname=e2e@%h",
        ],
        cwd=project_root,
        env=worker_environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if worker.poll() is not None:
                stderr = worker.stderr.read() if worker.stderr else ""
                raise RuntimeError(f"Celery worker exited early: {stderr}")

            if app.control.inspect(timeout=1).ping():
                break
            time.sleep(0.25)
        else:
            raise RuntimeError("Celery worker did not become ready within 30 seconds")

        yield
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()


def test_task_runs_through_containerized_broker_and_worker(
    celery_worker: None,
) -> None:
    """Verify a task completes through RabbitMQ and a separate worker process."""
    result = add.delay(4, 4)
    assert result.get(timeout=10) == 8
    assert result.status == "SUCCESS"
