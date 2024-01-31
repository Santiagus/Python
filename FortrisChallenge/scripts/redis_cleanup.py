import redis

def clean_all_keys(redis_client):
    # Get all keys
    all_keys = redis_client.keys('*')

    # Delete each key
    for key in all_keys:
        redis_client.delete(key)

    print("All messages cleaned.")

if __name__ == "__main__":
    redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

    # Clean all messages
    clean_all_keys(redis_client)