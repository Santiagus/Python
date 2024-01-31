from datetime import datetime
from unittest import expectedFailure
from fastapi import Query
from fastapi.responses import PlainTextResponse
from topcryptolist.app import app, connect_to_redis
from typing import Annotated, List, Optional, Union
from redis.exceptions import RedisError
import aioredis
import asyncio
import json
import pandas as pd
from fastapi import HTTPException


async def save_to_redis(redis_key, data):
    try:        
        retval = app.state.redis.set(redis_key, data)
        await app.state.redis.set(redis_key, data)
        print(f'Successfully set key "{redis_key}" in Redis.{retval}')
    except RedisError as e:
        print(f'Error setting key "{redis_key}" in Redis: {e}')
    except Exception as e:
        print(f'Unexpected error: {e}')

def unix_to_iso(unix_timestamp):
    # Convert Unix timestamp to datetime object
    dt_object = datetime.utcfromtimestamp(unix_timestamp)
    # Format the datetime object as ISO format
    iso_format = dt_object.isoformat()
    return iso_format
 
def round_to_previous_minute(timestamp, unix_format = False):    
    if unix_format:
        timestamp = datetime.fromtimestamp(timestamp)    
    rounded_dt = timestamp.replace(second=0, microsecond=0)    
    rounded_timestamp = int(rounded_dt.timestamp())
    return rounded_timestamp


async def stream_groupinfo_exists(redis, stream_name):    
    try:
        info_groups = await redis.xinfo_groups(stream_name)
        print(f"Consumer Groups for Stream '{stream_name}': {info_groups}")
        return info_groups != []
    except Exception as e:
        print(f"Error when featching groups info : {stream_name}")

async def create_consumer_groups(redis, stream_name, group_name):    
    try:
        res = await redis.xgroup_create(stream_name, group_name, mkstream=True)
        print(f"Created redis group '{group_name}' in stream '{stream_name}'")    
    except aioredis.errors.BusyGroupError as e:
        print(f"Redis group '{group_name}' in stream '{stream_name}' already exists.")
    return None

async def consume_stream(redis, stream, stream_group_config, request_id):
    # Check messages in response stream
    msg_pending  = await redis.xlen(stream)
    for i in range(msg_pending):    
        message = await redis.xrange(stream, '-', '+', count=1)
        message_id = message[0][0].decode()        
        if request_id == float(message[0][1][b'request_id'].decode()):
            await redis.xdel(stream, message_id)
            return message[0][1][b'data'].decode()
        await redis.xdel(stream, message_id)
        i += 1

    # Wait for ranking data response
    if not await stream_groupinfo_exists(redis, stream):
        await create_consumer_groups(redis, stream, stream_group_config['group_name'])
    
    while True:        
        message = await redis.xread_group(**stream_group_config)
        message_id = message[0][1].decode()        
        if request_id == float(message[0][2][b'request_id'].decode()):
            await redis.xdel(stream, message_id)
            return message[0][2][b'data'].decode()

def merge_results(json_data_array):
    data_sample1 = json_data_array[0]
    data_sample2 = json_data_array[1]
    
    df1 = pd.DataFrame(json.loads(data_sample1))
    df2 = pd.DataFrame(json.loads(data_sample2))    
    
    # Merge DataFrames
    merged_df = pd.merge(df1, df2, on=['Id', 'Symbol'], suffixes=('_df1', '_df2'))    
    merged_df.index = pd.RangeIndex(start=1, stop=len(merged_df)+1, name='Rank')    
    merged_df = merged_df.drop('Id', axis=1)    
    merged_df.reset_index(inplace = True)
    
    return merged_df.to_json(orient='records', indent=True)

async def fetch_toprank_data(request_id, get_latest_data):
    
    service_names = ['ranking','pricing']
    tasks = []

    for service in service_names:
        # Request ranking data
        requests_stream = app.state.config['groups'][service]['requests']['stream']
        app.state.redis.xadd(requests_stream, {"request_id": request_id,"get_latest_data": str(get_latest_data)})

        # Get config    
        responses_stream = app.state.config['groups'][service]['responses']['stream']
        stream_group_config = app.state.config['groups'][service]['responses']['group']
        
        # Create tasks to consume each response streams concurrently
        task = asyncio.create_task(consume_stream(app.state.redis, responses_stream, stream_group_config, request_id))
        tasks.append(task)

    results = await asyncio.gather(*tasks)
    
    return merge_results(results)    

async def read_last_message(redis, stream):
    try:
        result = await redis.xrevrange(stream, count=1, start='+', stop='-')
        return result
    except Exception as e:
        print(f'Error reading the most recent message from stream {stream}: {e}')
        return None


async def json_to_csv(json_data):
    import io
    import csv

    header = json_data[0].keys() if json_data else []
    csv_buffer = io.StringIO()  # Pass newline='' to force '\n'
    csv_writer = csv.DictWriter(csv_buffer, fieldnames=header, lineterminator="\n")
    csv_writer.writeheader()
    csv_writer.writerows(json_data)
    csv_content = csv_buffer.getvalue()
    csv_buffer.close()
    print(csv_content)
    return csv_content

@app.get("/")
async def getTopCryptoList(
    limit: int = Query(..., title="The number of items to retrieve", ge=1),
    timestamp: int = Query(None, title="The timestamp of the request", description="Optional timestamp parameter"),
    format: str = Query("JSON", title="The format of the response", description="Optional response format parameter (JSON or CSV)")
):
    # Check redis connectivity
    if app.state.redis is None:
        raise HTTPException(status_code=500, detail="Internal Server Error")
    
    ranking_data = None
    get_latest_data = False

    # Use timestamp as id/key for messages and db/cache
    if timestamp:   
        # Check in database/cache
        request_id = round_to_previous_minute(timestamp, unix_format=True)
        ranking_data = await app.state.redis.get(str(request_id))
    else: 
        # Generate timestamp as identifier and activate flag
        get_latest_data = True
        request_id = datetime.now().timestamp() # Do not round it here to avoid other instances to pick same msg

    if ranking_data is None: # Not in cache or "latest" resquest
        ranking_data = await fetch_toprank_data(request_id, get_latest_data)        
        if get_latest_data:
            request_id = round_to_previous_minute(request_id, unix_format=True)
        await save_to_redis(str(request_id), ranking_data)

    # Output formating
    ranking_data = json.loads(ranking_data)
    ranking_data = ranking_data[:limit]
    if format.upper() == 'CSV':
        csv = await json_to_csv(ranking_data)
        return PlainTextResponse(content=csv, media_type="text/csv")

    return ranking_data

    # except json.JSONDecodeError as e:
    #     return {f"Unexpected UTF-8 BOM (decode using utf-8-sig) - Value: {ranking_data}"}
    # except TypeError as e:
    #     return {'The JSON object must be str, bytes or bytearray'}
    # except Exception as e:
    #     return {"Error featching the data"}