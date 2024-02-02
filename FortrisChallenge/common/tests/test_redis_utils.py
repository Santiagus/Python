import pytest
import aioredis
from unittest.mock import AsyncMock, MagicMock
from ..redis_utils import connect_to_redis, save_to_redis, log_retry_info

@pytest.fixture
def redis_config():
    return {'host': 'localhost', 'port': 6379}

@pytest.fixture
def successful_redis_pool():
    pool_mock = MagicMock()
    pool_mock.execute.return_value = "PONG"
    return pool_mock

@pytest.fixture
def failed_redis_pool():
    pool_mock = MagicMock()
    pool_mock.execute.side_effect = ConnectionRefusedError
    return pool_mock

@pytest.mark.asyncio
async def test_connect_to_redis_successful(redis_config, successful_redis_pool):
    with pytest.raises(ConnectionRefusedError):
        await connect_to_redis(redis_config)

    successful_redis_pool.execute.assert_called_with("PING")

@pytest.mark.asyncio
async def test_connect_to_redis_failure(redis_config, failed_redis_pool, caplog):
    with pytest.raises(ConnectionRefusedError):
        await connect_to_redis(redis_config)

    assert "ConnectionRefusedError: " in caplog.text

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
    retry_state_mock = MagicMock()
    retry_state_mock.retry_object.wait.min = 5
    retry_state_mock.retry_object.wait.max = 60
    retry_state_mock.attempt_number = 2

    log_retry_info(retry_state_mock)

    assert "Redis connection failed. Retrying in (5-60)s. Attempt 2" in caplog.text

def test_log_retry_info_no_retry_state(caplog):
    log_retry_info(None)
    assert "Retry state or next_action is None. Unable to log retry information." in caplog.text
