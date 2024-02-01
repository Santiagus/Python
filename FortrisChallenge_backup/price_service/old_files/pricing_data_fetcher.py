
from datetime import datetime
from requests import Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import json
import os

def load_json_from_file(file_path = 'coinmarket_filtered_output.json'):     
    with open(file_path, 'r') as file:
        data = json.load(file)
    return data

async def get_api_info(timestamp=None):
    print("getting price quotes...")
    
    if timestamp is None:
        timestamp = datetime.now()
        
    # Coinmarket connection parameters
    APIKey = os.environ["COINMARKET_API_KEY"]
    NOT_AVAILABLE = "N/A"  # Default Value when data fetched is not available (Ej. LASTUPDATE)

    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'

    parameters = {
    'start':'1',
    'limit':'5000',
    'convert':'USD',
    "sort" : "volume_24h",
    "cryptocurrency_type" : "coins"
    }

    headers = {
    'Accepts': 'application/json',
    'Accept-Encoding': 'deflate, gzip',
    'X-CMC_PRO_API_KEY': APIKey
    }

    session = Session()
    session.headers.update(headers)

    filtered_items = []
    
    try:
        response = session.get(url, params=parameters)
        data = json.loads(response.text)
        # print("filtering pricing data...")
        if data.get("status").get("error_code"):      
            raise Exception(f'Error ({data.get("status").get("error_code")}) : {data.get("status").get("error_message")}')

        filtered_items = [
            {
            "Id": item.get("id", NOT_AVAILABLE),
            "TimeStamp": item.get("quote", {}).get("USD", {}).get("last_updated", NOT_AVAILABLE)[:-5],
            "Symbol": item.get("symbol", NOT_AVAILABLE),
            "Price USD": item.get("quote", {}).get("USD", {}).get("price", NOT_AVAILABLE),
            }
            for index, item in enumerate(data["data"])  
            ]        
    except (Exception,ConnectionError, Timeout, TooManyRedirects) as e:
        return e
    # print("Returning pricing data...")
    filtered_items = [item for item in filtered_items if item.get('Id') is not None]
    return filtered_items