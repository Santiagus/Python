# Crypto  Challenge

Requirements to be fulfilled for the completion of the challenge are saved in the `OriginalInstructions.md` file from the original pdf received.

### Requirements:

- Expose an HTTP endpoint to display a list of crypto assets
- Endpoint parameters
    - **limit** : how many top cryptocurrencies to be returned.
    - **datetime** : (optional): indicates the timestamp of the returned information. NOW by default
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

Both should be up to date and kept in a historical database for future requests.

### Architecture

At least 3 independent services (service-oriented architecture):
- Pricing Service - keeps up-to-date pricing information.
- Ranking Service - keeps up-to-date ranking information.
- HTTP-API Service - exposes an HTTP endpoint that returns the required list of top cryptocurrency types prices.

### Others to consider
- Scalability, parallelization, resources, caching

## SOLUTION

For its capacity as a message broker, cache, permanent data storage and scalability I have chosen [REDIS](https://redis.com/)

Mainly Redis features to be considered:

- Service communication via messages (Pub/Sub, Queues or Streams)
- Store data in-memory or persistent, so we can use it as a cache and/or database
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

Exposes endpoint to the users. When a request is received it checks the shared Redis cache/database. Entries saved use a timestamp rounded to the minute as the key. Smaller data refresh time from the external APIs is 60s

In case DateTime is specified, the service fetches data from all the external APIs concurrently, then merges it and saves it to Redis for future requests.

Open API Specification in *oas.yaml*.

#### Interactive API Docs:

- [localhost:6667/docs](http://localhost:6667/docs)

- [localhost:6667/redoc](http://localhost:6667/redoc)

**price_service**

Fetch price data and publish it into a Redis stream periodically (60s). when started it synchronizes the API request to the rounded minute to facilitate data merging based on the fetch timestamp.

**rank_service**

Fetch rank data and publish it into a Redis stream periodically (60s). when started it synchronizes the API request to the rounded minute to facilitate data merging based on the fetch timestamp.

**merge_service**

Monitor price and rank streams. When the timestamp difference between stream messages is inferior to a given margin (60s) it merges and stores the data in Redis. So It ensures the data is related to the same time and keeps the historical database updated when running.

## Considerations

- Only one of the two external APIs offers historical data for free, that's the reason to only consider and save the latest data.
 -The last updated timestamps related to the same coin (for last price and last rank info) vary substantially between the given sources. It means that the last update of the 24-hour volume could be 2 days ago and the price was updated 1 minute ago. In some tests, it was up to 56 days difference. Is possible to calculate the last 24-hour volume fetching historical data in the hour frame and aggregate it but not possible to do the same with the price because is not free to check, so populating the historical database this way was discarded.
- 24-hour Volume info in most cases (depending on the external API endpoint) refers to the previous day, not 24 hours before the data request.
- Reference to merge the data from different sources should be a unique identifier, Symbol should be the obvious choice but in this case, Symbols are not unique, Names either and the primary ID is different between the sources. The choice has been CMC ID as ID so can be obtained by processing the data from both sources, coinmarket matches with this and the other (crytocompare) offers it as an alternative ID. Even this way seems to be some ID duplicated but just on one side so merging got filtered info that is not present in all the sources.
- Every service loads a config file with a parameter to indicate the logging level and handler for sending the logs to the console and/or a log file apart from other parameters to make the system easier to adjust with no code updates involved.

**Scalability notes:**
rank and price services are based on generic data_fetcher + publisher (shared folder).

- *data_fetcher* : Class take care of data fetching. Loads needed info from a config JSON file with the configuration that indicates the endpoint (URL), the parameters/headers to apply when requesting data and filters to apply to the raw data to get the desired output.
The config files are placed in the config folder so any program that needs to fetch data just has to instantiate the data_fetcher a load one of the config files that meets the needs.

- *publisher*: Class that takes care of connecting to Redis to publish the info provided by an injected data_fetcher.

This way the system can implement many services to fetch and publish the data to the same or different streams. For example, one service per coin per data range just adjusting the config files.


- *merger_service*: Listen to as many streams as indicated in the config with an interval indicated in the config file, so it can be easily configured to check 2..n data streams or replicated to merge different streams. \
***TODO:*** Put the columns used as references to merge in the config file.

- Utils library functions are put in the COMMON folder.

    ***NOTE:*** Merger function is placed in utils and uses pandas. Considering scaling [dask](https://www.dask.org/) could be a good alternative for reimplementing the merging functionality.

### DOCUMENTATION:
- **CODE** : Most functions have a docstring to describe the purpose and the parameters.
- **Docs** : HTML folder contains an HTML format documentation autogenerated with [pdoc3](https://pdoc3.github.io/pdoc/) from the code docstrings.

### TESTINGS
*run_test.sh* script is provided in the project root folder to run the implemented test using *pytest*
**TODO:** Coverage, Black formatting, more tests...

### ORCHESTRATION

*requirements.txt*: file with the package dependencies needs to run each service. One per service folder.
*Dockerfile_<service_name>* files: includes the config to build the docker container for <service_name>
*docker_compose.yaml* : Run all the containers needed for the project. `docker compose up` / `docker compose down`

For clarifications ask at santiagoabad@gmail.com

