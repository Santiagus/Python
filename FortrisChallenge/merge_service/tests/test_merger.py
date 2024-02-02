import time
import asyncio
import json
import logging
from unittest.mock import Mock, patch
import pytest
from common.utils import round_to_previous_minute, unix_timestamp_to_iso, load_config_from_json, merge_data, unpack_message
from merge_service.merger import read_last_message, run_task_with_name, main

import sys
print(sys.path)

@pytest.fixture
def mocked_config():
    return {
        "logging": {"level": "DEBUG"},
        "redis": {
            "host": "localhost",
            "port": 6379,
            "source_streams": ["stream1", "stream2"],
            "main_stream": "main_stream",
            "interval": 5,
        },
    }


@pytest.fixture
def mocked_redis():
    return Mock()


@pytest.fixture
def mocked_result():
    return [(123456789, b'{"data": "message"}')]


@pytest.mark.asyncio
async def test_read_last_message(mocked_redis, mocked_result):
    mocked_redis.xrevrange.return_value = asyncio.Future()
    mocked_redis.xrevrange.return_value.set_result(mocked_result)

    result = await read_last_message(mocked_redis, "stream1")

    assert result == mocked_result


@pytest.mark.asyncio
async def test_run_task_with_name():
    async def task_coroutine():
        await asyncio.sleep(1)
        return "sup"

    result, name = await run_task_with_name("stream1", task_coroutine)

    assert result == "result"
    assert name == "stream1"


@pytest.mark.asyncio
async def test_main(mocked_config, mocked_redis, mocked_result):
    mocked_redis.set.return_value = asyncio.Future()
    mocked_redis.set.return_value.set_result(True)

    with patch("asyncio.gather", return_value=[(123456789, b'{"data": "message"}')]):
        with patch("time.sleep"):
            with patch("common.utils.merge_data", return_value="merged_data"):
                with patch("common.utils.unix_timestamp_to_iso", return_value="2022-01-01T00:00:00"):
                    with patch("common.utils.round_to_previous_minute", return_value=1640995200):
                        await main()

    assert mocked_redis.set.called
