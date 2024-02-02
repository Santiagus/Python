# Crypto  Challenge

Requirements to be fulfilled for the completion of the challenge are saved in `OriginalInstructions.md` file from the original pdf received.

### Requirements:

- Expose an http enpoint to display a list of crypto assests
- Endpoint parameters
    - **limit** : how many top cryptocurrency to be returned.
    - **datetime** : (optional): indicates  timestamp of the returned information. NOW by default
    - **format** : (optional): Output format. Values [JSON | CSV] (Default value Json)

**Sample call:** `$ curl http://localhost:6667?limit=200` \
**Sample CSV output:**

```bash
Rank, Symbol, Price USD,
1, BTC, 6634.41,
2, ETH, 370.237,
3, XRP, 0.471636,
... ... ...
200, DCN, 0.000269788,
```
### Tech stack:
- Python
- FastAPI
- Docker & docker-compose

### Data Sources
- **Price USD** : coinmarketcap API
- **Ranking** : cryptocompare API (24h Volume based)

Both should be up to date and keeped in an historical database for future request.

### Architecture

At least 3 independent services (service-oriented architecture):
- Pricing Service - keeps up-to-date pricing information.
- Ranking Service - keeps up-to-date ranking information.
- HTTP-API Service - exposes an HTTP endpoint that returns the required list of top cryptocurrency types prices.

### Others to consider
- Scalability, parallelization, resources, caching

## SOLUTION

For its capacity as message broker, cache, permanent data storage and scalability I have choosen [REDIS](https://redis.com/)

Mainly Redis features to be considered:

- Service communication via messages (Pub/Sub, Queues or Streams)
- Store data in-memory or persistant, so we can use it as cache and/or database
- Designed with scalability and distribution in mind
- supports master-slave replication, allowing you to create copies that can be used for scalability and high availability.
- Cloud platforms often support easy deployment of Redis with replication. For example, on AWS, you can use Amazon ElastiCache with Redis to deploy replication setups.
Partitioning:
 - Supports sharding or partitioning to distribute data across multiple Redis instances. Each instance holds a subset of the data, enabling horizontal scalability. (Redis Cluster)
 - Monitoring and automatic failover in case of master failure. (Redis Sentinel)
 - Well-supported on major cloud platforms such as AWS, Azure, Google Cloud, and others.
 - Some cloud platforms provide auto-scaling based on load.


## Services implemented

**httpAPI_service**

Exposes endpoint to the users. When a request is received it checks shared Redis cache/dabatase. Entries saved uses timestamp rounded to the minute as key. Smaller data refresh time from the external APIs is 60s

In case of datetime is specified, the service fetch data from all the external APIs concurrently, then merge it and save it to Redis for future request.

**price_service**

Fetch price data and publish it into a redis stream periodically (60s). when start it synchronize the API request to the rounded minute to facilitate data mergin based on fetch timestamp.

**rank_service**

Fetch rank data and publish it into a redis stream periodically (60s). when start it synchronize the API request to the rounded minute to facilitate data mergin based on fetch timestamp.

**merge_service**

Monitorize price and rank streams. When the timestamp difference between streams messages is inferior to a given margin (60s) it merge and store the data in Redis. So It assure the data is related to the same time and keep the historical database updated when running.

## Considerations

- Only one of the two external APIs offer historical data for free, thats the reason to only considerate and save lates data.
- Last updated timestamps related to the same coin (for last price and last rank info) vary substancially between the given sources. It means that last update of the 24h volume could be 2 days ago and price was updated 1 minute ago. In some test it was up to 56 days difference. Is possible to calculate last 24h volume featching historical data in the hour frame and aggregate it but not possible to do the same with the price because is not free to check, so populate the historical database this way was discarted.
- 24h Volume info in most cases (depends on the external API endpoint) refers to the previous day, no 24h before the data request.
- Reference for mergin the data from different sources should be a unique identifier, but in this case Symbols are not unique, Names are not unique, 
