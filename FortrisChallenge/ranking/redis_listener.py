# import api_connector
# import asyncio
# import aioredis
# import json

# def read_config(config_file_path="redis_config.json"):
#     with open(config_file_path, "r") as file:
#         config = json.load(file)
#     return config

# async def reader(channel):
#     while await channel.wait_message():
#         msg = await channel.get()
#         print("Got Message:", msg)

# async def handle_message(channel, message):
#     # This function will be called when a new message is received
#     # Handle the message as needed
#     print(f"Received message on channel {channel}: {message}")

# async def monitor_redis_queue():
#     # Load redis configuration
#     config = read_config()
#     redis_host = config["redis"]["host"]
#     redis_port = config["redis"]["port"]
#     request_queue = config["request_queue"]
#     result_queue = config["result_queue"]

#     # Initialization
#     redis = await aioredis.create_redis_pool(f'redis://{redis_host}:{redis_port}')
#     # channels = await redis.subscribe('ranking_request_queue')
#     channel = (await redis.subscribe('ranking_request_queue'))[0]

#     async def reader(channel):
#         async for ch, message in channel.iter():
#             print("Got message in channel:", ch, ":", message)
#     asyncio.get_running_loop().create_task(reader(channel))

#     # for channel in channels:
#     # reader_task = asyncio.ensure_future(reader(channel))
#     # while await channel.wait_message():
#     #     msg = await channel.get()
#     #     if msg:
#     #         response = await api_connector.topcoins_ranking()
#     #         await redis.publish('toplist', response)

#             # await redis.unsubscribe('first_topic')
#     # reader_task.cancel()
#     redis.close()
#     await redis.wait_closed()

# # loop = asyncio.get_event_loop()
# # loop.run_until_complete(main())
#     # try:
#     #     # Wait for incoming messages in an event-driven manner
#     #     async for msg in channel.iter(encoding='utf-8'):
#     #         limit = msg.get("limit")
#     #         timestamp = msg.get("timestamp")
#     #         response = await api_connector.topcoins_ranking()
#     #         await handle_message(channel.name.decode(), msg)
#     #         await redis.publish('toplist', 'Received' + msg)
#     #         # await redis.unsubscribe('first_topic')
#     # except Exception as e:
#     #     print("Error : ",  e)
#     #     return e
#     #     reader_task.cancel()


# # if __name__ == "__main__":
# #     # Run the event-driven Redis queue monitor
# #     asyncio.run(monitor_redis_queue())
# loop = asyncio.get_event_loop()
# loop.run_until_complete(monitor_redis_queue())


# # def monitor_redis_queue(redis_host, redis_port, queue_name):
# #     # Connect to Redis
# #     redis_client = redis.StrictRedis(host=redis_host, port=redis_port, decode_responses=True)

# #     # Create a pubsub instance
# #     pubsub = redis_client.pubsub()

# #     # Subscribe to the channel (queue)
# #     pubsub.subscribe(queue_name)

# #     # Function to handle incoming messages
# #     def handle_message(message):
# #         if message['type'] == 'message':
# #             print(f"Item received from queue {queue_name}: {message['data']}")

# #     # Start a separate thread to listen for messages
# #     thread = threading.Thread(target=lambda: pubsub.listen(callback=handle_message), daemon=True)
# #     thread.start()

# #     # Block the main thread to keep the listener running
# #     thread.join()


# # # Load redis configuration
# # config = read_config()

# # redis_host = config["redis"]["host"]
# # redis_port = config["redis"]["port"]
# # request_queue = config["request_queue"]
# # result_queue = config["result_queue"]

# # monitor_redis_queue(redis_host, redis_port, request_queue)

# ------------------------------------------------------------
# import asyncio
# import aioredis
# import api_connector

# async def monitor_queue(redis_host, redis_port, queue_name):
#     redis = await aioredis.create_redis_pool(f'redis://{redis_host}:{redis_port}')

#     while True:
#         # BLPOP is a blocking command that waits for an item in the list
#         # The timeout is specified in seconds (0 means indefinitely)
#         result = await redis.blpop(queue_name, timeout=0)

#         if result:
#             # Process the item received from the queue
#             print(f"Received item from {queue_name}: {result[1]}")
#             response = await api_connector.topcoins_ranking()
#             # Your processing logic goes here
#             redis.lpush("toplist", response)


# if __name__ == "__main__":
#     # Replace these values with your Redis server details and queue name
#     redis_host = 'localhost'
#     redis_port = 6379
#     queue_name = 'ranking_request_queue'

#     asyncio.run(monitor_queue(redis_host, redis_port, queue_name))
# import asyncio
# import json
# from asyncio import TimeoutError  # Import TimeoutError explicitly
# import api_connector
# import aioredis

import asyncio
import aioredis
import api_connector
import json

def load_config_from_json(file_path):
    with open(file_path, 'r') as file:
        config_data = json.load(file)
    return config_data


