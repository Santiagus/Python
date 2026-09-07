from contextlib import AbstractContextManager
from typing import cast

from kombu import pools
from celery.contrib.testing.worker import start_worker
from tasks import add, app


def test_task_executes_through_in_process_worker():
    pools.reset()
    app._pool = None
    app.amqp._producer_pool = None
    app._backend_cache = None
    if hasattr(app._local, "backend"):
        del app._local.backend

    original_broker = app.conf.broker_url
    original_backend = app.conf.result_backend
    original_always_eager = app.conf.task_always_eager

    app.conf.update(
        broker_url="memory://",
        result_backend="cache+memory://",
        task_always_eager=False,
    )

    try:
        worker = start_worker(app, perform_ping_check=False, pool="solo")

        with cast(AbstractContextManager[object], worker):
            result = add.delay(4, 4)
            assert result.get(timeout=5) == 8
            assert result.status == "SUCCESS"
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
            task_always_eager=original_always_eager,
        )
