import sys
import redis

def remove_keys(redis_connection, keys):
    return redis_connection.delete(*keys)

def remove_keys_matching_pattern(redis_connection, pattern):
    keys_to_remove = redis_connection.keys(pattern)
    if keys_to_remove:
        return redis_connection.delete(*keys_to_remove)
    else:
        return 0

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <key1> <key2> ...")
        sys.exit(1)
    
    key_pattern = None
    
    redis_connection = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)
    
    # Check for the '-p' flag and get the pattern
    if '-p' in sys.argv:
        try:
            pattern_index = sys.argv.index('-p') + 1
            key_pattern = sys.argv[pattern_index]

            # Remove keys matching the specified pattern
            result = remove_keys_matching_pattern(redis_connection, key_pattern)
            if result:
                print(f"All keys matching the pattern '{key_pattern}' successfully removed from Redis.")
            else:
                print(f"No keys matching the pattern '{key_pattern}' found in Redis.") 
        except IndexError:
            print("Invalid usage. Please provide a pattern after the '-p' flag.")
            sys.exit(1)

    else:
        keys_to_remove = sys.argv[1:]
        result = remove_keys(redis_connection, keys_to_remove)
        if result:
            print(f"Keys {keys_to_remove} successfully removed from Redis.")
        else:
            print(f"One or more keys not found in Redis.")

if __name__ == "__main__":
    main()
