import redis
import json

def get_all_keys(redis_connection):
    keys = []
    cursor = '0'

    while cursor != 0:
        cursor, partial_keys = redis_connection.scan(cursor=cursor, count=1000)
        keys.extend(partial_keys)

    return keys

def get_all_keys_and_values(redis_connection):
    keys = get_all_keys(redis_connection)
    values = redis_connection.mget(keys)
    
    # Check if values are None and replace with a placeholder
    values = [value if value is not None else "Value not found" for value in values]
    
    return dict(zip(keys, values))

def main():
    # Replace 'localhost' and 6379 with your Redis server details
    redis_connection = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)

    all_keys_and_values = get_all_keys_and_values(redis_connection)

    print("All Keys and Values:")
    for key, value in all_keys_and_values.items():
        if value == 'Value not found':
            print(f"{key}: {value}...")
        else:
            print(f"{key}: {json.loads(value)[:1]}...")

if __name__ == "__main__":
    main()