import json
import io
import csv
import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
from ..utils import (
    unix_timestamp_to_iso,
    seconds_until_next_minute,
    rounddown_time_to_minute,
    round_to_previous_minute,
    load_config_from_json,
    json_to_csv,
    print_df,
    merge_data,
    unpack_message,
)


def test_unix_timestamp_to_iso():
    # Test unix_timestamp_to_iso function
    unix_timestamp = 1643644800
    iso_timestamp = unix_timestamp_to_iso(unix_timestamp)
    expected_iso_timestamp = "2022-01-31T17:00:00"
    assert iso_timestamp == expected_iso_timestamp


def test_seconds_until_next_minute():
    # Test seconds_until_next_minute function
    seconds_remaining = seconds_until_next_minute()
    assert seconds_remaining >= 0 and seconds_remaining < 60


def test_rounddown_time_to_minute():
    # Test rounddown_time_to_minute function
    rounded_timestamp = rounddown_time_to_minute()
    current_time = int(datetime.now(timezone.utc).timestamp())
    expected_rounded_time = (current_time // 60) * 60
    assert rounded_timestamp == expected_rounded_time


def test_round_to_previous_minute():
    # Test round_to_previous_minute function
    timestamp = 1643644800
    rounded_timestamp = round_to_previous_minute(timestamp, unix_format=True)
    expected_rounded_timestamp = 1643644800
    assert rounded_timestamp == expected_rounded_timestamp


def test_load_config_from_json(tmp_path):
    # Test load_config_from_json function
    config_data = {"key": "value"}
    json_file_path = tmp_path / "test_config.json"
    with open(json_file_path, "w") as json_file:
        json.dump(config_data, json_file)

    loaded_config = load_config_from_json(json_file_path)
    assert loaded_config == config_data


def test_json_to_csv():
    # Test json_to_csv function
    json_data = [{"Id": 1, "Name": "John"}, {"Id": 2, "Name": "Jane"}]
    csv_content = json_to_csv(json_data)
    expected_csv_content = "Id,Name\n1,John\n2,Jane\n"
    assert csv_content == expected_csv_content


def test_print_df(capsys):
    # Test print_df function
    df = pd.DataFrame({"Name": ["John", "Jane"], "Age": [30, 25]})
    print_df(df)
    captured = capsys.readouterr()
    expected_output = "   Name  Age\n0  John   30\n1  Jane   25\n"
    assert captured.out == expected_output


def test_merge_data():
    # Test merge_data function
    rank_data = [{"Id": 1,"Symbol": "BTC"},
                  {"Id": 1027,"Symbol": "ETH"},
                  {"Id": 5426,"Symbol": "SOL"}]
    price_data = [{"Id": 5426,"Symbol": "SOL","Price": 91.67929509303363},
                   {"Id": 1,"Symbol": "BTC","Price": 42863.717593629444},
                   {"Id": 1027,"Symbol": "ETH","Price": 2540.618971408493}]
    
    merged_json = merge_data(rank_data, price_data)
    print("Result : ", merged_json)
    expected_merged_json = '[{"Rank": 1, "Symbol": "BTC", "Price": 42863.717593629444}, {"Rank": 2, "Symbol": "ETH", "Price": 2540.618971408493}, {"Rank": 3, "Symbol": "SOL", "Price": 91.67929509303363}]'
    assert merged_json == expected_merged_json


def test_unpack_message():
    # Test unpack_message function
    message = [(b'1643644800-0', {b'data': b'Test data'})]
    timestamp, data = unpack_message(message)
    expected_timestamp = 1643644800
    expected_data = "Test data"
    assert timestamp == expected_timestamp
    assert data == expected_data


# You can add more test cases based on your specific use cases.
