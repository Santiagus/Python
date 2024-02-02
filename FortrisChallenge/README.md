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

Open Api Specification in *oas.yaml*.

#### Interactive API Docs:

- [localhost:6667/docs](http://localhost:6667/docs)

- [localhost:6667/redoc](http://localhost:6667/redoc)

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
- Reference to merge the data from different sources should be a unique identifier, Symbol should be the obvious choice but in this case Symbols are not unique, Names either and the primary id is different between the sources. The choice has been CMC ID as ID so can be obtein processing the data from both sources, coinmarket match with this an the other (crytocompare) offers it as alternative ID. Even this way seems to be some ID duplicated but just in one side so merging got filterred info that is not present in all the sources.
- Every service loads a config file with parameter to indicate logging level and handler for sending the logs to the console and/or a log file a part from other params to make the system easier to adjust with no code updates involved.

**Scalability notes:**
rank and price services are based in generic data_fetcher + publisher (shared folder).

- *data_fetcher* : Class take care of data fetching. Loads needed info from a config json file with the configuration that indicate endpoint (url), the parameters/headers to apply when requesting data and filters to apply to the raw data to get the desired ouput.
The config files are placed in config folder so any program that needs to fetch data just have to instanciate the data_fetcher a load one of the config files that meets the needs.

- *publisher*: Class that takes care of connecting to Redis to publish the info provided by an injected data_fetcher.

This way the system can implement many services to fetch and publish the data to same or different streams. For example one service per coin per data range just adjusting the config files.


- *merger_service*: Listen to as many streams as indicated in the config so with an interval indicatd in the config file, so it can be easily configured to check 2..n data streams or replicated to merge diferent streams. \
***TODO:*** Put the columns used as reference to merge in the config file.

- Utils library functions are put in the COMMON folder.

    ***NOTE:*** Merger function is placed in utils and uses pandas. Considering scaling [dask](https://www.dask.org/) could be a good alternative for reimplementing the mergin functionality.

### DOCUMENTATION:
- **CODE** : Most functions has a docstring to describe the purpose and the parameters.
- **Docs** : HTML folder contains an HTML format documentation autogenerated with [pdoc3](https://pdoc3.github.io/pdoc/) from the code docstrings.

### TESTINGS
*run_test.sh* script is provided in the project rool folder to run the implemented test using *pytest*
**TODO:** Coverage, Black formatting, more test...

### ORCHESTRATION

*Dockerfile_<service_name>* files: includes the config to build the docker container for <service_name>
*docker_compose.yaml* : Run all the containers needed for project. `docker compose up` / `docker compose down`

For clarifications ask at santiagoabad@gmail.com

