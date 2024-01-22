from datetime import datetime
from unittest import expectedFailure
# from fastapi import FastAPI
from fastapi import Query
# from fastapi_cache import FastAPICache, caches, cache

from topcryptolist.app import app
from ranking import api_connector

from topcryptolist.api.schemas import (
    GetTopCryptoListSchema,
)
from typing import Annotated, List, Optional, Union
from redis.exceptions import RedisError

import pricing
import json
import redis

# Request Publish 
# config = {
#     "ranking_request_queue": "ranking_request_queue",
#     "ranking_result_queue": "ranking_result_queue",
#     "pricing_request_queue": "pricing_request_queue",
#     "pricing_result_queue": "pricing_result_queue",
# }

def save_to_redis(redis_key, data):
    try:
        # Cache the response in Redis with a TTL of 300 seconds (adjust as needed)
        app.state.redis.setex(redis_key, 300, json.dumps(data))
        # app.state.redis.set(redis_key, data)
        print(f'Successfully set key "{redis_key}" in Redis.')
    except RedisError as e:
        print(f'Error setting key "{redis_key}" in Redis: {e}')
    except Exception as e:
        print(f'Unexpected error: {e}')

# async def publish_ranking_request(limit, timestamp = datetime.now()):    
#     # return f"{{'limit': {limit}, 'timestamp': {timestamp} }}"
#     msg = {"limit": limit, "timestamp": timestamp}
#     app.state.redis.lpush("ranking_request_queue", json.dumps(msg))
#     app.state.redis.lpush("princing_request_queue", json.dumps(msg))
#     result = app.state.redis.blpop("toplist")[1]
#     return result.decode('utf-8')

async def fetch_toprank_data(request_id):

    # app.state.redis.xadd("toprank_requests", {"request_id": request_id})
    stream = app.state.config["redis"]["stream_names"]["rank_requests"]
    app.state.redis.xadd(stream, {"request_id": request_id})
                               
    # await app.state.redis.xadd(app.state.config["redis"]["stream_names"]["rank_requests"],
    #                            {"request_id": request_id},
    #                            id=request_id, mkstream=True, 
    #                            group=app.state.config["redis"]["consumer_groups"]["rank_requests"])

    # stream = app.state.config["redis"]["stream_names"]["price_requests"]
    # app.state.redis.xadd(stream, {"request_id": request_id})

    # app.state.redis.xadd(app.state.config["redis"]["stream_names"]["price_requests"],
    #                     {"request_id": request_id},
    #                     id=request_id, mkstream=True, 
    #                     group=app.state.config["redis"]["consumer_groups"]["price_requests"])

    # response = await app.state.redis.xclaim(app.state.config["redis"]["stream_names"]["topcoinsrank"], consumer_group, consumer_name, lease_duration_ms, message_id)
    stream = app.state.config["redis"]["stream_names"]["topcoinsrank"]
    consumer_group = app.state.config["redis"]["consumer_groups"]["topcoinsrank"]
    consumer_name = "HTTP_API_Consumer"
    lease_duration_ms = 10000
    # streams = ["rank_req"]
    latest_ids=[">"]
    count = 1
    print("xread_group ", consumer_group)
    res = await app.state.redis.xread_group(group_name=consumer_group, consumer_name=consumer_name, streams=[stream], count=count,
                                  latest_ids=latest_ids)
    print(res)
    # message = await app.state.redis.xrange(stream_name, '-', '+', count=1)
    while True:
        # message = app.state.redis.xread(stream_name, count=1)        
        print(f"Waiting a message at {stream}")
        message = await app.state.redis.xrange(stream, '-', '+', count=1)

        # message = await redis.xrange(stream_name, '-', '+', count=1)
        if message:
    # consumer_group = "topcoinsrank_consumers"
    # consumer_name = "topconsumer"
    # lease_duration_ms  = 15000
    # if message:
            message_id = message[0][0].decode()
            toprank_response = message[0][1][b'request_id'].decode()
            return toprank_response
        # response = await app.state.xclaim(stream_name, consumer_group, consumer_name, lease_duration_ms, message_id)
        else:
            print(f"No new messages at {stream}. Waiting for the next one...")

    # response = await app.state.redis.xread(app.state.config["redis"]["stream_names"]["topcoinsrank"], count=1, block=30000)
    
    # toprank_response = json.loads(response[0][1][0][1].decode())

    # save_to_redis(request_id, toprank_response)

    # return {"toprank_response": toprank_response}

@app.get("/")
async def getTopCryptoList(
    limit: int = Query(..., title="The number of items to retrieve", ge=1),
    timestamp: int = Query(None, title="The timestamp of the request", description="Optional timestamp parameter"),
    format: str = Query("JSON", title="The format of the response", description="Optional response format parameter (JSON or CSV)")
):
    try:    
        if not await app.state.redis.execute("PING"):            
            return json.dumps("Message broker is not ready")
    except redis.exceptions.ConnectionError as e:
        return json.dumps({"Message broker is not ready"})

    try:
        # Use the provided timestamp as the request ID, or use "now" if not provided
        request_id = timestamp or str("Now")
        
        # # Using timestamp as message_id
        # if timestamp is None:
        #     timestamp = int(datetime.now().timestamp())
        
        # ranking_data = app.state.redis.get(request_id)

        # if ranking_data is None: # Not in cache
            # ranking_data = await publish_ranking_request(limit, timestamp)
        ranking_data = await fetch_toprank_data(request_id)
            # response = await api_connector.topcoins_ranking()
            # save_to_redis('ranking_data', ranking_data)
        return json.loads(ranking_data)
    except json.JSONDecodeError as e:
        return {f"Unexpected UTF-8 BOM (decode using utf-8-sig) - Value: {ranking_data}"}
    except TypeError as e:
        return {'The JSON object must be str, bytes or bytearray'}
    except Exception as e:
        return {"Error featching the data"}