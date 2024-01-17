import redis

# Connect to Redis
redis_host = 'localhost'  # Replace with your Redis server's host
redis_port = 6379          # Replace with your Redis server's port
redis_client = redis.StrictRedis(host=redis_host, port=redis_port, decode_responses=True)

# Specify the key to be deleted
redis_key = 'ranking_data'

# Delete the key
print(f"Deleting {redis_key} entries")
result = redis_client.delete(redis_key)
print(f"Deleted {result} entries")
