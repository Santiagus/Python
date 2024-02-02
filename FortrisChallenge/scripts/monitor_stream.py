import asyncio
import aioredis

async def monitor_redis_stream(stream_name, consumer_name):
    redis = await aioredis.create_redis('redis://localhost:6379')

    try:
        while True:
            # Use XREAD to get new messages from the stream
            response = await redis.xread(streams=['ranking'], count=1)
            # response = await redis.execute('XREAD', 'BLOCK', 0, 'STREAMS', stream_name, '>', 'COUNT', 1)
            message_id = response[0][1].decode()
            data = response[0][2][b'data'].decode()
            print(f"{message_id}: {data[:80]}")

    except asyncio.CancelledError:
        pass
    finally:
        redis.close()
        await redis.wait_closed()

async def main():
    stream_name = 'ranking'
    consumer_name = 'stream_monitor'

    # Run the monitor function in the background
    monitor_task = asyncio.create_task(monitor_redis_stream(stream_name, consumer_name))

    try:
        # Your other main tasks can go here

        # Keep the main function running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        # Cancel the monitor task on keyboard interrupt
        monitor_task.cancel()
        await monitor_task

if __name__ == "__main__":
    asyncio.run(main())
