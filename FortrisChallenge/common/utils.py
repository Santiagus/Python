from datetime import datetime, timedelta, timezone
import json
import logging.config
import pandas as pd


def unix_timestamp_to_iso(unix_timestamp):
    """
    Convert a Unix timestamp to ISO format.

    Parameters:
        - `unix_timestamp`: The Unix timestamp to convert.

    Returns:
        - str: The timestamp in ISO format.

    Example:
        ```python
        iso_timestamp = unix_timestamp_to_iso(1643644800)
        print(iso_timestamp)
        ```
    """
    dt_object = datetime.fromtimestamp(unix_timestamp)
    iso_format = dt_object.isoformat()
    return iso_format

def seconds_until_next_minute():
    """
    Calculate the number of seconds until the next minute.

    Returns:
        - float: The number of seconds until the next minute.

    Example:
        ```python
        seconds_remaining = seconds_until_next_minute()
        print(f"Seconds until next minute: {seconds_remaining}")
        ```
    """
    now = datetime.now()
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    seconds_until_next_minute = (next_minute - now).total_seconds()
    return seconds_until_next_minute

def rounddown_time_to_minute():
    """
    Round down the current time to the nearest minute.

    Returns:
        - int: Rounded down timestamp to the nearest minute.

    Example:
        ```python
        rounded_timestamp = rounddown_time_to_minute()
        print(f"Rounded down timestamp: {rounded_timestamp}")
        ```
    """
    current_time = int(datetime.now(timezone.utc).timestamp())
    rounded_time = (current_time // 60) * 60  # Round down to the nearest minute
    return rounded_time

def round_to_previous_minute(timestamp, unix_format = False):
    """
    Round a timestamp to the previous minute.

    Parameters:
        - `timestamp`: The timestamp to round.
        - `unix_format` (bool): If True, `timestamp` is assumed to be in Unix format.

    Returns:
        - int: Rounded timestamp.

    Example:
        ```python
        rounded_timestamp = round_to_previous_minute(1643644800, unix_format=True)
        print(f"Rounded timestamp: {rounded_timestamp}")
        ```
    """

    if unix_format:
        timestamp = datetime.fromtimestamp(timestamp)
    rounded_dt = timestamp.replace(second=0, microsecond=0)
    rounded_timestamp = int(rounded_dt.timestamp())
    return rounded_timestamp

def load_config_from_json(file_path):
    """
    Load configuration data from a JSON file.

    Parameters:
        - `file_path` (str): The path to the JSON file.

    Returns:
        - dict: Configuration data loaded from the JSON file.

    Example:
        ```python
        config_data = load_config_from_json("config.json")
        print(config_data)
        ```
    """
    with open(file_path, 'r') as file:
        config_data = json.load(file)
    return config_data

def json_to_csv(json_data):
    """
    Convert JSON data to CSV format.

    Parameters:
        - `json_data`: A list of dictionaries containing JSON data.

    Returns:
        - str: CSV-formatted string.

    Example:
        ```python
        csv_content = json_to_csv([{"Id": 1, "Name": "John"}, {"Id": 2, "Name": "Jane"}])
        print(csv_content)
        ```
    """
    import io
    import csv

    header = json_data[0].keys() if json_data else []
    csv_buffer = io.StringIO()  # Pass newline='' to force '\n'
    csv_writer = csv.DictWriter(csv_buffer, fieldnames=header, lineterminator="\n")
    csv_writer.writeheader()
    csv_writer.writerows(json_data)
    csv_content = csv_buffer.getvalue()
    csv_buffer.close()

    return csv_content

def print_df(df):
    """
    Print the first 20 rows of a DataFrame with enhanced display settings.

    Parameters:
        - `df`: The DataFrame to print.

    Example:
        ```python
        df = pd.DataFrame({"Name": ["John", "Jane"], "Age": [30, 25]})
        print_df(df)
        ```
    """
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)  # Set a large width to avoid line breaks
    print(df.head(20))


def merge_data(*data_list):
    """
    Merge data from multiple sources into a single DataFrame.

    Parameters:
        - `*data_list`: Variable number of DataFrames to be merged.

    Returns:
        - str: JSON-formatted string representing the merged DataFrame.

    Example:
        ```python
        merged_json = merge_data(df1, df2, df3)
        print(merged_json)
        ```
    """
    if not data_list:
        logging.info(f"No data to merge")
        return {}

    logging.info(f"Merging data from {len(data_list)} sources")
    
    # Convert each element in data_list to a DataFrame
    data_frames = [pd.DataFrame(data) for data in data_list]

    all_float_columns = []
    for df in data_frames:
        df['Id'] = df['Id'].astype('Int64') # Assure Id in all tables is int64 (NaN is float by default)
        float_columns = df.select_dtypes(include='float64').columns
        if float_columns.size > 0:
            all_float_columns.append(*float_columns)
        df[float_columns] = df[float_columns].astype(str) # Convert float to str to avoid to round values

    # Merge DataFrames
    merged_df = pd.merge(data_frames[0], data_frames[1], on=['Id', 'Symbol'], suffixes=('_df1', '_df2'))
    for i in range(2, len(data_frames)):
        merged_df = pd.merge(merged_df, data_frames[i], on=['Id', 'Symbol'], suffixes=(f'_df{i-1}', f'_df{i}')).astype(object)

    merged_df = merged_df.drop('Id', axis=1)

    # Add Rank
    merged_df.index = pd.RangeIndex(start=1, stop=len(merged_df) + 1, name='Rank')
    merged_df.reset_index(inplace=True)
    result_json = merged_df.to_json(orient='records')

    # Get floats converted to str back
    data_list = json.loads(result_json)
    for entry in data_list:
        for target_key in all_float_columns:
            if target_key in entry:
                entry[target_key] = float(entry[target_key])

    # Convert the list of dictionaries back to a JSON string
    updated_json_data = json.dumps(data_list)

    return updated_json_data


def unpack_message(message):
    """
    Unpack a message containing a timestamp and data.

    Parameters:
        - `message`: A message in the expected format.

    Returns:
        - tuple: A tuple containing timestamp (int) and data (str).

    Example:
        ```python
        message = [('<timestamp>', {b'data': '<data>'})]
        timestamp, data = unpack_message(message)
        print(f"Timestamp: {timestamp}, Data: {data}")
        ```
    """
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
