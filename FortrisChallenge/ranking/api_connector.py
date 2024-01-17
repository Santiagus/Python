from collections import OrderedDict
from datetime import datetime
from datetime import timedelta
from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import json
import os

def get_api_info(timestamp=None):
  print("get_api_info - getting ranking quotes...")
  
  # Cryptocompare connection parameters
  APIKey = os.environ["CRYPTOCOMPARE_API_KEY"]
  limit = 5000                    # API constraint. Max total results
  RESULTS_PER_REQUEST = 100       # API constraint. Max results per request
  NOT_AVAILABLE = "N/A"           # Default Value when data fetched is not available (Ej. LASTUPDATE)
  pages = limit // RESULTS_PER_REQUEST

  url = 'https://data-api.cryptocompare.com/asset/v1/top/list'

  parameters = {
      "page" : 1,
      "page_size" : RESULTS_PER_REQUEST,
      "asset_type":"BLOCKCHAIN",
      "sort_by": "SPOT_MOVING_24_HOUR_QUOTE_VOLUME_USD",
      "sort_direction": "DESC",
      'api_key': APIKey
  }

  headers = {
      'Accepts': 'application/json',
  }

  session = Session()
  session.headers.update(headers)

  filtered_items = []
  try:
    for _ in range(pages):
        response = session.get(url, params=parameters)
        data = json.loads(response.text,object_pairs_hook=OrderedDict)
        if data.get("Err"):
            print(f'Error : {data.get("Err").get("message")}')
            break
        
        filtered_items.extend({
            "Id": next(
                (int(alt_id.get("ID")) for alt_id in item.get("ASSET_ALTERNATIVE_IDS", []) if alt_id and alt_id.get("NAME") == "CMC"),
                None  # Set to None if no "CMC"
            ) if item.get("ASSET_ALTERNATIVE_IDS") is not None else None ,
            "TimeStamp" : datetime.utcfromtimestamp(item.get("PRICE_USD_LAST_UPDATE_TS")).isoformat(),
            "Symbol": item.get("SYMBOL", NOT_AVAILABLE),
            "Price_USD": item.get("PRICE_USD", NOT_AVAILABLE),
            }
            for index, item in enumerate(data.get("Data").get("LIST",[]))
        )
        parameters["page"] += 1
  except (ConnectionError, Timeout, TooManyRedirects) as e:
      return(e)
  return filtered_items


# Async version
import httpx

async def fetch_data_from_api_async(url, parameters, headers):
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=parameters, headers=headers)
        response.raise_for_status()  # Raise an exception for non-2xx status codes
        return response.text


def strdata_to_ordered_json(rawdata):
    try:
        data = json.loads(rawdata,object_pairs_hook=OrderedDict)
        if data.get("Err"):
            return json.dumps(f'Error : {data.get("Err").get("message")}')
        return data
    except Exception as e:
        return json.dumps(f'Error : data load failed.')


def filter_data(data):    
    print("Filtering data...")
    NOT_AVAILABLE = "N/A"           # Default Value when data fetched is not available (Ej. LASTUPDATE)
    # data = strdata_to_ordered_json(rawdata)
    try:
        filtered_data = ({
            "Id": next(
                (int(alt_id.get("ID")) for alt_id in item.get("ASSET_ALTERNATIVE_IDS", []) if alt_id and alt_id.get("NAME") == "CMC"),
                None  # Set to None if no "CMC"
            ) if item.get("ASSET_ALTERNATIVE_IDS") is not None else None ,
            "TimeStamp" : datetime.utcfromtimestamp(item.get("PRICE_USD_LAST_UPDATE_TS")).isoformat(),
            "Symbol": item.get("SYMBOL", NOT_AVAILABLE),
            "Price_USD": item.get("PRICE_USD", NOT_AVAILABLE),
            }
            for item in data.get("Data").get("LIST",[])
        )
        print("Filtered ranking data served!!")
        return filtered_data
    except Exception as e:
        return {"Error filtering data"}


# Example usage
async def topcoins_ranking():
    print("getting ranking quotes...")

    # Cryptocompare connection parameters
    APIKey = os.environ["CRYPTOCOMPARE_API_KEY"]
    limit = 5000                    # API constraint. Max total results
    RESULTS_PER_REQUEST = 100       # API constraint. Max results per request
    pages = limit // RESULTS_PER_REQUEST

    url = 'https://data-api.cryptocompare.com/asset/v1/top/list'

    parameters = {
        "page" : 1,
        "page_size" : RESULTS_PER_REQUEST,
        "asset_type":"BLOCKCHAIN",
        "sort_by": "SPOT_MOVING_24_HOUR_QUOTE_VOLUME_USD",
        "sort_direction": "DESC",
        'api_key': APIKey
    }

    headers = {
        'Accepts': 'application/json',
    }

    filtered_items = []

    try:
        total_assets = limit
        data = await fetch_data_from_api_async(url, parameters, headers)
        json_data = strdata_to_ordered_json(data)
        total_assets = json_data.get("Data", limit).get("STATS", limit).get("TOTAL_ASSETS", limit)
        fdata = filter_data(json_data)
        filtered_items.extend(fdata)
        while len(filtered_items) < total_assets:
            parameters["page"] += 1
            data = await fetch_data_from_api_async(url, parameters, headers)
            json_data = strdata_to_ordered_json(data)
            fdata = filter_data(json_data)
            filtered_items.extend(fdata)
        return json.dumps(filtered_items)

        # print("Data:", data)
    except httpx.HTTPError as e:
        print(f"HTTP error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    
# # Run the event loop
# import asyncio
# asyncio.run(main())