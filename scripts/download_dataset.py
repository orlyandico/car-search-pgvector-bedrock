#!/usr/bin/env python3
import os
import requests
from tqdm import tqdm

DATASET_URL = "https://media.githubusercontent.com/media/gabrieldonadel/used-cars-dataset/master/dataset.csv"
DATASET_PATH = "data/dataset.csv"

def download_dataset():
    if os.path.exists(DATASET_PATH):
        print(f"Dataset already exists at {DATASET_PATH}")
        return
    
    os.makedirs(os.path.dirname(DATASET_PATH), exist_ok=True)
    
    print(f"Downloading dataset from {DATASET_URL}...")
    response = requests.get(DATASET_URL, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    
    with open(DATASET_PATH, 'wb') as f, tqdm(total=total_size, unit='B', unit_scale=True) as pbar:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            pbar.update(len(chunk))
    
    print(f"Downloaded to {DATASET_PATH}")

if __name__ == "__main__":
    download_dataset()
