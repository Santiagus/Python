
from requests import Request, Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
from datetime import datetime, timezone
import json
import os

APIKey = os.environ["COINMARKET_API_KEY"]

NOT_AVAILABLE = "N/A"  # Default Value when data fetched is not available (Ej. LASTUPDATE)
# Rate limit	30 Requests per minute
# Update frequency	**Every 1 minute

url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'

update_frequency_seconds = 60

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

try:
  response = session.get(url, params=parameters)
  data = json.loads(response.text)
  if data.get("status").get("error_code"):      
      raise Exception(f'Error ({data.get("status").get("error_code")}) : {data.get("status").get("error_message")}')

  min_datetime = datetime.max.replace(tzinfo=timezone.utc)
  max_datetime = datetime.min.replace(tzinfo=timezone.utc)

  filtered_items = [
      {
      "Id": item.get("id", NOT_AVAILABLE),
      "TimeStamp": item.get("quote", {}).get("USD", {}).get("last_updated", NOT_AVAILABLE),
      "Symbol": item.get("symbol", NOT_AVAILABLE),
      "Price": item.get("quote", {}).get("USD", {}).get("price", NOT_AVAILABLE),
      }
      for index, item in enumerate(data["data"])
      if (timestamp := item.get("last_updated", NOT_AVAILABLE)) is not None
      and (
          (min_datetime := min(min_datetime, datetime.fromisoformat(timestamp))) or True
      )  # Update min_timestamp
      and (
          (max_datetime := max(max_datetime, datetime.fromisoformat(timestamp))) or True
      )  # Update max_timestamp
    ]
  # print(json.dumps(data))
  # Print or use the min and max values as needed
  print("Minimum TimeStamp:", max_datetime)
  print("Maximum TimeStamp:", min_datetime)
  # Calculate the time difference
  time_difference = max_datetime - min_datetime
  # Format the time difference in HH:MM:SS
  formatted_diff = str(time_difference)
  print("Time Difference:", formatted_diff)
  print("Entries        :", len(filtered_items))
  #--------------------------
  # Specify the file path where you want to save the JSON data
  file_path = "coinmarket_output.json"

  # Write JSON data to the file
  with open(file_path, 'w') as json_file:
    json.dump(data, json_file, indent=4) 
  #--------------------------
  file_path = "coinmarket_filtered_output.json"

  # Write JSON data to the file
  with open(file_path, 'w') as json_file:
    json.dump(filtered_items, json_file,indent=0)
  
  # print(data)
except (Exception,ConnectionError, Timeout, TooManyRedirects) as e:
  print(e)