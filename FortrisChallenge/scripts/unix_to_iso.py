import sys
import datetime

def unix_to_iso(unix_timestamp):
    # Convert Unix timestamp to datetime object
    dt_object = datetime.datetime.utcfromtimestamp(unix_timestamp)
    
    # Format the datetime object as ISO format
    iso_format = dt_object.isoformat()
    
    return iso_format

def calculate_time_difference(timestamp1, timestamp2):
    # Calculate the time difference between two Unix timestamps
    difference = abs(timestamp1 - timestamp2)
    time_difference = datetime.timedelta(seconds=difference)
    
    # Format the time difference
    time_difference_str = str(time_difference)

    # Append 'zzz' to indicate milliseconds (even though Unix timestamps don't include milliseconds)
    time_difference_str += "zzz"
    
    return time_difference_str

if __name__ == "__main__":
    # Check if one or two Unix timestamps are provided as command-line arguments
    if len(sys.argv) not in [2, 3]:
        print("Usage: python script_name.py <unix_timestamp1> [<unix_timestamp2>]")
        sys.exit(1)

    # Get the Unix timestamps from the command-line arguments
    try:
        unix_timestamp1 = int(sys.argv[1])
        unix_timestamp2 = int(sys.argv[2]) if len(sys.argv) == 3 else None
    except ValueError:
        print("Error: Invalid Unix timestamp provided.")
        sys.exit(1)

    # Convert and print the ISO format for the given timestamp(s)
    iso_result1 = unix_to_iso(unix_timestamp1)
    print(f"Unix Timestamp 1: {unix_timestamp1}")
    print(f"ISO Format 1: {iso_result1}")

    if unix_timestamp2 is not None:
        iso_result2 = unix_to_iso(unix_timestamp2)
        print()
        print(f"Unix Timestamp 2: {unix_timestamp2}")
        print(f"ISO Format 2: {iso_result2}")

        # Calculate and print the time difference
        time_difference = calculate_time_difference(unix_timestamp1, unix_timestamp2)
        print(f"\nTime Difference: {time_difference}")
