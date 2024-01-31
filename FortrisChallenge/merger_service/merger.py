import time
import redis
import aioredis
import asyncio
from datetime import datetime
# from unittest import expectedFailure
# from fastapi import Query
# from fastapi.responses import PlainTextResponse
# from topcryptolist.app import app, connect_to_redis
# from typing import Annotated, List, Optional, Union
# from redis.exceptions import RedisError
import json
import pandas as pd
# from fastapi import HTTPException

# async def save_to_redis(redis_key, data):
#     try:        
#         retval = redis.set(redis_key, data)
#         await app.state.redis.set(redis_key, data)
#         print(f'Successfully set key "{redis_key}" in Redis.{retval}')
#     except RedisError as e:
#         print(f'Error setting key "{redis_key}" in Redis: {e}')
#     except Exception as e:
#         print(f'Unexpected error: {e}')

asyncio.set_event_loop(asyncio.new_event_loop())  # Set the event loop

def unix_to_iso(unix_timestamp):
    # Convert Unix timestamp to datetime object
    dt_object = datetime.fromtimestamp(unix_timestamp)
    # Format the datetime object as ISO format
    iso_format = dt_object.isoformat()
    return iso_format
 
def round_to_previous_minute(timestamp, unix_format = False):    
    if unix_format:
        timestamp = datetime.fromtimestamp(timestamp)    
    rounded_dt = timestamp.replace(second=0, microsecond=0)    
    rounded_timestamp = int(rounded_dt.timestamp())
    return rounded_timestamp

async def merge_results(data1, data2):
    df1 = pd.DataFrame(json.loads(data1))
    df2 = pd.DataFrame(json.loads(data2))
    
    # Merge DataFrames
    merged_df = pd.merge(df1, df2, on=['Id', 'Symbol'], suffixes=('_df1', '_df2'))    
    merged_df.index = pd.RangeIndex(start=1, stop=len(merged_df)+1, name='Rank')    
    merged_df = merged_df.drop('Id', axis=1)
    merged_df.reset_index(inplace = True)
    #---------------------------------------------
    # pd.set_option('display.max_rows', None)
    pd.set_option('display.max_rows', 10)  # Adjust the number as needed
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)  # Set a large width to avoid line breaks
    # Print the merged DataFrame
    print(merged_df)
    
    # Specify the file path for the CSV file
    csv_file_path = 'merged.csv'
    # Save the DataFrame to a CSV file
    merged_df.to_csv(csv_file_path, index=False)
    #---------------------------------------------
    merged_df = merged_df.drop('TimeStamp_df1', axis=1)
    merged_df = merged_df.drop('TimeStamp_df2', axis=1)
    return merged_df.to_json(orient='records', indent=True)

async def read_stream(redis, stream, messages_queue):
    while True:
        response = await redis.xread(streams=[stream], count=1)
        await messages_queue.put(response)


def unpack_message(message):
    timestamp = int(message[0][0].decode()[:-2])
    data = message[0][1][b'data'].decode()
    return timestamp, data
    

async def merge_and_save(redis, messages_queue):
    # while True:
    # Wait for messages from both streams
    message1 = await messages_queue.get()
    message2 = await messages_queue.get()

    # Unpack to get timestamp and data
    timestamp1, data1 = unpack_message(message1)
    timestamp2, data2 = unpack_message(message2)

    # Merge the messages (customize this part according to your needs)        
    merged_data = await merge_results(data1, data2)

    # Generate redis key
    redis_key = round_to_previous_minute(max(timestamp1, timestamp2), unix_format=True)
    
    # Save the merged data to Redis (customize this part according to your needs)
    print(f"Saving to Redis: {redis_key} : {merged_data[:50]}")
    try:
        success = redis.set(redis_key, merged_data)
        if success:
            print("Data stored successfully")
            save = redis.bgsave()
            print(f"Redis BGSave : {save}")
        else:
            print("Key already exists or there was an issue storing the data")
    except Exception as e:
        print(f"An error occurred: {e}")




async def read_last_message(redis, stream):
    try:
        result = await redis.xrevrange(stream, count=1, start='+', stop='-')
        return result
    except Exception as e:
        print(f'Error reading the most recent message from stream {stream}: {e}')
        return None

async def main():
    # rd = await aioredis.create_redis_pool('redis://localhost:6379')
    redis = await aioredis.create_redis_pool(('localhost', 6379))
    timeout_seconds = 10
    price_stream = 'price'
    ranking_stream = 'ranking'

    try:
        while True:
            # Create asyncio.Tasks for each read operation
            price_task = asyncio.create_task(read_last_message(redis, price_stream))
            ranking_task = asyncio.create_task(read_last_message(redis, ranking_stream))

            # Await the results individually
            price_data = await price_task
            ranking_data = await ranking_task

            # Chech data
            if price_data == [] or ranking_data == []:
                print("Data missing!!")
                time.sleep(timeout_seconds)
                continue

            # Process the results
            price_timestamp, price_data = unpack_message(price_data)
            ranking_timestamp, ranking_data = unpack_message(ranking_data)
            print(f"[{price_stream}  ]: {unix_to_iso(price_timestamp)}: {price_data[:80]}")
            print(f"[{ranking_stream}]: {unix_to_iso(ranking_timestamp)}: {ranking_data[:80]}")
            time.sleep(timeout_seconds)
            
            timediff = price_timestamp - ranking_timestamp
            if timediff > timeout_seconds:
                print(f"[{ranking_stream}]: Not updated. Time difference : {timediff}s")
            elif timediff < -timeout_seconds:
                print(f"[{price_stream}]: Not updated. Time difference : {timediff}s")
            else : # Data sources synchronized
                try:
                    # Generate redis key
                    generated_redis_key = round_to_previous_minute(max(price_timestamp, ranking_timestamp), unix_format=True)                
                    # Merge the messages (Order matters ranking MUST be on the left!!)
                    merged_data = await merge_results(ranking_data, price_data)
                    # Save to redis
                    is_data_saved = redis.set(generated_redis_key, merged_data)
                    print(f"Saving to Redis: {generated_redis_key} : {json.loads(merged_data)[:1]}")
                    success = redis.set(generated_redis_key, merged_data)
                    if success:
                        print("Data stored successfully")
                        # save = redis.bgsave()
                        # print(f"Redis BGSave : {save}")
                    else:
                        print("Key already exists or there was an issue storing the data")
                except Exception as e:
                    print(f"An error occurred: {e}")


    finally:
        redis.close()
        await redis.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())