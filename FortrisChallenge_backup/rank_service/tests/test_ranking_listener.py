import asyncio
import aioredis
import unittest
from unittest.mock import MagicMock, patch
import unittest
from unittest.mock import Mock, patch
from ranking_listener import load_config_from_json, create_redis_group, process_message, main
import json
import tracemalloc

tracemalloc.start()

# async def async_function_under_test():
#     # Some asynchronous code that interacts with a Redis instance
#     redis = await aioredis.create_redis_pool('redis://localhost:6379')
#     value = await redis.get('key')
#     await redis.close()
#     return value

class TestRankingListener(unittest.IsolatedAsyncioTestCase):

    async def test_load_config_from_json(self):        
        sample_config = {
            "host": "localhost",
            "port": 6379,
            "requests": {
                "group": {
                    "group_name": "rank_req_consumers",
                    "consumer_name": "rank_consumer",
                    "streams": [
                        "rank_req"
                    ],
                    "timeout": 0,
                    "count": 1,
                    "latest_ids": [
                        ">"
                    ],
                    "no_ack": False
                },
                "stream": "rank_req",
                "min_idle_time": 10000
            },
            "responses": {
                "stream": "topcoinsrank"
            }
        }

        # Create a temporary file with the sample config
        with open("test_config.json", "w") as test_file:
            json.dump(sample_config, test_file)

        # Load the configuration using the function
        loaded_config = await load_config_from_json("test_config.json")

        # Assert that each value matches the expected sample
        self.assertEqual(loaded_config["host"], "localhost")
        self.assertEqual(loaded_config["port"], 6379)

        self.assertEqual(loaded_config["requests"]["group"]["group_name"], "rank_req_consumers")
        self.assertEqual(loaded_config["requests"]["group"]["consumer_name"], "rank_consumer")
        self.assertEqual(loaded_config["requests"]["group"]["streams"], ["rank_req"])
        self.assertEqual(loaded_config["requests"]["group"]["timeout"], 0)
        self.assertEqual(loaded_config["requests"]["group"]["count"], 1)
        self.assertEqual(loaded_config["requests"]["group"]["latest_ids"], [">"])
        self.assertEqual(loaded_config["requests"]["group"]["no_ack"], False)

        self.assertEqual(loaded_config["requests"]["stream"], "rank_req")
        self.assertEqual(loaded_config["requests"]["min_idle_time"], 10000)

        self.assertEqual(loaded_config["responses"]["stream"], "topcoinsrank")


        # Clean up: remove the temporary file
        import os
        os.remove("test_config.json")
        # return None

    @patch("your_module.your_module_name.aioredis.create_redis_pool")
    async def test_create_redis_group(self, mock_create_redis_pool):
        
        pass

    @patch("your_module.your_module_name.aioredis.create_redis_pool")
    async def test_process_message(self, mock_create_redis_pool):
        # Your test logic here
        pass

    @patch("your_module.your_module_name.aioredis.create_redis_pool")
    async def test_main(self, mock_create_redis_pool):
        # Your test logic here
        pass

if __name__ == "__main__":
    unittest.main()
