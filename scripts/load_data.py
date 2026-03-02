#!/usr/bin/env python3
import argparse
import json
import os
import sys
from datetime import datetime

import boto3
import pandas as pd
import psycopg2
import psycopg2.extras


def get_db_connection():
    sm = boto3.client(
        "secretsmanager", region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    )
    
    response = sm.list_secrets(Filters=[{'Key': 'name', 'Values': ['car-search/db-credentials-']}])
    if not response['SecretList']:
        raise Exception('No secret found with prefix car-search/db-credentials-')
    
    secret = sm.get_secret_value(SecretId=response['SecretList'][0]['ARN'])
    creds = json.loads(secret["SecretString"])

    return psycopg2.connect(
        host=creds["host"],
        port=creds["port"],
        database=creds["database"],
        user=creds["username"],
        password=creds["password"],
        sslmode="require",
    )


def create_schema(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS car_listings (
                id BIGINT PRIMARY KEY,
                url TEXT,
                region TEXT,
                price INTEGER,
                year SMALLINT,
                manufacturer TEXT,
                model TEXT,
                condition TEXT,
                cylinders TEXT,
                fuel TEXT,
                odometer INTEGER,
                title_status TEXT,
                transmission TEXT,
                vin TEXT,
                drive TEXT,
                size TEXT,
                type TEXT,
                paint_color TEXT,
                image_url TEXT,
                description TEXT,
                state TEXT,
                lat DOUBLE PRECISION,
                long DOUBLE PRECISION,
                posting_date TIMESTAMPTZ
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS car_embeddings (
                id SERIAL PRIMARY KEY,
                listing_id BIGINT NOT NULL REFERENCES car_listings(id) ON DELETE CASCADE,
                embedding_text TEXT NOT NULL,
                embedding vector(1024) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT unique_listing UNIQUE (listing_id)
            )
        """)

        indices = [
            "CREATE INDEX IF NOT EXISTS idx_car_listings_manufacturer ON car_listings(manufacturer)",
            "CREATE INDEX IF NOT EXISTS idx_car_listings_year ON car_listings(year)",
            "CREATE INDEX IF NOT EXISTS idx_car_listings_price ON car_listings(price)",
            "CREATE INDEX IF NOT EXISTS idx_car_listings_type ON car_listings(type)",
            "CREATE INDEX IF NOT EXISTS idx_car_listings_fuel ON car_listings(fuel)",
            "CREATE INDEX IF NOT EXISTS idx_car_listings_state ON car_listings(state)",
            "CREATE INDEX IF NOT EXISTS idx_car_listings_description_gin ON car_listings USING gin(to_tsvector('english', COALESCE(description, '')))",
            """CREATE INDEX IF NOT EXISTS idx_car_embeddings_hnsw ON car_embeddings
               USING hnsw (embedding vector_cosine_ops)
               WITH (m = 16, ef_construction = 64)""",
        ]

        for idx in indices:
            cur.execute(idx)

        conn.commit()


def load_data(conn, df, batch_size):
    import numpy as np

    with conn.cursor() as cur:
        # Convert DataFrame to list of tuples with native Python types
        rows = []
        for row in df.itertuples(index=False):
            converted = []
            for val in row:
                if pd.isna(val):
                    converted.append(None)
                elif isinstance(val, (np.integer, np.int32, np.int64)):
                    converted.append(int(val))
                elif isinstance(val, (np.floating, np.float32, np.float64)):
                    converted.append(float(val))
                else:
                    converted.append(val)
            rows.append(tuple(converted))

        query = """
            INSERT INTO car_listings (
                id, url, region, price, year, manufacturer, model, condition,
                cylinders, fuel, odometer, title_status, transmission, vin,
                drive, size, type, paint_color, image_url, description,
                state, lat, long, posting_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """

        total = len(rows)
        for i in range(0, total, batch_size):
            batch_start = datetime.now()
            batch = rows[i : i + batch_size]
            psycopg2.extras.execute_batch(cur, query, batch, page_size=batch_size)
            conn.commit()
            batch_elapsed = (datetime.now() - batch_start).total_seconds()
            print(
                f"Processed {min(i + batch_size, total)}/{total} rows ({batch_elapsed:.1f}s)"
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--truncate", action="store_true")
    parser.add_argument(
        "--info", action="store_true", help="Show data info without loading"
    )
    args = parser.parse_args()

    if args.info:
        print("\nInfo mode - skipping database load")
        return

    print("Connecting to Aurora...")
    conn = get_db_connection()

    print("Creating schema...")
    create_schema(conn)

    if args.truncate:
        print("Truncating existing data...")
        with conn.cursor() as cur:
            cur.execute("TRUNCATE car_listings CASCADE")
            conn.commit()

    print("Loading dataset...")
    df = pd.read_csv("data/dataset.csv")
    print(f"Loaded {len(df)} rows")

    print("\nNumeric field distributions:")
    for col in ["price", "year", "odometer"]:
        if col in df.columns:
            print(f"\n{col}:")
            print(df[col].describe())
            print(f"1st percentile: {df[col].quantile(0.01)}")

    print("\nCleansing data...")
    # Handle invalid IDs - assign sequential IDs starting from 10 billion
    invalid_id_mask = df["id"].isna() | ~df["id"].astype(str).str.isdigit()
    invalid_count = invalid_id_mask.sum()
    if invalid_count > 0:
        print(f"Assigning new IDs to {invalid_count} rows with invalid IDs")
        df.loc[invalid_id_mask, "id"] = range(10000000000, 10000000000 + invalid_count)

    df["id"] = df["id"].astype("int64")

    # Calculate 1st percentile for lower bounds
    price_lower = int(df["price"].quantile(0.01)) if "price" in df.columns else 100
    year_lower = int(df["year"].quantile(0.01)) if "year" in df.columns else 1990

    print(f"Using price lower bound: ${price_lower}")
    print(f"Using year lower bound: {year_lower}")

    # Filter price and year, but keep nulls
    price_filtered = df[
        (df["price"].isna()) | ((df["price"] >= price_lower) & (df["price"] <= 250000))
    ].copy()
    print(f"Price filter removed {len(df) - len(price_filtered)} rows")
    df = price_filtered

    year_filtered = df[
        (df["year"].isna()) | ((df["year"] >= year_lower) & (df["year"] <= 2030))
    ].copy()
    print(f"Year filter removed {len(df) - len(year_filtered)} rows")
    df = year_filtered

    # Remove rows with null price or odometer
    before_null_filter = len(df)
    df = df[df["price"].notna() & df["odometer"].notna()].copy()
    print(f"Null price/odometer filter removed {before_null_filter - len(df)} rows")

    # Cap odometer at 999999
    if "odometer" in df.columns:
        df.loc[df["odometer"] > 999999, "odometer"] = 999999

    # Check for integer overflow issues
    print(f"Max id: {df['id'].max()}")
    print(f"Max price: {df['price'].max()}")
    print(f"Max odometer: {df['odometer'].max()}")

    text_cols = [
        "region",
        "manufacturer",
        "model",
        "condition",
        "cylinders",
        "fuel",
        "title_status",
        "transmission",
        "vin",
        "drive",
        "size",
        "type",
        "paint_color",
        "description",
        "state",
    ]
    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].str.lower()

    if "region_url" in df.columns:
        df = df.drop(columns=["region_url"])
    if "county" in df.columns:
        df = df.drop(columns=["county"])

    print(f"After cleansing: {len(df)} rows")

    print("Loading data...")
    start = datetime.now()
    load_data(conn, df, args.batch_size)
    elapsed = (datetime.now() - start).total_seconds()

    print(f"\nComplete! Loaded {len(df)} rows in {elapsed:.1f}s")

    conn.close()


if __name__ == "__main__":
    main()
