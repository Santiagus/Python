import redis

def check_consumer_groups(redis, stream_name):
    # Use XINFO GROUPS to get information about consumer groups for a stream
    info_groups = redis.xinfo_groups(stream_name)
    print(f"Consumer Groups for Stream '{stream_name}': {info_groups}")

def get_all_keys_info(redis_client):
    # Get all keys
    all_keys = redis_client.keys('*')

    # Extract key names from the keys
    key_names = [key.decode() for key in all_keys]

    return key_names

def list_messages_in_key(redis_client, key_name, count=10):
    # Determine the type of the key
    key_type = redis_client.type(key_name).decode()

    # Fetch and list messages based on the key type
    if key_type == 'list':
        result = redis_client.lrange(key_name, 0, count - 1)
        print(f"Messages in List '{key_name}':")
        for message in result:
            print(f"  Message: {message.decode()}")
    elif key_type == 'stream':
        print(check_consumer_groups(redis_client,key_name))
        result = redis_client.xrange(key_name, '-', '+', count=count)
        print(f"Messages in Stream '{key_name}':")
        for entry in result:
            print(f"  Entry: {entry}")
    else:
        print(f"Unsupported key type for '{key_name}'")

if __name__ == "__main__":
    # redis_client = await aioredis.create_redis_pool(('localhost', 6379))
    redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

    # Get information about all keys
    all_keys = get_all_keys_info(redis_client)

    # List messages in each key
    for key_name in all_keys:
        list_messages_in_key(redis_client, key_name)
        print("\n")
