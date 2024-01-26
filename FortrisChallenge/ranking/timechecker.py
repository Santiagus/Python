import json
from datetime import datetime

# Load the JSON file
file_path = 'cryptocompare_filtered_output.json'  # replace with the actual file path
with open(file_path, 'r') as file:
    data = json.load(file)

# Extract timestamps from the data
timestamps = [item['TimeStamp'] for item in data]

# Convert timestamps to datetime objects
datetime_objects = [datetime.fromisoformat(timestamp) for timestamp in timestamps]

# Find min and max timestamps
min_timestamp = min(datetime_objects)
max_timestamp = max(datetime_objects)

# Calculate time difference
time_difference = max_timestamp - min_timestamp

# Print results
print(f"Min Timestamp: {min_timestamp}")
print(f"Max Timestamp: {max_timestamp}")
print(f"Time Difference: {time_difference.days} days, {time_difference.seconds // 3600} hours, {(time_difference.seconds % 3600) // 60} minutes, {time_difference.seconds % 60} seconds")
