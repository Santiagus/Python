import json
import logging
from common.utils import rounddown_time_to_minute, unix_timestamp_to_iso
from common.redis_utils import connect_to_redis


class Publisher:
    def __init__(self, config, data_fetcher, redis):
        """
        Initialize the Publisher.
        Parameters:
        - config (dict): Configuration settings for the Publisher.
        - data_fetcher (object): An object responsible for fetching data.
        - redis: An initialized connection to a Redis server.
        """        
        self.config = config
        self.data_fetcher = data_fetcher
        self.redis = redis

    async def init_async(self):
        """
        Asynchronously initialize the Redis connection.
        """
        self.redis = await connect_to_redis(self.config)

    def check_dependencies_are_set(self):
        """
        Check if essential dependencies are set (non-None) before performing operations.

        Raises:
        - RuntimeError: If any essential dependency is not initialized.
        """
        if self.config is None:
            raise RuntimeError("Config is not initialized.")
        if self.data_fetcher is None:
            raise RuntimeError("Data fetcher is not initialized.")
        if self.redis is None:
            raise RuntimeError("Redis connection is not initialized.")
    
    async def send_data_to_redis_stream(self):
        """
        Send data to the specified Redis stream.

        Raises:
        - RuntimeError: If essential dependencies are not set.
        """
        self.check_dependencies_are_set()

        # Fetch data from the data fetcher.
        data = await self.data_fetcher.get_data()        
        json_data = json.dumps(data)

        # Publish the data to the specified Redis stream.
        self.redis.xadd(self.config['redis']['stream'],
                        {'data': json_data }, 
                        message_id=(str(rounddown_time_to_minute()) + '-0').encode('utf-8'),
                        max_len=1)
        logging.info(f"[{self.config['redis']['stream']}] : {unix_timestamp_to_iso(rounddown_time_to_minute())}: {json_data[:100]}")
