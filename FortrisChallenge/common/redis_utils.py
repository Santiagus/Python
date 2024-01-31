import aioredis
from tenacity import retry, stop_after_attempt, retry_if_exception_type, wait_fixed
import logging

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
        logger.info("Redis connection failed. Retrying in %ds. Attempt %d/%d",
                    retry_state.retry_object.wait.wait_fixed,
                    retry_state.attempt_number,
                    retry_state.retry_object.stop.max_attempt_number)
    else:
        logger.warning("Retry state or next_action is None. Unable to log retry information.")

@retry(
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(ConnectionRefusedError),
    wait=wait_fixed(3),
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
        raise e
    except Exception as e:
        logging.error(f"Unexpected error occurred: {e}")
        raise e