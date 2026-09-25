"""Distributed lock manager and mutual exclusion utilities using Redis.

Provides an atomic distributed lock implementation with TTL and fencing tokens
to prevent overlapping Celery task executions and coordinate multi-instance schedulers.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Generator
from contextlib import contextmanager

import redis
from redis.maint_notifications import MaintNotificationsConfig

from app.config import get_settings

logger = logging.getLogger(__name__)

# Atomic Lua release script: only delete the key if the token matches
_RELEASE_LUA_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_redis_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """Retrieve or eagerly instantiate the process-wide Redis client singleton.

    Returns:
        redis.Redis: Active Redis client instance with keep-alive pooling.
    """
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        maint_config = MaintNotificationsConfig(enabled=settings.redis_maint_notifications)
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_keepalive=True,
            maint_notifications_config=maint_config,
        )
    return _redis_client


def close_redis_client() -> None:
    """Dispose of the shared Redis client connection pool."""
    global _redis_client
    if _redis_client is not None:
        _redis_client.close()
        _redis_client = None


class DistributedLock:
    """Atomic Redis distributed lock backed by a fencing token and TTL."""

    def __init__(
        self,
        lock_key: str,
        ttl_seconds: int = 60,
        client: redis.Redis | None = None,
    ) -> None:
        """Initialize the distributed lock instance.

        Args:
            lock_key: Redis key to lock.
            ttl_seconds: Expiration TTL in seconds to prevent permanent deadlocks.
            client: Optional Redis client; defaults to get_redis_client().
        """
        self.lock_key = lock_key
        self.ttl_seconds = ttl_seconds
        self.client = client or get_redis_client()
        self.token = str(uuid.uuid4())
        self._acquired = False

    def acquire(self) -> bool:
        """Attempt to acquire the lock atomically via SET NX EX.

        Returns:
            bool: True if the lock was acquired, False if already held.
        """
        # 1. Attempt atomic set-if-not-exists with expiration TTL
        result = self.client.set(
            self.lock_key,
            self.token,
            nx=True,
            ex=self.ttl_seconds,
        )
        self._acquired = bool(result)
        if self._acquired:
            logger.debug(
                "Acquired distributed lock: %s (token=%s, ttl=%ss)",
                self.lock_key,
                self.token,
                self.ttl_seconds,
            )
        else:
            logger.warning(
                "Failed to acquire distributed lock: %s (already held)",
                self.lock_key,
            )
        return self._acquired

    def release(self) -> bool:
        """Release the lock atomically using Lua script if token matches.

        Returns:
            bool: True if released, False if expired or owned by another process.
        """
        if not self._acquired:
            return False

        try:
            # 2. Execute atomic Lua script to release only if token matches
            deleted = self.client.eval(_RELEASE_LUA_SCRIPT, 1, self.lock_key, self.token)
            success = bool(deleted)
            if success:
                logger.debug("Released distributed lock: %s", self.lock_key)
            else:
                logger.warning(
                    "Lock was already expired or reassigned before release: %s",
                    self.lock_key,
                )
            return success
        finally:
            self._acquired = False


@contextmanager
def distributed_lock(
    lock_key: str,
    ttl_seconds: int = 60,
    client: redis.Redis | None = None,
) -> Generator[bool, None, None]:
    """Context manager for acquiring and safely auto-releasing a distributed lock.

    Args:
        lock_key: Redis key to lock.
        ttl_seconds: Expiration TTL in seconds.
        client: Optional Redis client.

    Yields:
        bool: True if lock acquired, False if contention detected.
    """
    lock = DistributedLock(lock_key=lock_key, ttl_seconds=ttl_seconds, client=client)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()
