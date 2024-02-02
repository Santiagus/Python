import aioredis
from tenacity import retry, stop_after_attempt, retry_if_exception_type, wait_random_exponential
import logging
from redis import RedisError

def log_retry_info(retry_state):
    """
    Logs retry information for Redis connection attempts during tenacity retries.
    This function, designed to be used as a callback in tenacity, logs retry-related details
    when attempting to connect to a Redis server.

    Parameters:
    - retry_state (tenacity.RetryCallState): The state information for the current retry operation.

    Logs:
    - If retry_state is not None, it logs information about the Redis connection failure, including the waiting time, attempt number, and maximum attempt number.
    - If retry_state is None, it issues a warning indicating that the retry state or next action is unavailable.

    Usage:
    - Integrate this function as a callback in tenacity.retry to capture and log retry details during Redis connection attempts.

    Returns:
    - None
    """

    logger = logging.getLogger(__name__)

    if retry_state:
        logger.info("Redis connection failed. Retrying in (%d-%d)s. Attempt %d",
                    retry_state.retry_object.wait.min,
                    retry_state.retry_object.wait.max,
                    retry_state.attempt_number,
                    )
    else:
        logger.warning("Retry state or next_action is None. Unable to log retry information.")



@retry(
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(ConnectionRefusedError),
    wait=wait_random_exponential(min=5, max=20),
    after=log_retry_info
)
async def connect_to_redis(config):
    """
    Asynchronous function to establish a connection to a Redis server based on the provided configuration.
    Parameters:
    - config (dict): A dictionary containing the Redis connection configuration, including 'host' and 'port'.
    Returns:
    - aioredis.Redis: A connection pool to the Redis server upon successful connection.
    Raises:
    - ConnectionRefusedError: If the connection to the Redis server is refused.
    - Exception: For any other unexpected errors during the connection attempt.

    This function uses the aioredis library to create an asynchronous connection pool to a Redis server.
    It attempts to connect to the specified host and port, and if successful, verifies the connection with
    a PING command. In case of a refused connection, it raises a ConnectionRefusedError.
    For any other unexpected errors, a generic Exception is raised with an associated error message.
    """
    host, port = config['host'], config['port']
    redis = None
    try:
        redis = await aioredis.create_redis_pool((host, port))
        if await redis.execute("PING"):
            logging.info("Connected to Redis successfully. ")
            return redis
    except ConnectionRefusedError as e:
        logging.error(f"ConnectionRefusedError: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error occurred: {e}")
        return None


async def save_to_redis(redis, redis_key, data):
    """
    Asynchronously save data to a Redis store with a specified key.

    Parameters:
        - `redis`: The Redis connection pool or client.
        - `redis_key` (str): The key under which the data will be stored in Redis.
        - `data`: The data to be saved to Redis.

    Raises:
        - `aioredis.RedisError`: If there is an error while interacting with Redis.

    Returns:
        - bool: True if the data is successfully saved to Redis, False otherwise.

    Example:
        ```python
        # Assuming `redis_pool` is an instance of aioredis.Redis connection pool
        result = await save_to_redis(redis_pool, "my_data_key", {"name": "John", "age": 30})
        if result:
            print("Data successfully saved to Redis.")
        else:
            print("Failed to save data to Redis.")
        ```
    """
    try:
        success = await redis.set(redis_key, data)
        if success:
            logging.info(f'Successfully set key "{redis_key}" in Redis.')
            return True
        return False
    except RedisError as e:
        logging.error(f'Error setting key "{redis_key}" in Redis: {e}')
        return False
    except Exception as e:
        logging.error(f'Unexpected error: {e}')
        return False