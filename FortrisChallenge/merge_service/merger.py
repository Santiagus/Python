import pandas as pd
import time
import aioredis
import asyncio
import logging
import json
from tenacity import RetryError
from common.redis_utils import connect_to_redis
from common.utils import round_to_previous_minute, unix_timestamp_to_iso, load_config_from_json, setup_logging
# asyncio.set_event_loop(asyncio.new_event_loop())  # Set the event loop

def print_df(df):
    # pd.set_option('display.max_rows', 10)  # Adjust the number as needed
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)  # Set a large width to avoid line breaks
    print(df.head(20))

async def merge_results(*data_list):
    # Convert each element in data_list to a DataFrame
    data_frames = [pd.DataFrame(json.loads(data)) for data in data_list]
    # for df in data_frames:
    #     print_df(df)

    # Merge DataFrames
    merged_df = pd.merge(data_frames[0], data_frames[1], on=['Id', 'Symbol'], suffixes=('_df1', '_df2'))
    for i in range(2, len(data_frames)):
        merged_df = pd.merge(merged_df, data_frames[i], on=['Id', 'Symbol'], suffixes=(f'_df{i-1}', f'_df{i}'))
    merged_df.index = pd.RangeIndex(start=1, stop=len(merged_df) + 1, name='Rank')
    merged_df = merged_df.drop('Id', axis=1)
    # print_df(merged_df)
    # merged_df.reset_index(inplace=True)
    # print_df(merged_df)

    # Specify the file path for the CSV file
    # csv_file_path = 'merged.csv'
    # Save the DataFrame to a CSV file
    # merged_df.to_csv(csv_file_path, index=False)

    # Drop timestamp columns from the merged DataFrame
    timestamp_columns_to_drop = [f'TimeStamp_df{i}' for i in range(1, len(data_frames) + 1)]
    merged_df = merged_df.drop(timestamp_columns_to_drop, axis=1)

    # Return the merged DataFrame as JSON
    return merged_df.to_json(orient='records', indent=True)


def unpack_message(message):
    timestamp = 0
    data = []
    try:
        logging.debug(f'unpacking message...')
        timestamp = int(message[0][0].decode()[:-2])
        data = message[0][1][b'data'].decode()
    except IndexError as e:
        logging.debug(f'Empty or innaccesible message.')
    except Exception as e:
        logging.error(f'Error unpacking message, check message format')
    finally:
        return timestamp, data

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
        setup_logging(config.get("logging", {}))

        logging.info(f"Service start. Loading configuration...")
        redis: aioredis.Redis | None = await connect_to_redis(config["redis"])
        tasks = []

        while True:
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
                data_list.append(data)
                logging.debug(f"[{task_name:<8}]: {unix_timestamp_to_iso(timestamp)}: {data[:80]}")
                is_data_missing |= result == []

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
                if main_stream_id != 0:
                    # Assure mainstream is in list first position, so it will set the results entries order
                    data_list.insert(0, data_list.pop(main_stream_id))
                merged_data = await merge_results(*data_list)

                # Save to redis
                logging.info(f"Saving to Redis: {generated_redis_key} : {json.loads(merged_data)[:1]}")
                success = await redis.set(generated_redis_key, merged_data)
                if success:
                    logging.info(f"Data stored successfully with key {generated_redis_key} data time {unix_timestamp_to_iso(generated_redis_key)}")
                    time.sleep(config["redis"]["interval"])
                else:
                    logging.error(f"{generated_redis_key} Key already exists or there was an issue storing the data")
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