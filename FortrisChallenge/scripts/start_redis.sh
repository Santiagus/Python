#!/bin/bash
docker run --name my-redis-container -d -p 6379:6379 --restart always \
  -v redis.conf:/etc/redis/redis.conf \
  redis redis-server /etc/redis/redis.conf
