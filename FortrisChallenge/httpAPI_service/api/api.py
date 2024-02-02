import json
import logging
import asyncio
from datetime import datetime
from fastapi import Query
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse
from common.utils import round_to_previous_minute, json_to_csv, merge_data, rounddown_time_to_minute
from common.redis_utils import save_to_redis
from httpAPI_service.app import app

@app.get("/")
async def getTopCryptoList(
    limit: int = Query(..., title="The number of items to retrieve", ge=1),
    datetime: datetime = Query(None, title="The timestamp of the request", description="Optional timestamp parameter"),
    format: str = Query("JSON", title="The format of the response", description="Optional response format parameter (JSON or CSV)")
):
    """
    Get the top cryptocurrencies based on specified parameters.

    Parameters:
        - `limit` (int): The number of items to retrieve. Must be greater than or equal to 1.
        - `timestamp` (int, optional): The timestamp of the request. Optional parameter.
        - `format` (str, optional): The format of the response. Optional parameter.
          Possible values: "JSON" (default) or "CSV".

    Returns:
        - Response: A list of top cryptocurrencies based on the specified parameters.

    Example:
        Calling this endpoint without specifying parameters:
        ```
        /?limit=10&timestamp=1643644800&format=JSON
        ```
    """
    ranking_data = None

    try:
        # Check redis connectivity
        if app.state.redis is None:
            logging.error(f"No redis connection available")
            raise HTTPException(status_code=500, detail="Internal Server Error")

        # Check parameters are correct
        if not (isinstance(limit, int) and limit > 0):
            raise HTTPException(status_code=422, detail="Limit must be an integer greater than 0")
        

        # Use timestamp as id/key for messages and db/cache
        if datetime:
            # Check in database/cache
            request_id = round_to_previous_minute(int(datetime.timestamp()), unix_format=True)
            ranking_data = await app.state.redis.get(request_id)
        else:
            # Round current time to the minute and check for cached value
            redis_key = rounddown_time_to_minute()
            ranking_data = await app.state.redis.get(redis_key)

            if ranking_data is None: # Not in cache
                logging.info(f"Feching data from external apis")

                price_result_task  = asyncio.create_task(app.state.price_fetcher.get_data())
                rank_result_task  = asyncio.create_task(app.state.rank_fetcher.get_data())

                price_result, rank_result = await asyncio.gather(price_result_task, rank_result_task)

                ranking_data = merge_data(rank_result, price_result)
                await save_to_redis(app.state.redis, redis_key, ranking_data)
            else:
                logging.info(f"Returning cached data for {redis_key}")

        if ranking_data is None: # Not in cache or "latest" resquest
            logging.error(f"No data for the specified datetime : {datetime} ")
            raise HTTPException(status_code=404, detail="Data not found for the specified timestamp")

        # Output formating
        ranking_data = json.loads(ranking_data)
        ranking_data = ranking_data[:limit]
        if format.upper() == 'CSV':
            csv = json_to_csv(ranking_data)
            return PlainTextResponse(content=csv, media_type="application/csv")

        return ranking_data

    except json.JSONDecodeError as e:
        logging.error(f"Unexpected UTF-8 BOM (decode using utf-8-sig) - Value: {ranking_data}")
    except TypeError as e:
        logging.error(f'The JSON object must be str, bytes or bytearray')