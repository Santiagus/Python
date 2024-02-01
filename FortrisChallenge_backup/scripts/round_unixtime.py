import sys
from datetime import datetime, timedelta

def unix_to_iso(unix_timestamp):
    # Convert Unix timestamp to datetime object
    dt_object = datetime.utcfromtimestamp(unix_timestamp)
    # Format the datetime object as ISO format
    iso_format = dt_object.isoformat()
    return iso_format

def round_to_previous_hour(timestamp):
    # dt = datetime.utcfromtimestamp(timestamp)
    dt = datetime.fromtimestamp(timestamp)
    # return dt.timestamp()
    rounded_dt = dt.replace(minute=0, second=0, microsecond=0)
    
    rounded_timestamp = int(rounded_dt.timestamp())
    return rounded_timestamp

def round_to_nearest_hour(timestamp):
    # dt = datetime.utcfromtimestamp(timestamp)
    dt = datetime.fromtimestamp(timestamp)

    rounded_dt = dt + timedelta(minutes=30)
    rounded_dt = rounded_dt.replace(minute=0, second=0, microsecond=0)
    
    rounded_timestamp = int(rounded_dt.timestamp())
    return rounded_timestamp

if __name__ == "__main__":
    # Check if a Unix timestamp is provided as a command-line argument
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <unix_timestamp>")
        sys.exit(1)

    # Get the Unix timestamp from the command-line argument
    try:
        timestamp = int(sys.argv[1])
    except ValueError:
        print("Error: Invalid Unix timestamp provided.")
        sys.exit(1)

    # Round the timestamp and print the result
    rounded_timestamp = round_to_previous_hour(timestamp)
    
    print(f"Original Timestamp: {timestamp} - {unix_to_iso(timestamp)}")
    print(f"Rounded Timestamp: {rounded_timestamp} - {unix_to_iso(rounded_timestamp)}")
