import kagglehub
import shutil
import os

# Download latest version
handle = "andyjava/crypto-trading-dataset-ohlcv-and-indicators"  # "andyjava/crypto-trading-dataset-ohlcv-and-indicators"

path = kagglehub.dataset_download(handle)

print("Files downloaded at:", path)

# Move downloaded files to data/raw
destination_dir = "data/raw"
destination_path = os.path.join(destination_dir, os.path.basename(path))

# Remove existing directory if it exists
if os.path.exists(destination_path):
    shutil.rmtree(destination_path)

shutil.move(path, destination_dir)

print("Files moved to:", destination_dir)
