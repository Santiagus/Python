"""Unit tests for Redis distributed lock and mutual exclusion manager."""

from __future__ import annotations

import uuid

import pytest

from services.worker.locks import (
    DistributedLock,
    close_redis_client,
    distributed_lock,
    get_redis_client,
)


@pytest.mark.unit
def test_distributed_lock_acquire_and_release() -> None:
    """Verify that a distributed lock can be acquired and released successfully."""
    client = get_redis_client()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)
    assert lock.acquire() is True
    assert client.exists(lock_key) == 1

    # Release lock
    assert lock.release() is True
    assert client.exists(lock_key) == 0


@pytest.mark.unit
def test_distributed_lock_contention() -> None:
    """Verify that acquiring an already held lock returns False."""
    client = get_redis_client()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock1 = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)
    lock2 = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)

    assert lock1.acquire() is True
    assert lock2.acquire() is False

    # Once lock1 is released, lock2 can acquire
    assert lock1.release() is True
    assert lock2.acquire() is True
    assert lock2.release() is True


@pytest.mark.unit
def test_distributed_lock_release_unacquired_or_expired() -> None:
    """Verify release returns False when lock was not acquired or token is missing."""
    client = get_redis_client()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock = DistributedLock(lock_key=lock_key, ttl_seconds=1, client=client)
    # Release before acquire
    assert lock.release() is False

    # Acquire and manually delete in Redis to simulate TTL expiration
    assert lock.acquire() is True
    client.delete(lock_key)
    # Releasing an expired or deleted lock returns False
    assert lock.release() is False


@pytest.mark.unit
def test_distributed_lock_context_manager() -> None:
    """Verify context manager auto-releases the lock upon exit."""
    client = get_redis_client()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    with distributed_lock(lock_key, ttl_seconds=10, client=client) as acquired:
        assert acquired is True
        assert client.exists(lock_key) == 1

    # Lock must be released automatically outside context
    assert client.exists(lock_key) == 0


@pytest.mark.unit
def test_distributed_lock_context_manager_contention() -> None:
    """Verify context manager handles contention without releasing someone else's lock."""
    client = get_redis_client()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock_primary = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)
    assert lock_primary.acquire() is True

    # Attempt to use context manager on same key
    with distributed_lock(lock_key, ttl_seconds=10, client=client) as acquired:
        assert acquired is False

    # Primary lock should still be active
    assert client.exists(lock_key) == 1
    assert lock_primary.release() is True
    assert client.exists(lock_key) == 0


@pytest.mark.unit
def test_redis_client_singleton_lifecycle() -> None:
    """Verify get_redis_client returns active singleton and close_redis_client closes it."""
    client1 = get_redis_client()
    client2 = get_redis_client()
    assert client1 is client2

    close_redis_client()
    client3 = get_redis_client()
    assert client3 is not None
    assert client3.ping() is True
