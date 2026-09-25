"""Unit tests for Redis distributed lock and mutual exclusion manager.

Tests atomic acquire, release, contention, context manager, and lifecycle
using an in-memory mock client to ensure fast, isolated execution.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from services.worker.locks import (
    DistributedLock,
    close_redis_client,
    distributed_lock,
    get_redis_client,
)


class FakeRedisClient:
    """In-memory Redis client mock for unit testing DistributedLock."""

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._data: dict[str, str] = {}

    def set(
        self,
        name: str,
        value: str,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool:
        """Set key if not exists when nx is True."""
        if nx and name in self._data:
            return False
        self._data[name] = str(value)
        return True

    def get(self, name: str) -> str | None:
        """Get value for key."""
        return self._data.get(name)

    def delete(self, *names: str) -> int:
        """Delete given keys and return deleted count."""
        count = 0
        for k in names:
            if self._data.pop(k, None) is not None:
                count += 1
        return count

    def exists(self, *names: str) -> int:
        """Return count of existing keys."""
        return sum(1 for k in names if k in self._data)

    def eval(self, script: str, numkeys: int, key: str, token: str) -> int:
        """Simulate release Lua script: delete key only if token matches."""
        if self._data.get(key) == str(token):
            self._data.pop(key, None)
            return 1
        return 0

    def ping(self) -> bool:
        """Simulate ping command."""
        return True

    def close(self) -> None:
        """Simulate client disposal."""
        self._data.clear()


@pytest.mark.unit
def test_distributed_lock_acquire_and_release() -> None:
    """Verify that a distributed lock can be acquired and released successfully."""
    client = FakeRedisClient()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)  # type: ignore[arg-type]
    assert lock.acquire() is True
    assert client.exists(lock_key) == 1

    # Release lock
    assert lock.release() is True
    assert client.exists(lock_key) == 0


@pytest.mark.unit
def test_distributed_lock_contention() -> None:
    """Verify that acquiring an already held lock returns False."""
    client = FakeRedisClient()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock1 = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)  # type: ignore[arg-type]
    lock2 = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)  # type: ignore[arg-type]

    assert lock1.acquire() is True
    assert lock2.acquire() is False

    # Once lock1 is released, lock2 can acquire
    assert lock1.release() is True
    assert lock2.acquire() is True
    assert lock2.release() is True


@pytest.mark.unit
def test_distributed_lock_release_unacquired_or_expired() -> None:
    """Verify release returns False when lock was not acquired or token is missing."""
    client = FakeRedisClient()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock = DistributedLock(lock_key=lock_key, ttl_seconds=1, client=client)  # type: ignore[arg-type]
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
    client = FakeRedisClient()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    with distributed_lock(lock_key, ttl_seconds=10, client=client) as acquired:  # type: ignore[arg-type]
        assert acquired is True
        assert client.exists(lock_key) == 1

    # Lock must be released automatically outside context
    assert client.exists(lock_key) == 0


@pytest.mark.unit
def test_distributed_lock_context_manager_contention() -> None:
    """Verify context manager handles contention without releasing someone else's lock."""
    client = FakeRedisClient()
    lock_key = f"test:lock:{uuid.uuid4().hex}"

    lock_primary = DistributedLock(lock_key=lock_key, ttl_seconds=10, client=client)  # type: ignore[arg-type]
    assert lock_primary.acquire() is True

    # Attempt to use context manager on same key
    with distributed_lock(lock_key, ttl_seconds=10, client=client) as acquired:  # type: ignore[arg-type]
        assert acquired is False

    # Primary lock should still be active
    assert client.exists(lock_key) == 1
    assert lock_primary.release() is True
    assert client.exists(lock_key) == 0


@pytest.mark.unit
def test_distributed_lock_default_client() -> None:
    """Verify DistributedLock acquires process-wide singleton client when omitted."""
    fake = FakeRedisClient()
    with patch("services.worker.locks.get_redis_client", return_value=fake):
        lock = DistributedLock(lock_key="test:default")
        assert lock.client is fake


@pytest.mark.unit
def test_redis_client_singleton_lifecycle() -> None:
    """Verify get_redis_client returns active singleton and close_redis_client closes it."""
    fake = FakeRedisClient()
    with patch("services.worker.locks.redis.from_url", return_value=fake) as mock_from_url:
        close_redis_client()  # Reset any prior state
        client1 = get_redis_client()
        client2 = get_redis_client()
        assert client1 is client2
        assert client1.ping() is True

        # Verify from_url was called with maint_notifications_config disabled by default
        assert mock_from_url.call_count == 1
        call_kwargs = mock_from_url.call_args.kwargs
        assert "maint_notifications_config" in call_kwargs
        assert call_kwargs["maint_notifications_config"].enabled is False

        close_redis_client()
        client3 = get_redis_client()
        assert client3 is not None
        close_redis_client()
        # Test no-op second close
        close_redis_client()


@pytest.mark.unit
def test_redis_client_maint_notifications_enabled() -> None:
    """Verify get_redis_client passes enabled=True when redis_maint_notifications is configured."""
    fake = FakeRedisClient()
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    mock_settings.redis_maint_notifications = True

    with patch("services.worker.locks.get_settings", return_value=mock_settings):
        with patch("services.worker.locks.redis.from_url", return_value=fake) as mock_from_url:
            close_redis_client()
            client = get_redis_client()
            assert client is fake
            call_kwargs = mock_from_url.call_args.kwargs
            assert call_kwargs["maint_notifications_config"].enabled is True
            close_redis_client()
