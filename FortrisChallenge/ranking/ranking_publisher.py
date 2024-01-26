import aioredis
import asyncio
import json
import sys
import tenacity
import logging
import ranking_data_fetcher
import redis.exceptions

# data_sample = '[{"Id": 1, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "BTC"}, {"Id": 1027, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "ETH"}, {"Id": 5426, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "SOL"}, {"Id": 74, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "DOGE"}, {"Id": 13631, "TimeStamp": "2024-01-22T03:13:29", "Symbol": "MANTA"}, {"Id": 52, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "XRP"}]'

async def load_config_from_json(file_path):
    with open(file_path, 'r') as file:
        config_data = json.load(file)
    return config_data


# async def create_redis_group(redis, stream, group_name):
#     try:
#         res = await redis.xgroup_create(stream, group_name, mkstream=True)
#         if res:
#             logging.info(f"Created redis group '{group_name}' in stream '{stream}'")
#     except aioredis.errors.BusyGroupError:        
#         logging.info(f"Redis group '{group_name}' in stream '{stream}' already exists.")



# async def message_unpack(redis, config):
#         msg_pending  = await redis.xlen(config['requests']['stream'])
#         logging.info(f"There are {msg_pending} msg pending in {config['requests']['stream']} stream.")
    
#         if msg_pending:
#             message = await redis.xrange(config['requests']['stream'], '-', '+', count=1)
#             message_id = message[0][0].decode()
#             request_id = message[0][1][b'request_id']
#             get_latest_data = bool(message[0][1][b'get_latest_data'])
#         else:
#             message = await redis.xread_group(**config['requests']['group'])
#             message_id = message[0][1].decode()
#             request_id = message[0][2][b'request_id']
#             get_latest_data = bool(message[0][2][b'get_latest_data'])
        
#         return message, message_id, request_id, get_latest_data


# async def process_message(redis, config):
#     try:
#         while True:
#             message, message_id, timestamp, get_latest_data = await message_unpack(redis, config)
#             if message:
#                 # Extend the lease by reclaiming the message
#                 await redis.xclaim(config['requests']['stream'],
#                                    config['requests']['group']['group_name'],
#                                    config['requests']['group']['consumer_name'],
#                                    config['requests']['min_idle_time'], message_id)
#                 logging.info(f"Processing message: {message_id}")
#                 # if get_latest_data:
#                 # response = await ranking_data_fetcher.topcoins_ranking()
#                 response = ranking_data_fetcher.load_json_from_file()

#                 # else:
#                 #     response = await ranking_data_fetcher.topcoins_ranking(timestamp)
#                 # response = {"request_id": timestamp.decode(), "data": data_sample}
#                 redis.xadd(config['responses']['stream'], {"request_id": timestamp.decode(), "data": json.dumps(response)})
#                 res = await redis.xack(config['requests']['stream'],
#                                        config['requests']['group']['group_name'],
#                                        message_id)
#                 res = await redis.xdel(config['requests']['stream'], message_id)
#                 logging.info(f"Deleted {config['responses']['stream']} {message_id} : {res}")
#                 msg_pending  = await redis.xlen(config['requests']['stream'])
#             else:
#                 logging.info(f"No new messages. Waiting for the next one...")
#     finally:
#         redis.close()
#         await redis.wait_closed()


# async def main():
#     logging.info(f"Ranking service start")
    
#     redis = None

#     try:
#         config = await load_config_from_json('config.json')
#         redis = await aioredis.create_redis_pool((config['host'], config['port']))
#         retval = await create_redis_group(redis, config['requests']['stream'],config['requests']['group']['group_name'])
#         retval = await process_message(redis, config)
#     except FileNotFoundError:
#         logging.error(f"File config.json was not found.")
#     except ConnectionRefusedError as e:
#         logging.error(f"Redis Connection Refused.")
#     finally:
#         logging.info(f"Shutting down ranking service...")
#         # Close the Redis connection in the 'finally' block to ensure it's closed even if an exception occurs
#         if redis is not None:
#             redis.close()
#             await redis.wait_closed()

import redis
import schedule
import time
import json
from datetime import datetime

@tenacity.retry(
    stop=tenacity.stop_after_attempt(10),
    retry=tenacity.retry_if_exception_type(ConnectionRefusedError),
    wait=tenacity.wait_fixed(3),
)
async def connect_to_redis(host, port):
    try:
        redis = await aioredis.create_redis_pool((host, port))
        if await redis.execute("PING"):
            print("Connected to Redis successfully.")
            return redis
    except ConnectionRefusedError as e:
        print(f"ConnectionRefusedError: {e}")
        raise e
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise e

def get_rounded_timestamp():
    current_time = int(time.time())
    rounded_time = (current_time // 60) * 60  # Round down to the nearest minute
    return rounded_time

async def send_data_to_redis_stream(redis, stream, ttl_seconds):
    data_sample = '[{"Id": 1, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "BTC"}, {"Id": 1027, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "ETH"}, {"Id": 5426, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "SOL"}, {"Id": 74, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "DOGE"}, {"Id": 13631, "TimeStamp": "2024-01-22T03:13:29", "Symbol": "MANTA"}, {"Id": 52, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "XRP"}]'
    
    
    data = ranking_data_fetcher.load_json_from_file()    
    timestamp = get_rounded_timestamp()
    json_data = json.dumps(data_sample)
    
    redis.xadd(stream, {'data': json_data}, id=str(timestamp), t=ttl_seconds)
    print(f"Send data {json_data} to {stream} at {timestamp}")
    # Send data to the Redis stream
    # redis.xadd(config['responses']['stream'], {'data': data_json})
    # redis.xadd(config['responses']['stream'], {"request_id": timestamp.decode(), "data": json.dumps(response)})

async def main():
    try:
        config = await load_config_from_json('config.json')
        redis = await connect_to_redis(config['host'], config['port'])
        ttl_seconds = 3600

        schedule.every(10).seconds.do(lambda: asyncio.create_task(send_data_to_redis_stream(redis, 'ranking', ttl_seconds)))

        while True:
            schedule.run_pending()        
            await asyncio.sleep(1)
    
    except json.decoder.JSONDecodeError as e:
            print(f"Config load error : {e}")    
    except ConnectionRefusedError as e:
        print(f"Failed to connect to Redis: {e}")
    except tenacity.RetryError:
        print("Failed to connect to Redis after retries.")        
    except Exception as e:
        print(f"An unexpected error occurred during startup: {e}")    

if __name__ == "__main__":
    asyncio.run(main())

