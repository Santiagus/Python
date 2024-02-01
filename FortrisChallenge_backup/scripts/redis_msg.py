import redis

redis_client = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)


queues = ['ranking_request_queue',
          'princing_request_queue',
          'toplist'
          ]

for q in queues:
    # Get the number of elements in a list (queue)    
    queue_size = redis_client.llen(q)
    print(f"{q} size: {queue_size}")

    # Get all elements in a list (queue)
    queue_elements = redis_client.lrange(q, 0, -1)
    print(f"{q} elements:", queue_elements)
