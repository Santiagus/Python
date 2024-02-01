import aioredis

async def acknowledge_message(redis, stream_name, consumer_group, message_id):
    try:
        # Acknowledge the message
        await redis.xack(stream_name, consumer_group, message_id)
        print(f"Message with ID {message_id} acknowledged successfully.")
    except aioredis.ReplyError as e:
        print(f"Failed to acknowledge message with ID {message_id}. Error: {e}")

async def main():
    redis = await aioredis.create_redis_pool("redis://localhost")
    stream_name = 'toprank_requests'  # Update with your actual stream name
    consumer_group = 'ranking_consumers'  # Update with your actual consumer group name
    message_id_to_acknowledge = b'1705874860983-0'  # Update with the desired message ID

    # Call the function to acknowledge the message
    await acknowledge_message(redis, stream_name, consumer_group, message_id_to_acknowledge)

    # Close the Redis connection
    redis.close()
    await redis.wait_closed()

# Run the event loop
import asyncio
asyncio.run(main())
