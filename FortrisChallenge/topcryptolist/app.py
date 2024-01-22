from fastapi import FastAPI
from redis import Redis
# from contextlib import asynccontextmanager
from redis import exceptions
import aioredis

import retry
import httpx
import aioredis
import json
import utils

app = FastAPI(debug=True)

from topcryptolist.api import api

# @retry.retry(Exception, delay=1, backoff=2, max_delay=10, tries=-1)
# async def connect_to_redis():
#     # return Redis(host=app.state.config["redis"]["host"], port=app.state.config["redis"]["port"])    
#     return await aioredis.create_redis_pool((app.state.config["redis"]["host"], app.state.config["redis"]["port"]))
#     return = await aioredis.create_redis_pool("redis://localhost")

    # return await aioredis.create_redis_pool("redis://localhost")

async def check_consumer_groups(redis, stream_name):
    # Use XINFO GROUPS to get information about consumer groups for a stream
    try:
        info_groups = await redis.xinfo_groups(stream_name)
        print(f"Consumer Groups for Stream '{stream_name}': {info_groups}")
    except Exception as e:
        print(f"Erron when featching groups info : {stream_name}")

async def create_consumer_groups(redis, stream_names):
    consumer_group = app.state.config["redis"]["consumer_groups"]["topcoinsrank"]
    consumer_name="topcoinsrank_consumer"
    streams = ["topcoinsrank"]
    latest_ids=[">"]
    count = 1

    res = ""
    for stream in stream_names.values():
        # await app.state.redis.xgroup_create(stream, str(stream + "_consumers"), id='0', mkstream=True)
        try:
            await check_consumer_groups(redis, stream)
            res = await redis.xgroup_create(stream, str(stream + "_consumers"), mkstream=True) #, id='0', mkstream=True)
            await check_consumer_groups(redis, stream)
            if res:
                print(f"Created redis group '{str(stream + '_consumers')}' in stream '{stream}'")
        except Exception as e:
            print(f"Redis group '{str(stream + '_consumers')}' in stream '{stream}' already exists.")
            # print(f"Redis group creation failed ({e}): {res}")
@app.on_event("startup")
async def startup_event():
    try:        
        config_path = 'config.json'
        app.state.config = utils.load_config_from_json(config_path)
        # Use the retry decorator to attempt connection to Redis
        # app.state.redis = connect_to_redis()
        # app.state.redis = await aioredis.create_redis_pool("redis://localhost")
        app.state.redis = await aioredis.create_redis_pool(('localhost', 6379))

        app.state.http_client = httpx.AsyncClient()
        if await app.state.redis.execute("PING"):
            print("Connected to Redis successfully.")
            await create_consumer_groups(app.state.redis, app.state.config["redis"]['stream_names'])
                # Send a request to Redis Stream
            # stream_name = "toprank_requests"
            # consumer_group = "ranking_consumers"
            # await app.state.redis.xgroup_create(stream_name, consumer_group, id='0', mkstream=True)

    except exceptions.ConnectionError as error:
        print(error)
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")

@app.on_event("shutdown")
async def shutdown_event():
   app.state.redis.close()