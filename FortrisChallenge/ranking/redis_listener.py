import asyncio
import aioredis
import api_connector
import json
import logging

data_sample = '[{"Id": 1, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "BTC", "Price_USD": 41334.4409079465}, {"Id": 1027, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "ETH", "Price_USD": 2435.95860533111}, {"Id": 5426, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "SOL", "Price_USD": 89.4960289302982}, {"Id": 74, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "DOGE", "Price_USD": 0.0832146431181928}, {"Id": 13631, "TimeStamp": "2024-01-22T03:13:29", "Symbol": "MANTA", "Price_USD": 2.72213652502557}, {"Id": 52, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "XRP", "Price_USD": 0.542530458136185}]'

async def load_config_from_json(file_path):
    with open(file_path, 'r') as file:
        config_data = json.load(file)
    return config_data


async def create_redis_group(redis, config):
    try:
        res = await redis.xgroup_create(**config, mkstream=True)
        if res:
            logging.info(f"Created redis group '{config['request']['group']['group_name']}' in stream '{config['request']['stream']}'")
    except Exception as e:
        logging.warning(f"Redis group '{config['requests']['group']['group_name']}' in stream '{config['requests']['stream']}' already exists.")


async def process_message(redis, config):
    try:
        msg_pending  = await redis.xlen(config['requests']['stream'])
        print(f"There are {msg_pending} msg pending.")
        while True:
            if msg_pending:
                message = await redis.xrange(config['requests']['stream'], '-', '+', count=1)
                message_id = message[0][0].decode()
                message_data = message[0][1][b'request_id']
            else:
                message = await redis.xread_group(**config['requests']['group'])
                message_id = message[0][1].decode()
                message_data = message[0][2][b'request_id']
            if message:
                # Extend the lease by reclaiming the message
                await redis.xclaim(config['requests']['stream'],
                                   config['requests']['group']['group_name'],
                                   config['requests']['group']['consumer_name'],
                                   config['requests']['min_idle_time'], message_id)
                logging.info(f"Processing message: {message_id}")
                # response = await api_connector.topcoins_ranking()
                response = data_sample
                redis.xadd(config['responses']['stream'], {"request_id": response})
                res = await redis.xack(config['requests']['stream'],
                                       config['requests']['group']['group_name'],
                                       message_id)
                res = await redis.xdel(config['requests']['stream'], message_id)
                logging.info(f"Deleted {config['responses']['stream']} {message_id} : {res}")
                msg_pending  = await redis.xlen(config['requests']['stream'])
            else:
                logging.info(f"No new messages. Waiting for the next one...")
    finally:
        redis.close()
        await redis.wait_closed()


async def main():
    config = await load_config_from_json('config.json')
    redis = await aioredis.create_redis_pool((config['host'], config['port']))

    try:
        await create_redis_group(redis, config)
        await process_message(redis, config)

    finally:
        logging.info(f"Shutting down ranking service...")
        # Close the Redis connection in the 'finally' block to ensure it's closed even if an exception occurs
        redis.close()
        await redis.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())