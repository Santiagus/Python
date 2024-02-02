import asyncio
from tenacity import RetryError
from unittest.mock import patch, MagicMock
import pytest
from rank_service.rank_publisher import main


config = {
    'logging': {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {'verbose': {'format': '{levelname:<8} {asctime} [{module:<16}] {message}', 'style': '{'}},
        'handlers': {'file': {'level': 'ERROR', 'class': 'logging.FileHandler', 'filename': 'rank_service.log', 'formatter': 'verbose'},
                        'console': {'level': 'DEBUG', 'class': 'logging.StreamHandler', 'formatter': 'verbose'}},
        'root': {'level': 'INFO', 'handlers': ['file', 'console']}
    },
    'redis': {'host': 'localhost', 'port': 6379, 'stream': 'rank', 'interval': 60}
}

@pytest.mark.asyncio
async def test_main_successful_execution():
    with patch('rank_service.rank_publisher.load_config_from_json', return_value=config):
        with patch('rank_service.rank_publisher.DataFetcher') as mock_data_fetcher:
            with patch('rank_service.rank_publisher.connect_to_redis') as mock_connect_to_redis:
                with patch('rank_service.rank_publisher.Publisher') as mock_publisher:
                    await main()

    mock_data_fetcher.assert_called_once()
    mock_connect_to_redis.assert_called_once_with(config['redis'])
    mock_publisher.assert_called_once_with(config, mock_data_fetcher.return_value, mock_connect_to_redis.return_value)


@pytest.mark.asyncio
async def test_main_retry_error():
    with patch('rank_service.rank_publisher.load_config_from_json', return_value=config):
        with patch('rank_service.rank_publisher.DataFetcher') as mock_data_fetcher:
            with patch('rank_service.rank_publisher.connect_to_redis', side_effect=RetryError):
                with patch('rank_service.rank_publisher.Publisher') as mock_publisher:
                    await main()

    mock_data_fetcher.assert_called_once()
    mock_publisher.assert_not_called()

