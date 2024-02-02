import asyncio
import pytest
from unittest.mock import AsyncMock, patch, Mock
from merge_service.merger import read_last_message, run_task_with_name, main

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
        return "done"

    result, name = await run_task_with_name("stream1", task_coroutine())
    
    assert result == "done"
    assert name == "stream1"


# @pytest.mark.asyncio
# async def test_gather_tasks_results():
#     gather_results ="[([(b'1706868720-0', OrderedDict([(b'data', b'[{'Id': 1, 'Symbol': 'BTC', 'Price USD': 42938.387890741134}, {'Id': 6636, 'Symbol': 'DOT', 'Price USD': 6.897947694471983}, {'Id': 6535, 'Symbol': 'NEAR', 'Price USD': 2.8473485529266194}, {'Id': 28316, 'Symbol': 'UPRO', 'Price USD': 0.1939634372046452}]')]))], 'price'), ([(b'1706868720-0', OrderedDict([(b'data', b'[{'Id': 1, 'Symbol': 'BTC'}, {'Id': 1027, 'Symbol': 'ETH'}, {'Id': 2482, 'Symbol': 'CPC'}, {'Id': 2321, 'Symbol': 'QLC'}]')]))], 'rank')]"
#     # async def task_coroutine():
#     await asyncio.sleep(1)
#     return gather_results
# @pytest.mark.asyncio
# async def mock_coroutine():
#     gather_results ="[([(b'1706868720-0', OrderedDict([(b'data', b'[{'Id': 1, 'Symbol': 'BTC', 'Price USD': 42938.387890741134}, {'Id': 6636, 'Symbol': 'DOT', 'Price USD': 6.897947694471983}, {'Id': 6535, 'Symbol': 'NEAR', 'Price USD': 2.8473485529266194}, {'Id': 28316, 'Symbol': 'UPRO', 'Price USD': 0.1939634372046452}]')]))], 'price'), ([(b'1706868720-0', OrderedDict([(b'data', b'[{'Id': 1, 'Symbol': 'BTC'}, {'Id': 1027, 'Symbol': 'ETH'}, {'Id': 2482, 'Symbol': 'CPC'}, {'Id': 2321, 'Symbol': 'QLC'}]')]))], 'rank')]"
#     # async def task_coroutine():
#     await asyncio.sleep(1)
#     return gather_results
@pytest.mark.asyncio
async def mock_coroutine():
    await asyncio.sleep(1)  # Simulate some asynchronous operation (e.g., fetching data)
    
    # Simulate the result you expect
    gather_results = "[{'Id': 1, 'Symbol': 'BTC', 'Price USD': 42938.387890741134}, " \
                     "{'Id': 2, 'Symbol': 'ETH', 'Price USD': 2305.1541836162664}, " \
                     "{'Id': 3, 'Symbol': 'SOL', 'Price USD': 100.60050843848062}]"
    
    return gather_results

@pytest.mark.asyncio
async def test_main_successful_execution():
    config = {
        'logging': {
            'version': 1,
            'disable_existing_loggers': False,
            'formatters': {'verbose': {'format': '{levelname:<8} {asctime} [{module:<16}] {message}', 'style': '{'}},
            'handlers': {'file': {'level': 'ERROR', 'class': 'logging.FileHandler', 'filename': 'price_service.log', 'formatter': 'verbose'},
                         'console': {'level': 'DEBUG', 'class': 'logging.StreamHandler', 'formatter': 'verbose'}},
            'root': {'level': 'INFO', 'handlers': ['file', 'console']}
        },
        'redis': {'host': 'localhost', 'port': 6379, 'stream': 'price', 'interval': 60}
    }

    merged_data = '[{"Rank": 1, "Symbol": "BTC", "Price USD": 42938.387890741134}, {"Rank": 2, "Symbol": "ETH", "Price USD": 2305.1541836162664}, ... ]'

    mocked_redis = AsyncMock()

    with patch('price_service.price_publisher.load_config_from_json', return_value=config):
        with patch('price_service.price_publisher.connect_to_redis'):
            with patch('asyncio.gather', return_value=[mock_coroutine() for _ in range(2)]):
                with patch("common.utils.unix_timestamp_to_iso", return_value="2022-01-01T00:00:00"):
                    with patch("common.utils.round_to_previous_minute", return_value=1640995200):
                        with patch("common.utils.merge_data", return_value=merged_data):
                            await main()

                            mocked_redis.set.called

