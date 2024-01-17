#!/bin/bash
docker run -d --name my-redis-container -p 6379:6379 --restart always redis