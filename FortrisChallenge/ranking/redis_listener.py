# import api_connector
# import asyncio
# import aioredis
import json

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

import asyncio
import aioredis
import api_connector

async def monitor_queue(redis_host, redis_port, queue_name):
    redis = await aioredis.create_redis_pool(f'redis://{redis_host}:{redis_port}')

    while True:
        # BLPOP is a blocking command that waits for an item in the list
        # The timeout is specified in seconds (0 means indefinitely)
        result = await redis.blpop(queue_name, timeout=0)

        if result:
            # Process the item received from the queue
            print(f"Received item from {queue_name}: {result[1]}")
            response = await api_connector.topcoins_ranking()
            # Your processing logic goes here
            redis.lpush("toplist", response)


if __name__ == "__main__":
    # Replace these values with your Redis server details and queue name
    redis_host = 'localhost'
    redis_port = 6379
    queue_name = 'ranking_request_queue'

    asyncio.run(monitor_queue(redis_host, redis_port, queue_name))
