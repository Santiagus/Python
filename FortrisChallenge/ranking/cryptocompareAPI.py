from collections import OrderedDict
from datetime import datetime 
from datetime import timedelta
from requests import Request, Session
from requests.exceptions import ConnectionError, Timeout, TooManyRedirects
import json
import os

# The values are based on GMT time, historical daily data closes at 00 GMT.
# Spain time GMT+1

APIKey = os.environ["CRYPTOCOMPARE_API_KEY"]

limit = 5000                    # Challenge constraint
RESULTS_PER_REQUEST = 100       # API constraint
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


min_datetime = datetime.now().timestamp()
max_datetime = datetime(1970, 1, 1, 0, 0, 0, tzinfo=datetime.utcfromtimestamp(0).tzinfo).timestamp()
# total_items = []
filtered_items = []
try:
  file_path = "cryptocompare_output.json"
  with open(file_path, 'w') as json_file:
    pass

  file_path_filtered = "cryptocompare_filtered_output.json"
  with open(file_path_filtered, 'w') as json_file:
    pass
  
  for page in range(pages):
    response = session.get(url, params=parameters)

    data = json.loads(response.text,object_pairs_hook=OrderedDict)
    
    if data.get("Err"):
      print(f'Error : {data.get("Err").get("message")}')
      break
    
    # min_datetime = datetime.max.replace(tzinfo=timezone.utc)
    # max_datetime = datetime.min.replace(tzinfo=timezone.utc)
    filtered_items.extend(
      {
      # "Volume" :  "{:>20.5f}".format(item.get("RAW", {}).get("USD", {}).get("TOTALVOLUME24HTO", 0)),
      # "TimeStamp" : item.get("RAW", {}).get("USD", {}).get("LASTUPDATE", NOT_AVAILABLE),
      # "Symbol": item.get("CoinInfo").get("Name", NOT_AVAILABLE),
      # "Id": item.get("CoinInfo").get("Id", NOT_AVAILABLE),
      # "Rank": index + page*RESULTS_PER_REQUEST + 1,
        
      # "Volume" :  "{:>20.5f}".format(item.get("SPOT_MOVING_24_HOUR_QUOTE_VOLUME_USD", 0)),      
      # "TimeStamp" : datetime.utcfromtimestamp(max_datetime).isoformat())
      
      "Id": next(
        (int(alt_id.get("ID")) for alt_id in item.get("ASSET_ALTERNATIVE_IDS", []) if alt_id and alt_id.get("NAME") == "CMC"),
        None  # Set to None if no "CMC"
      ) if item.get("ASSET_ALTERNATIVE_IDS") is not None else None ,
      "TimeStamp" : datetime.utcfromtimestamp(item.get("PRICE_USD_LAST_UPDATE_TS")).isoformat(),
      "Symbol": item.get("SYMBOL", NOT_AVAILABLE),
      # "Name": item.get("NAME", NOT_AVAILABLE),
      # "Id": item.get("ID", NOT_AVAILABLE),
      "Rank": index + page*RESULTS_PER_REQUEST + 1,
      "Price_USD": item.get("PRICE_USD", NOT_AVAILABLE),        
      }
      for index, item in enumerate(data.get("Data").get("LIST",[]))
          if (timestamp := item.get("PRICE_USD_LAST_UPDATE_TS", datetime.min)) is not None
      and (
          (min_datetime := min(min_datetime, timestamp)) or True
      )  # Update min_timestamp
      and (
          (max_datetime := max(max_datetime, timestamp)) or True
      )  # Update max_timestamp
    )
    # print(json.dumps(data))
    #--------------------------
    # Specify the file path where you want to save the JSON data
    file_path = "cryptocompare_output.json"

    # Write JSON data to the file
    with open(file_path, 'a') as json_file:
      json.dump(data, json_file, indent=4) 
    
    # file_path = "cryptocompare_filtered_output.json"
    # with open(file_path_filtered, 'a') as json_file:
    #   json.dump(filtered_items, json_file, indent=0)
    #--------------------------
    # ranking information for the top assets. Toplist by 24H Volume Full Data.
    # for _ in filtered_items:
    #   print(_)
        
    # print(f"Page {parameters['page']} - Items : {len(filtered_items)}")
    # total_items.extend(filtered_items)
    # total_items += len(filtered_items)
    parameters["page"] += 1

except (ConnectionError, Timeout, TooManyRedirects) as e:
  print(e)

file_path_filtered = "cryptocompare_filtered_output.json"
with open(file_path_filtered, 'a') as json_file:
  json.dump(filtered_items, json_file, indent=0)

# Print or use the min and max values as needed
print("Minimum TimeStamp:", datetime.utcfromtimestamp(max_datetime).isoformat())
print("Maximum TimeStamp:", datetime.utcfromtimestamp(min_datetime).isoformat())
# Calculate the time difference
time_difference = max_datetime - min_datetime
# Format the time difference in HH:MM:SS


time_difference_seconds = max_datetime - min_datetime

# Convert the time difference to a timedelta object
time_difference_timedelta = timedelta(seconds=time_difference_seconds)

print("Time Difference (days, hours, minutes, seconds):", time_difference_timedelta)
print("Entries        :", len(filtered_items))

