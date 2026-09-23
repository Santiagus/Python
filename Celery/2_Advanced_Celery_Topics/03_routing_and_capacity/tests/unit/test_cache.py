"""Unit tests for L1+L2 hybrid cache and Redis Pub/Sub invalidations."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.cache import (
    CHANNEL_ACCOUNT_INVALIDATIONS,
    DEFAULT_ACCOUNT_TTL_SECONDS,
    AccountCacheManager,
    clear_account_cache,
    get_account_cache,
)


@pytest.mark.unit
class TestAccountCacheManager:
    """Test L1 process memory and L2 Redis Pub/Sub cache manager."""

    def test_init_defaults_and_custom(self) -> None:
        """Verify default and custom initialization attributes."""
        mgr_default = AccountCacheManager()
        assert mgr_default._default_ttl == DEFAULT_ACCOUNT_TTL_SECONDS
        assert mgr_default._redis_url is not None

        mgr_custom = AccountCacheManager(redis_url="redis://localhost:6379/2", default_ttl=60.0)
        assert mgr_custom._default_ttl == 60.0
        assert mgr_custom._redis_url == "redis://localhost:6379/2"

    def test_is_cached_and_put(self) -> None:
        """Verify is_cached returns True for valid entries, False for expired/missing."""
        mgr = AccountCacheManager()
        aid = uuid4()

        # Missing entry
        assert mgr.is_cached(aid) is False

        # Put with default TTL
        mgr.put(aid)
        assert mgr.is_cached(aid) is True

        # Expired entry
        mgr._local_cache[aid] = 0.0  # Monotonic timestamp in past
        assert mgr.is_cached(aid) is False
        assert aid not in mgr._local_cache

        # Put with custom TTL
        aid2 = uuid4()
        mgr.put(aid2, ttl=100.0)
        assert mgr.is_cached(aid2) is True

    def test_evict_local_and_clear(self) -> None:
        """Verify local eviction of single items, invalid items, and wildcard clear."""
        mgr = AccountCacheManager()
        aid1 = uuid4()
        aid2 = uuid4()
        mgr.put(aid1)
        mgr.put(aid2)

        # Evict single item by UUID
        mgr.evict_local(aid1)
        assert mgr.is_cached(aid1) is False
        assert mgr.is_cached(aid2) is True

        # Evict by string UUID
        mgr.evict_local(str(aid2))
        assert mgr.is_cached(aid2) is False

        # Evict non-existent UUID
        mgr.evict_local(uuid4())

        # Evict invalid target string
        mgr.evict_local("not-a-valid-uuid")

        # Wildcard eviction
        mgr.put(aid1)
        mgr.put(aid2)
        mgr.evict_local("*")
        assert len(mgr._local_cache) == 0

        # Clear method
        mgr.put(aid1)
        mgr.clear()
        assert len(mgr._local_cache) == 0

    @pytest.mark.asyncio
    async def test_invalidate_broadcast_success_and_failure(self) -> None:
        """Verify invalidate evicts locally and publishes to Redis Pub/Sub."""
        mgr = AccountCacheManager()
        aid = uuid4()
        mgr.put(aid)

        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)
        mgr._redis_client = mock_redis

        # Successful broadcast
        await mgr.invalidate(aid)
        assert mgr.is_cached(aid) is False
        mock_redis.publish.assert_awaited_once_with(CHANNEL_ACCOUNT_INVALIDATIONS, str(aid))

        # Failure during broadcast is caught and logged
        mock_redis.publish.side_effect = ConnectionError("Redis down")
        await mgr.invalidate(aid)  # Should not raise

    def test_get_redis_client_caching(self) -> None:
        """Verify _get_redis_client lazily initializes and reuses connection."""
        mgr = AccountCacheManager(redis_url="redis://localhost:6379/0")
        assert mgr._redis_client is None

        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_from_url.return_value = mock_client

            client1 = mgr._get_redis_client()
            client2 = mgr._get_redis_client()

            assert client1 is mock_client
            assert client2 is mock_client
            mock_from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_and_stop_listener(self) -> None:
        """Verify listener task starts, idempotently ignores restart, and stops cleanly."""
        mgr = AccountCacheManager()

        with patch.object(mgr, "_listen_loop", new_callable=AsyncMock) as mock_loop:
            # First start
            await mgr.start_listener()
            assert mgr._is_running is True
            assert mgr._listener_task is not None

            # Redundant start
            task = mgr._listener_task
            await mgr.start_listener()
            assert mgr._listener_task is task

            # Setup mock pubsub and redis client for stop
            mock_pubsub = AsyncMock()
            mock_pubsub.unsubscribe = AsyncMock()
            mock_pubsub.close = AsyncMock()
            mgr._pubsub = mock_pubsub

            mock_redis = AsyncMock()
            mock_redis.aclose = AsyncMock()
            mgr._redis_client = mock_redis

            # Stop listener
            await mgr.stop_listener()
            assert mgr._is_running is False
            assert mgr._listener_task is None
            assert mgr._pubsub is None
            assert mgr._redis_client is None

            mock_pubsub.unsubscribe.assert_awaited_once()
            mock_pubsub.close.assert_awaited_once()
            mock_redis.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_listener_with_exceptions(self) -> None:
        """Verify stop_listener gracefully handles exceptions during cleanup."""
        mgr = AccountCacheManager()
        mgr._is_running = True

        # Mock listener task that raises on cancel
        mock_task = MagicMock()
        mock_task.cancel = MagicMock()
        mock_task.__await__ = MagicMock(side_effect=asyncio.CancelledError)
        mgr._listener_task = mock_task

        mock_pubsub = AsyncMock()
        mock_pubsub.unsubscribe.side_effect = RuntimeError("Pubsub error")
        mgr._pubsub = mock_pubsub

        mock_redis = AsyncMock()
        mock_redis.aclose.side_effect = RuntimeError("Redis close error")
        mgr._redis_client = mock_redis

        await mgr.stop_listener()
        assert mgr._pubsub is None
        assert mgr._redis_client is None

    @pytest.mark.asyncio
    async def test_stop_listener_uninitialized(self) -> None:
        """Calling stop_listener on an uninitialized manager executes cleanly."""
        mgr = AccountCacheManager()
        assert mgr._listener_task is None
        assert mgr._pubsub is None
        assert mgr._redis_client is None
        await mgr.stop_listener()
        assert mgr._is_running is False

    @pytest.mark.asyncio
    async def test_listen_loop_message_consumption(self) -> None:
        """Verify _listen_loop consumes invalidation messages and evicts entries."""
        mgr = AccountCacheManager()
        target_aid = uuid4()
        mgr.put(target_aid)
        assert mgr.is_cached(target_aid) is True

        mock_pubsub = AsyncMock()
        # Sequence of messages:
        # 1. Valid invalidation message for target_aid
        # 2. Irrelevant message (e.g. subscribe notification)
        # 3. Message with empty data
        # 4. None (timeout)
        async def mock_get_message(ignore_subscribe_messages: bool = True, timeout: float = 1.0):
            messages = [
                {"type": "message", "data": str(target_aid)},
                {"type": "subscribe", "data": 1},
                {"type": "message", "data": None},
                None,
            ]
            if hasattr(mock_get_message, "idx"):
                mock_get_message.idx += 1
            else:
                mock_get_message.idx = 0
            if mock_get_message.idx < len(messages):
                return messages[mock_get_message.idx]
            # Stop loop naturally
            mgr._is_running = False
            return None

        mock_pubsub.get_message = mock_get_message

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub
        mgr._redis_client = mock_redis
        mgr._is_running = True

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await mgr._listen_loop()

        # Item should have been evicted by the first message
        assert mgr.is_cached(target_aid) is False

    @pytest.mark.asyncio
    async def test_listen_loop_reconnection_and_error_handling(self) -> None:
        """Verify _listen_loop catches connection errors, clears cache, and retries."""
        mgr = AccountCacheManager()
        aid = uuid4()
        mgr.put(aid)
        assert mgr.is_cached(aid) is True

        mock_redis = MagicMock()
        # First iteration raises ConnectionError, then we stop running
        def fail_pubsub() -> MagicMock:
            mgr._is_running = False  # Stop after one failure
            raise ConnectionError("Broker unreachable")

        mock_redis.pubsub.side_effect = fail_pubsub
        mgr._redis_client = mock_redis
        mgr._is_running = True

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await mgr._listen_loop()
            mock_sleep.assert_not_called()  # Because is_running was set to False

        # Cache must be purged on connection break
        assert mgr.is_cached(aid) is False

    @pytest.mark.asyncio
    async def test_listen_loop_reconnection_sleep_when_running(self) -> None:
        """Verify _listen_loop sleeps 2s if still running after connection error."""
        mgr = AccountCacheManager()
        mock_redis = MagicMock()

        call_count = 0
        def fail_then_cancel() -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Temporary disconnect")
            raise asyncio.CancelledError()

        mock_redis.pubsub.side_effect = fail_then_cancel
        mgr._redis_client = mock_redis
        mgr._is_running = True

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await mgr._listen_loop()
            mock_sleep.assert_awaited_with(2.0)

    def test_module_level_helpers(self) -> None:
        """Verify get_account_cache and clear_account_cache."""
        cache = get_account_cache()
        assert isinstance(cache, AccountCacheManager)

        aid = uuid4()
        cache.put(aid)
        assert cache.is_cached(aid) is True

        clear_account_cache()
        assert cache.is_cached(aid) is False
