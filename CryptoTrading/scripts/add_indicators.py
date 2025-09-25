import pandas as pd
import pandas_ta as ta
import os

# Define the input and output directories
input_dir = "data/raw"
output_dir = "data/processed"

# OFFSETS
MACD_LENGTH = 26
ADX_LENGTH = 14
BBANDS_LENGTH = 20


# Loop through all files in the input directory
for file in os.listdir(input_dir):
    # Check if the file is a CSV file
    if file.endswith(".csv"):
        # Load the CSV file
        df = pd.read_csv(
            os.path.join(input_dir, file),
            usecols=["low", "high", "open", "close", "volume"],
        )

        # Calculate the technical indicators
        # MACD
        macd_values = ta.macd(df["close"], fast=12, slow=26, signal=9)
        df.loc[MACD_LENGTH:, "macd"] = macd_values["MACD_12_26_9"].iloc[MACD_LENGTH:]
        df.loc[MACD_LENGTH:, "macd_hist"] = macd_values["MACDh_12_26_9"].iloc[
            MACD_LENGTH:
        ]
        df.loc[MACD_LENGTH:, "macd_signal"] = macd_values["MACDs_12_26_9"].iloc[
            MACD_LENGTH:
        ]

        # ADX
        adx_values = ta.adx(df["high"], df["low"], df["close"], length=14)
        df.loc[ADX_LENGTH:, "adx"] = adx_values["ADX_14"].iloc[ADX_LENGTH:]

        # BBANDS
        bbands_values = ta.bbands(df["close"], length=20, std=2)
        df.loc[BBANDS_LENGTH:, "bb_upper"] = bbands_values["BBU_20_2.0"].iloc[
            BBANDS_LENGTH:
        ]
        df.loc[BBANDS_LENGTH:, "bb_middle"] = bbands_values["BBM_20_2.0"].iloc[
            BBANDS_LENGTH:
        ]
        df.loc[BBANDS_LENGTH:, "bb_lower"] = bbands_values["BBL_20_2.0"].iloc[
            BBANDS_LENGTH:
        ]
        df.loc[BBANDS_LENGTH:, "bb_width"] = bbands_values["BBB_20_2.0"].iloc[
            BBANDS_LENGTH:
        ]
        df.loc[BBANDS_LENGTH:, "bb_percent"] = bbands_values["BBP_20_2.0"].iloc[
            BBANDS_LENGTH:
        ]
        df["rsi"] = ta.rsi(df["close"], length=14)
        # df["adx"] = ta.adx(df["high"], df["low"], df["close"], length=14)["ADX_14"]
        # (
        #     df["bb_lower"],
        #     df["bb_middle"],
        #     df["bb_upper"],
        #     df["bb_width"],
        #     df["bb_percent"],
        # ) = ta.bbands(df["close"], length=20, std=2)

        df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
        df["ema_short"] = ta.ema(df["close"], length=9)
        df["ema_long"] = ta.ema(df["close"], length=26)

        # Save the updated dataframe to a new CSV file in the output directory
        output_file = os.path.join(output_dir, file)
        df.to_csv(output_file, index=False)

        print(f"Processed file: {file}")
