from collections import OrderedDict
from datetime import datetime
from datetime import timedelta
from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import json
import os


symbols_file_path = "symbols.json" # JSON file that keeps symbols returned by toplist
top_list_url = 'https://data-api.cryptocompare.com/asset/v1/top/list'
historical_data_url = 'https://min-api.cryptocompare.com/data/exchange/histohour?tsym=BTC&limit=24&aggregate=1'


def get_api_info(timestamp=None):
  print("get_api_info - getting ranking quotes...")
  
  # Cryptocompare connection parameters
  APIKey = os.environ["CRYPTOCOMPARE_API_KEY"]
  limit = 5000                    # API constraint. Max total results
  RESULTS_PER_REQUEST = 100       # API constraint. Max results per request
  NOT_AVAILABLE = "N/A"           # Default Value when data fetched is not available (Ej. LASTUPDATE)
  pages = limit // RESULTS_PER_REQUEST


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
        response = session.get(top_list_url, params=parameters)
        data = json.loads(response.text,object_pairs_hook=OrderedDict)
        if data.get("Err"):
            print(f'Error : {data.get("Err").get("message")}')
            break

        filtered_items = [
            {
                "Id": alt_id["ID"],
                "TimeStamp": datetime.utcfromtimestamp(item.get("PRICE_USD_LAST_UPDATE_TS")).isoformat(),
                "Symbol": item.get("SYMBOL", NOT_AVAILABLE),
                "Price_USD": item.get("PRICE_USD", NOT_AVAILABLE),
            }
            for index, item in enumerate(data.get("Data").get("LIST", []))
            if (alt_id := next(
                (int(alt_id.get("ID")) for alt_id in item.get("ASSET_ALTERNATIVE_IDS", []) if alt_id and alt_id.get("NAME") == "CMC"),
                None  # Set to None if no "CMC"
            )) is not None
        ]

        filtered_items.extend(filtered_items)
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
async def topcoins_ranking(timestamp = None):
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
        # Filter items where 'Id' is not None
        # filtered_items = [item for item in filtered_items if item.get('Id') is not None]

        save_to_json_file(filtered_items)        

        if not os.path.exists(symbols_file_path):
            save_symbols_to_file(filtered_items)
        return json.dumps(filtered_items)

        # print("Data:", data)
    except httpx.HTTPError as e:
        print(f"HTTP error: {e}")
    except Exception as e:
        print(f"Error: {e}")

def save_to_json_file(data, file_path = 'cryptocompare_filtered_output.json'):

    with open(file_path, "w") as json_file:
        json.dump(data, json_file, indent= 2)
    print(f"JSON data has been saved to {file_path}")
    

def save_symbols_to_file(items, file_path = 'output.json'):
    # Extract 'Symbol' values and create a set
    symbol_set = {item['Symbol'] for item in items}
    
    # Save the set to a file
    file_path = 'symbols.txt'
    with open(file_path, 'w') as file:
        json.dump(list(symbol_set), file)
    print(f'Symbols saved to {file_path}')

def load_symbols_from_file(file_path):     
    with open(file_path, 'r') as file:
        symbol_list = json.load(file)
    return set(symbol_list)


# # Run the event loop
# asyncio.run(main())
        
# https://min-api.cryptocompare.com/data/exchange/histohour?tsym=BTC&limit=24&aggregate=1

import asyncio

# def main():

if __name__ == "__main__":
    # main()
    asyncio.run(topcoins_ranking(timestamp=None))