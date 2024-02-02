import pytest
import logging
import asyncio
import aioredis
from unittest.mock import AsyncMock, MagicMock, patch
from ..redis_utils import connect_to_redis, save_to_redis, log_retry_info


@pytest.fixture
def redis_config():
    return {'host': 'localhost', 'port': 6379}


@pytest.fixture
def wrong_redis_config():
    return {'host': '8.8.8.8', 'port': 80}


@pytest.fixture
def successful_redis_pool():
    pool_mock = MagicMock()
    ping_mock = pool_mock.execute.return_value = asyncio.Future()
    ping_mock.set_result(b'PONG')
    return pool_mock


@pytest.fixture
def failed_redis_pool():
    pool_mock = MagicMock()
    pool_mock.execute.side_effect = ConnectionRefusedError
    return pool_mock


pytest.mark.asyncio
async def test_connect_to_redis_successful(redis_config, successful_redis_pool):
    with patch("aioredis.create_redis_pool", successful_redis_pool):
        redis = await connect_to_redis(redis_config)
        assert redis is not None


@pytest.mark.asyncio
async def test_connect_to_redis_failure(wrong_redis_config, failed_redis_pool):
    with patch("aioredis.create_redis_pool", failed_redis_pool):
            redis = await connect_to_redis(wrong_redis_config)
    assert redis is None


@pytest.mark.asyncio
async def test_save_to_redis_successful():
    redis_mock = AsyncMock()
    redis_mock.set.return_value = True

    result = await save_to_redis(redis_mock, "key", "data")
    assert result is True
    redis_mock.set.assert_called_with("key", "data")


@pytest.mark.asyncio
async def test_save_to_redis_failure():
    redis_mock = AsyncMock()
    redis_mock.set.side_effect = aioredis.RedisError("Redis error")

    result = await save_to_redis(redis_mock, "key", "data")

    assert result is False
    redis_mock.set.assert_called_with("key", "data")


def test_log_retry_info(caplog):
    with caplog.at_level(logging.DEBUG):
        retry_state_mock = MagicMock()
        retry_state_mock.retry_object.wait.min = 5
        retry_state_mock.retry_object.wait.max = 60
        retry_state_mock.attempt_number = 2
        log_retry_info(retry_state_mock)
        assert "Redis connection failed. Retrying in (5-60)s. Attempt 2" in caplog.messages
        assert caplog.records  # Ensure there are log records
        assert caplog.records[0].levelno == logging.INFO
        assert "Redis connection failed. Retrying in (5-60)s. Attempt 2" in caplog.text


def test_log_retry_info_no_retry_state(caplog):
    log_retry_info(None)
    assert "Retry state or next_action is None. Unable to log retry information." in caplog.text
