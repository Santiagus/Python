from fastapi import FastAPI
from redis import Redis
# from contextlib import asynccontextmanager
from redis import exceptions

import retry
import httpx
import aioredis
import json

app = FastAPI(debug=True)

from topcryptolist.api import api

@retry.retry(Exception, delay=1, backoff=2, max_delay=10, tries=-1)
def connect_to_redis():
    return Redis(host='localhost', port=6379)

@app.on_event("startup")
async def startup_event():
    try:
        # Use the retry decorator to attempt connection to Redis
        app.state.redis = connect_to_redis()
        app.state.http_client = httpx.AsyncClient()
        if app.state.redis.ping():
            print("Connected to Redis successfully.")
    except exceptions.ConnectionError as error:
        print(error)
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")

@app.on_event("shutdown")
async def shutdown_event():
   app.state.redis.close()