from datetime import datetime, timedelta, timezone
import json
import logging.config

def setup_logging(log_config):
    """
    Setup logging configuration based on the provided log_config.
    """
    logging.config.dictConfig(log_config)

def unix_timestamp_to_iso(unix_timestamp):
    dt_object = datetime.fromtimestamp(unix_timestamp)
    iso_format = dt_object.isoformat()
    return iso_format

def seconds_until_next_minute():
    now = datetime.now()
    next_minute = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    seconds_until_next_minute = (next_minute - now).total_seconds()
    return seconds_until_next_minute


def rounddown_time_to_minute():
    current_time = int(datetime.now(timezone.utc).timestamp())
    rounded_time = (current_time // 60) * 60  # Round down to the nearest minute
    return rounded_time

def load_config_from_json(file_path):
    with open(file_path, 'r') as file:
        config_data = json.load(file)
    return config_data