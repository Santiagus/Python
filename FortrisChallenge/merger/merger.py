import pandas as pd
from datetime import datetime
import json


# Order is relevant, cryptocomape key order will be used as rank
file_path_first = 'cryptocompare_filtered_output.json'
with open(file_path_first) as input_file:
    json_array = json.load(input_file)
    df_first = pd.DataFrame(json_array)

file_path_second = 'coinmarket_filtered_output.json'
with open(file_path_first) as input_file:
    json_array = json.load(input_file)
    df_second = pd.DataFrame(json_array)

# Convert the Timestamp strings to datetime objects
df_first['TimeStamp'] = pd.to_datetime(df_first['TimeStamp'])
df_second['TimeStamp'] = pd.to_datetime(df_second['TimeStamp'].str.replace("Z", ""))

# Merge DataFrames
merged_df = pd.merge(df_first, df_second,on=["Id"], suffixes=('_First', '_Second'),)
merged_df.index = pd.RangeIndex(start=1, stop=len(merged_df)+1, name='Rank')

# Calculate the time difference in seconds
merged_df['TimeDifference_Seconds'] = (merged_df['TimeStamp_First'] - merged_df['TimeStamp_Second']).dt.total_seconds()

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)  # Set a large width to avoid line breaks

# Print the merged DataFrame
print(merged_df)

# Get the first 200 entries
first_200_entries = merged_df.head(200)

# Calculate the average and median of 'TimeDifference_Seconds'
average_time_difference = first_200_entries['TimeDifference_Seconds'].mean()
median_time_difference = first_200_entries['TimeDifference_Seconds'].median()

# Print the results
print(f'Average Time Difference: {average_time_difference} seconds')
print(f'Median Time Difference: {median_time_difference} seconds')

