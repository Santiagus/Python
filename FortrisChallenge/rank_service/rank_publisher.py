import asyncio
import logging
import logging.config
import time
from tenacity import RetryError
import schedule
from common.utils import seconds_until_next_minute, load_config_from_json
from common.redis_utils import connect_to_redis
from shared.data_fetcher import DataFetcher, CustomApiException
from shared.publisher import Publisher



async def main():
    """
    Orchestrates the execution of the ranking-related service.

    This function initializes components, such as data fetching, Redis connection, and the main publisher.
    It handles environment configuration, initial data synchronization, scheduled updates, error handling, and a graceful exit.

    :raises RetryError: If retry operation fails.
    :raises ConnectionRefusedError: If connection to Redis is refused.
    :raises APIKeyMissingError: If the API key is missing.
    :raises RuntimeError: If a runtime error occurs.
    :raises Exception: For any unexpected errors.

    :return: None
    """
    redis = None
    try:
        # Configuration
        config = load_config_from_json('rank_service/config.json')

        # Set up logging based on the configuration
        logging.config.dictConfig(config["logging"])

        logging.info(f"Service start. Loading configuration...")

        # Initialize DataFetcher, Redis and Publisher
        rank_config = load_config_from_json('config/rank_config.json')
        data_fetcher = DataFetcher(rank_config)
        redis = await connect_to_redis(config["redis"])

        publisher = Publisher(config, data_fetcher, redis)

        # Synchronization to the minute for first stream update
        seconds = seconds_until_next_minute()
        logging.info(f"Synchronizing to rounded minute. Sending data in {seconds} seconds.")
        time.sleep(seconds)
        await publisher.send_data_to_redis_stream()

        schedule.every(config['redis']['interval']).seconds.do(
            lambda: asyncio.create_task(publisher.send_data_to_redis_stream())
        )
        while True:
            schedule.run_pending()
            await asyncio.sleep(5)
    except RetryError as e:
        logging.error(f"Retry operation failed: {e}")
    except ConnectionRefusedError as e:
        logging.error(f"Failed to connect to Redis: {e}")
    except CustomApiException as e:
        logging.error(f'API Error ({e.json_data.get("Err").get("type")}): {e.json_data.get("Err").get("message")}')
        logging.error(f"Publisher can not access to data source without APIKey.")
    except RuntimeError as e:
        logging.error(f"RuntimeError: {e}")    
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        logging.exception("Stack trace:")
    finally:
        logging.info("Exiting program.")
        if redis is not None:
            redis.close()
            await redis.wait_closed()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Script interrupted by user.")
    except asyncio.CancelledError:
        logging.info("Script cancelled. Cleaning up and exiting gracefully.")
