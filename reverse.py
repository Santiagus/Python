import json

data_sample = '[{"Id": 1, "TimeStamp": "2024-01-21T01:12:53", "Symbol": "BTC", "Price_USD": 41334.4409079465}, {"Id": 1027, "TimeStamp": "2024-01-21T03:12:53", "Symbol": "ETH", "Price_USD": 2435.95860533111}, {"Id": 5426, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "SOL", "Price_USD": 89.4960289302982}, {"Id": 74, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "DOGE", "Price_USD": 0.0832146431181928}, {"Id": 13631, "TimeStamp": "2024-01-22T03:13:29", "Symbol": "MANTA", "Price_USD": 2.72213652502557}, {"Id": 52, "TimeStamp": "2024-01-22T03:12:53", "Symbol": "XRP", "Price_USD": 0.542530458136185}]'


# Parse JSON string into a Python list
data_list = json.loads(data_sample)

# Modify the order of items (for example, reverse the order)
reordered_data_list = data_list[::-1]

print(reordered_data_list)
# Convert the reordered list back to a JSON string
# reordered_data_sample = json.dumps(reordered_data_list, indent=2)

# # Print the modified JSON string
# print(reordered_data_sample)