async def check_consumer_groups(redis, stream_name):
    # Use XINFO GROUPS to get information about consumer groups for a stream
    try:
        info_groups = await redis.xinfo_groups(stream_name)
        print(f"Consumer Groups for Stream '{stream_name}': {info_groups}")
    except Exception as e:
        print(f"Erron when featching groups info : {stream_name}")

data_sample = '[{"Id": 1, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "BTC", "Price_USD": 41334.4409079465}, {"Id": 1027, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "ETH", "Price_USD": 2435.95860533111}, {"Id": 5426, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "SOL", "Price_USD": 89.4960289302982}, {"Id": 74, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "DOGE", "Price_USD": 0.0832146431181928}, {"Id": 13631, "TimeStamp": "2024-01-22T03:13:29", "Symbol": "MANTA", "Price_USD": 2.72213652502557}, {"Id": 52, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "XRP", "Price_USD": 0.542530458136185}]'

async def process_rank_request():
    # redis = await aioredis.create_redis_pool("redis://localhost")
    redis = await aioredis.create_redis_pool(('localhost', 6379))
    ping = await redis.execute('PING')
    print(f"Redis Ping : {ping}")

    config = load_config_from_json('../config.json')
    stream_name = config["redis"]["stream_names"]["rank_requests"]
    response_stream = "topcoinsrank"

    consumer_name="rank_consumer"
    # stream_name = "toprank_requests"
    consumer_group = config["redis"]["consumer_groups"]["rank_requests"]
    lease_duration_ms = 10000
    # consumer_name = 'myconsumer'
    count = 1
    #  def xread_group(self, group_name, consumer_name, streams, timeout=0,
    #                 count=None, latest_ids=None, no_ack=False):
    # response = redis.xread_group(consumer_group, consumer_name, streams={stream_name: '>'},count=count)
    # response = redis.xread_group(group_name=consumer_group, consumer_name=consumer_name, streams=[stream_name], count=count)
    
    # streams = [(stream_name_bytes, b'>')]

    # TODO: Create grous (xgroup_create) priour to use
    stream = "rank_req"
    latest_ids=[">"]
    try:

        await check_consumer_groups(redis, stream)
        res = await redis.xgroup_create(stream, str(stream + "_consumers"), mkstream=True) #, id='0', mkstream=True)
        await check_consumer_groups(redis, stream)
        if res:
            print(f"Created redis group '{str(stream + '_consumers')}' in stream '{stream}'")
    except Exception as e:
        print(f"Redis group '{str(stream + '_consumers')}' in stream '{stream}' already exists.")

    res = redis.xread_group(group_name=consumer_group, consumer_name=consumer_name, streams=[stream], count=count,
                                  latest_ids=latest_ids)

    # res = await redis.xread_group(
    # "rank_req_consumers", # consumer group name
    # "rank_consumer", # consumer name
    # streams=[(stream_name, '>')], # stream name and ID
    # count=1, # maximum number of elements per stream
    # # block=0, # do not block if there are no new messages
    # # noack=True # do not require acknowledgments
# )
    # response =   redis.xread_group(group=consumer_group, consumer_name=consumer_name, streams={stream_name: '>'}, count=count)

    # print(response)
    try:
        while True:
            # # XREAD BLOCK 0 means a non-blocking read
            # message = await redis.xread(["toprank_requests"], count=1)
            # XRANGE with '+' (plus) and '-' (minus) specifies the entire range of the stream
            message = await redis.xrange(stream_name, '-', '+', count=1)
            if message:
                message_id = message[0][0].decode()
                message_data = message[0][1][b'request_id']
                # message_id, message_data = message[0]
                # request_id = message_data[b'request_id'].decode()
                # Extend the lease by reclaiming the message
                # await redis.xclaim(stream_name, consumer_group, "rank_consumer", lease_duration_ms, id)
                await redis.xclaim(stream_name, consumer_group, consumer_name, lease_duration_ms, message_id)                
                # Simulate processing time
                print(f"Processing message: {message_id}")
                # await asyncio.sleep(5)  # Simulate processing time                
                # response = await api_connector.topcoins_ranking()
                response = data_sample                
                
                redis.xadd(response_stream, {"request_id": response})

                # Acknowledge the message
                # await redis.xack(stream_name, consumer_group, id)
                result = await redis.xack(stream_name, consumer_group, message_id)
                print(f"XACK {stream_name} {consumer_group} {message_id} : {result}")
                res = await redis.xdel(stream_name, message_id)
                print(f"Deleted {stream_name} {message_id} : {res}")

                # stream = config["redis"]["stream_names"]["topcoinsrank"]
                # redis.xadd(stream, {"request_id": response})
            # else:
            #     print(f"No new messages. Waiting for the next one...")
            # Simulate fetching rank data from an external API (api_connector module)
            # rank_data = await api_connector.topcoins_ranking()

            # Publish the rank data to the "rank_data" stream
            # await redis.xadd(
            #     "rank_data", {"request_id": data, "data": json.dumps(rank_data)}
            # )

    finally:
        redis.close()
        await redis.wait_closed()
if __name__ == "__main__":
    asyncio.run(process_rank_request())
