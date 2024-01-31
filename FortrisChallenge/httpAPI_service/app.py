from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
# from starlette.lifespan import Lifespan
from redis import Redis
# from contextlib import asynccontextmanager
from redis import exceptions
import aioredis

import tenacity
import httpx
import aioredis
import json
from common.redis_utils import connect_to_redis
from common.utils import seconds_until_next_minute, load_config_from_json, setup_logging

import sys

# @tenacity.retry(
#     stop=tenacity.stop_after_attempt(3),
#     retry=tenacity.retry_if_exception_type(ConnectionRefusedError),
#     wait=tenacity.wait_fixed(3),
# )
# async def connect_to_redis(host, port):
#     try:
#         redis = await aioredis.create_redis_pool((host, port))
#         if await redis.execute("PING"):
#             print("Connected to Redis successfully.")
#             return redis
#     except ConnectionRefusedError as e:
#         print(f"ConnectionRefusedError: {e}")
#         raise e
#     except Exception as e:
#         print(f"An unexpected error occurred: {e}")
#         raise e


@asynccontextmanager
async def lifespan(app: FastAPI):
    # try:
        # Inicialization (Load config, stablish connections, ...)
        config_path = 'config.json'
        app.state.redis = None
        app.state.config = load_config_from_json(config_path)
        app.state.redis = await connect_to_redis(app.state.config["host"], app.state.config["port"])

        yield

        # Shutdown (Close connections to msg broker, db, ...)
        if app.state.redis is not None:
            app.state.redis.close()

    # except json.decoder.JSONDecodeError as e:
    #         print(f"Config load error : {e}")
    # except ConnectionRefusedError as e:
    #     print(f"Failed to connect to Redis: {e}")
    # except tenacity.RetryError:
    #     print("Failed to connect to Redis after retries.")
    # except Exception as e:
    #     print(f"An unexpected error occurred during startup: {e}")
    # finally:
    #     if app.state.redis is not None:
    #         app.state.redis.close()
    #     sys.exit(1)  # Exit the application with a non-zero exit code


app = FastAPI(lifespan=lifespan)

from httpAPI_service.api import api
