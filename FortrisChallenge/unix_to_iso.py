import sys
import datetime

def unix_to_iso(unix_timestamp):
    # Convert Unix timestamp to datetime object
    dt_object = datetime.datetime.utcfromtimestamp(unix_timestamp)
    
    # Format the datetime object as ISO format
    iso_format = dt_object.isoformat()
    
    return iso_format

if __name__ == "__main__":
    # Check if a Unix timestamp is provided as a command-line argument
    if len(sys.argv) != 2:
        print("Usage: python script_name.py <unix_timestamp>")
        sys.exit(1)

    # Get the Unix timestamp from the command-line argument
    try:
        unix_timestamp = int(sys.argv[1])
    except ValueError:
        print("Error: Invalid Unix timestamp provided.")
        sys.exit(1)

    # Convert and print the result
    iso_result = unix_to_iso(unix_timestamp)
    print(f"Unix Timestamp: {unix_timestamp}")
    print(f"ISO Format: {iso_result}")
