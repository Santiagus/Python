import time
import asyncio
import logging
import logging.config
import json
from tenacity import RetryError
from common.redis_utils import connect_to_redis
from common.utils import round_to_previous_minute, unix_timestamp_to_iso, load_config_from_json, merge_data, unpack_message


async def read_last_message(redis, stream):
    try:
        result = await redis.xrevrange(stream, count=1, start='+', stop='-')
        return result
    except Exception as e:
        logging.error(f'Error reading the most recent message from stream {stream}: {e}')
        return None


async def run_task_with_name(name, task_coroutine):
    task = asyncio.create_task(task_coroutine)
    await task
    return task.result(), name

async def main():
    redis = None
    try:
        # Configuration
        config = load_config_from_json('merge_service/config.json')

        # Set up logging based on the configuration
        logging.config.dictConfig(config["logging"])

        logging.info(f"Service start. Loading configuration...")
        redis = await connect_to_redis(config["redis"])
        tasks = []

        while True:
            if redis is None:
                redis = await connect_to_redis(config["redis"])

            # Create task per stream to read messages asynchronously
            tasks = [run_task_with_name(stream, read_last_message(redis, stream)) for stream in config["redis"]["source_streams"]]
            results = await asyncio.gather(*tasks)
            
            # Process the results
            is_data_missing = False
            timestamps = []
            data_list = []
            main_stream_id = 0
            for result, task_name in results:
                timestamp, data = unpack_message(result)
                if task_name == config["redis"]["main_stream"]:
                    main_stream_id = len(timestamps)
                timestamps.append(timestamp)
                if data != []:
                    data_list.append(json.loads(data)) # type: ignore
                logging.debug(f"[{task_name:<8}]: {unix_timestamp_to_iso(timestamp)}: {data[:80]}")
                is_data_missing |= result == None

            # In some stream is empty timeout and continue loop
            if is_data_missing:
                time.sleep(config["redis"]["interval"])
                continue

            # Check time difference among data sources
            timediff = max(timestamps) - min(timestamps)
            if timediff > config["redis"]["interval"]:
                logging.info(f"Time difference among stream sources is too big : {timediff}s")
            else : # Data sources synchronized
                # Generate redis key
                generated_redis_key = round_to_previous_minute(max(timestamps), unix_format=True)

                # Merge data
                if main_stream_id != 0 and data_list:
                    # Assure mainstream is in list first position, so it will set the results entries order
                    data_list.insert(0, data_list.pop(main_stream_id))

                if data_list:
                    merged_data = merge_data(*data_list)
                    # Save to redis
                    logging.info(f"Saving to Redis: {generated_redis_key} : {json.loads(merged_data)[:1]}")
                
                    success = False
                    if redis is not None:
                        success = await redis.set(generated_redis_key, merged_data)
                    if success:
                        logging.info(f"Data stored successfully with key {generated_redis_key} data time {unix_timestamp_to_iso(generated_redis_key)}")                        
                    else:
                        logging.error(f"{generated_redis_key} Key already exists or there was an issue storing the data")
            time.sleep(config["redis"]["interval"])

    except RetryError as e:
        logging.error(f"Retry operation failed: {e}")
    except ConnectionRefusedError as e:
        logging.error(f"Failed to connect to Redis: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        logging.exception("Stack trace:")
    finally:
        logging.info("Exiting program.")
        if redis is not None:
            redis.close()
            await redis.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())