"""Hybrid L1+L2 caching manager with Redis Pub/Sub distributed cache invalidation.

Provides sub-microsecond local process memory lookups (L1) while maintaining
cluster-wide cache consistency across horizontal API container replicas via
asynchronous Redis Pub/Sub invalidation broadcasts (L2).
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL_ACCOUNT_INVALIDATIONS = "account:invalidations"
DEFAULT_ACCOUNT_TTL_SECONDS = 300.0


class AccountCacheManager:
    """Manages process-local L1 account validation cache with Redis Pub/Sub synchronization."""

    def __init__(
        self,
        redis_url: str | None = None,
        default_ttl: float = DEFAULT_ACCOUNT_TTL_SECONDS,
    ) -> None:
        """Initialize the hybrid account cache manager.

        Args:
            redis_url: Optional Redis connection string. Defaults to settings.redis_url.
            default_ttl: Default time-to-live for cached account entries in seconds.
        """
        self._redis_url = redis_url or get_settings().redis_url
        self._default_ttl = default_ttl
        self._local_cache: dict[UUID, float] = {}
        self._listener_task: asyncio.Task[None] | None = None
        self._redis_client: aioredis.Redis | None = None
        self._pubsub: aioredis.client.PubSub | None = None
        self._is_running = False

    def is_cached(self, account_id: UUID) -> bool:
        """Check if an account ID is present in L1 memory and unexpired.

        Args:
            account_id: Unique account UUID.

        Returns:
            bool: True if account is valid and unexpired in local memory, False otherwise.
        """
        now = time.monotonic()
        expiry = self._local_cache.get(account_id)
        if expiry is not None and expiry > now:
            return True
        # Clean expired entry if present
        if expiry is not None:
            self._local_cache.pop(account_id, None)
        return False

    def put(self, account_id: UUID, ttl: float | None = None) -> None:
        """Store an account ID in L1 local memory with an expiration timestamp.

        Args:
            account_id: Unique account UUID.
            ttl: Optional TTL override in seconds.
        """
        ttl_seconds = ttl if ttl is not None else self._default_ttl
        self._local_cache[account_id] = time.monotonic() + ttl_seconds

    def evict_local(self, target: UUID | str) -> None:
        """Evict an account ID or all accounts from process-local L1 memory.

        Args:
            target: Account UUID, string representation of UUID, or '*' for global purge.
        """
        if str(target) == "*":
            self._local_cache.clear()
            logger.info("local_account_cache_purged_all")
            return

        try:
            account_uuid = UUID(str(target))
            if self._local_cache.pop(account_uuid, None) is not None:
                logger.info("local_account_cache_evicted", extra={"account_id": str(account_uuid)})
        except (ValueError, TypeError) as exc:
            logger.warning("invalid_eviction_target", extra={"target": str(target), "error": str(exc)})

    def clear(self) -> None:
        """Clear all entries from local L1 cache."""
        self._local_cache.clear()

    async def invalidate(self, target: UUID | str) -> None:
        """Evict target locally and broadcast invalidation to all cluster replicas via Redis.

        Args:
            target: Account UUID, string UUID, or '*' to invalidate cluster-wide.
        """
        # 1. Evict from local memory immediately
        self.evict_local(target)

        # 2. Publish invalidation message to Redis Pub/Sub channel
        try:
            client = self._get_redis_client()
            await client.publish(CHANNEL_ACCOUNT_INVALIDATIONS, str(target))
            logger.info("published_account_invalidation", extra={"target": str(target)})
        except Exception as exc:
            logger.warning("failed_publishing_invalidation", extra={"target": str(target), "error": str(exc)})

    def _get_redis_client(self) -> aioredis.Redis:
        """Return or create the shared Redis client instance.

        Returns:
            aioredis.Redis: Active Redis client instance.
        """
        if self._redis_client is None:
            self._redis_client = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
            )
        return self._redis_client

    async def start_listener(self) -> None:
        """Start the background Redis Pub/Sub invalidation listener loop."""
        if self._listener_task is not None and not self._listener_task.done():
            return

        self._is_running = True
        self._listener_task = asyncio.create_task(self._listen_loop(), name="account_cache_invalidation_listener")
        logger.info("started_account_cache_invalidation_listener")

    async def stop_listener(self) -> None:
        """Stop the background listener and clean up Redis connections."""
        self._is_running = False

        # 1. Cancel background loop task
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except (asyncio.CancelledError, Exception):
                pass
            self._listener_task = None

        # 2. Unsubscribe and close pubsub
        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe(CHANNEL_ACCOUNT_INVALIDATIONS)
                await self._pubsub.close()
            except Exception as exc:
                logger.debug("pubsub_close_error", extra={"error": str(exc)})
            self._pubsub = None

        # 3. Close redis client
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception as exc:
                logger.debug("redis_client_close_error", extra={"error": str(exc)})
            self._redis_client = None

        logger.info("stopped_account_cache_invalidation_listener")

    async def _listen_loop(self) -> None:
        """Long-running background task consuming invalidation events from Redis."""
        while self._is_running:
            try:
                # 1. Connect to Redis and subscribe to invalidation channel
                client = self._get_redis_client()
                pubsub = client.pubsub()
                self._pubsub = pubsub
                await pubsub.subscribe(CHANNEL_ACCOUNT_INVALIDATIONS)
                logger.info("subscribed_to_account_invalidations", extra={"channel": CHANNEL_ACCOUNT_INVALIDATIONS})

                # 2. Consume incoming messages
                while self._is_running:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if message and message.get("type") == "message":
                        data = message.get("data")
                        if data:
                            logger.info("received_cache_invalidation_event", extra={"data": str(data)})
                            self.evict_local(str(data))
                    await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "account_cache_listener_connection_error",
                    extra={"error": str(exc), "retry_in": "2s"},
                )
                # On connection break, purge local cache to prevent stale reads
                self._local_cache.clear()
                if self._is_running:
                    await asyncio.sleep(2.0)


# Module-level singleton instance
_account_cache_manager: AccountCacheManager = AccountCacheManager()


def get_account_cache() -> AccountCacheManager:
    """Return the global singleton account cache manager."""
    return _account_cache_manager


def clear_account_cache() -> None:
    """Evict all entries from local account cache (test isolation hook)."""
    _account_cache_manager.clear()
