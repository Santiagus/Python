import asyncio
import aioredis
import json

async def read_stream(redis, stream_name, consumer_group, consumer_name):
    # Join the consumer group
    await redis.xreadgroup(consumer_group, consumer_name, {stream_name: '>'}, count=0)

    # Continuously read messages
    while True:
        streams, messages = await redis.xreadgroup(consumer_group, consumer_name, {stream_name: '>'}, count=1)

        if messages:
            for message in messages[0][1]:
                data = json.loads(message[1].decode())
                yield data

async def merge_streams(redis, stream_price, stream_rank, consumer_group_price, consumer_name_price, consumer_group_rank, consumer_name_rank):
    async for data_price in read_stream(redis, stream_price, consumer_group_price, consumer_name_price):
        timestamp_id = data_price['timestamp_id']

        async for data_rank in read_stream(redis, stream_rank, consumer_group_rank, consumer_name_rank):
            if data_rank['timestamp_id'] == timestamp_id:
                # Match found, merge data
                merged_data = {'timestamp_id': timestamp_id, 'price': data_price['price'], 'rank': data_rank['rank']}
                print(f"Merged Data: {merged_data}")
                break

async def main():
    redis = await aioredis.create_redis('redis://localhost')

    try:
        stream_price = 'stream_price'
        stream_rank = 'stream_rank'
        consumer_group_price = 'consumer_group_price'
        consumer_name_price = 'consumer_name_price'
        consumer_group_rank = 'consumer_group_rank'
        consumer_name_rank = 'consumer_name_rank'

        # Create consumer groups (if not already created)
        await redis.xgroup_create(stream_price, consumer_group_price, id='0', mkstream=True)
        await redis.xgroup_create(stream_rank, consumer_group_rank, id='0', mkstream=True)

        # Start monitoring and merging streams asynchronously
        tasks = [
            merge_streams(redis, stream_price, stream_rank, consumer_group_price, consumer_name_price, consumer_group_rank, consumer_name_rank),
        ]

        await asyncio.gather(*tasks)

    finally:
        redis.close()
        await redis.wait_closed()

if __name__ == "__main__":
    asyncio.run(main())
