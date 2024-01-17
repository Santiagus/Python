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
config = {
    "ranking_request_queue": "ranking_request_queue",
    "ranking_result_queue": "ranking_result_queue",
    "pricing_request_queue": "pricing_request_queue",
    "pricing_result_queue": "pricing_result_queue",
}

def save_to_redis(redis_key, data):
    try:
        app.state.redis.set(redis_key, data)
        print(f'Successfully set key "{redis_key}" in Redis.')
    except RedisError as e:
        print(f'Error setting key "{redis_key}" in Redis: {e}')
    except Exception as e:
        print(f'Unexpected error: {e}')

async def publish_ranking_request(limit, timestamp = datetime.now()):    
    # return f"{{'limit': {limit}, 'timestamp': {timestamp} }}"
    msg = {"limit": limit, "timestamp": timestamp}
    app.state.redis.lpush("ranking_request_queue", json.dumps(msg))
    app.state.redis.lpush("princing_request_queue", json.dumps(msg))
    result = app.state.redis.blpop("toplist")[1]
    return result.decode('utf-8')

@app.get("/")
async def getTopCryptoList(
    limit: int = Query(..., title="The number of items to retrieve", ge=1),
    timestamp: int = Query(None, title="The timestamp of the request", description="Optional timestamp parameter"),
    format: str = Query("JSON", title="The format of the response", description="Optional response format parameter (JSON or CSV)")
):
    try:    
        if not app.state.redis.ping():
            return json.dumps("Message broker is not ready")
    except redis.exceptions.ConnectionError as e:
        return json.dumps({"Message broker is not ready"})

    try:
        # Using timestamp as message_id
        if timestamp is None:
            timestamp = int(datetime.now().timestamp())
        
        ranking_data = app.state.redis.get(timestamp)
        if ranking_data is None:            
            ranking_data = await publish_ranking_request(limit, timestamp)
            # response = await api_connector.topcoins_ranking()
            save_to_redis('ranking_data', ranking_data)
        return json.loads(ranking_data)
    except json.JSONDecodeError as e:
        return {f"Unexpected UTF-8 BOM (decode using utf-8-sig) - Value: {ranking_data}"}
    except TypeError as e:
        return {'The JSON object must be str, bytes or bytearray'}
    except Exception as e:
        return {"Error featching the data"}