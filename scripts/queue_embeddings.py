#!/usr/bin/env python3
import boto3
import json
import argparse
import psycopg2
from datetime import datetime

def get_db_connection():
    sm = boto3.client('secretsmanager')
    
    response = sm.list_secrets(Filters=[{'Key': 'name', 'Values': ['car-search/db-credentials-']}])
    if not response['SecretList']:
        raise Exception('No secret found with prefix car-search/db-credentials-')
    
    secret = sm.get_secret_value(SecretId=response['SecretList'][0]['ARN'])
    creds = json.loads(secret['SecretString'])
    
    return psycopg2.connect(
        host=creds['host'],
        port=creds['port'],
        database=creds['database'],
        user=creds['username'],
        password=creds['password'],
        sslmode='require'
    )

def queue_listing_ids(start_id, end_id, limit):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if end_id:
        cur.execute("""
            SELECT cl.id FROM car_listings cl
            LEFT JOIN car_embeddings ce ON cl.id = ce.listing_id
            WHERE cl.id >= %s AND cl.id <= %s AND ce.listing_id IS NULL
            ORDER BY cl.id
        """, (start_id, end_id))
    else:
        cur.execute("""
            SELECT cl.id FROM car_listings cl
            LEFT JOIN car_embeddings ce ON cl.id = ce.listing_id
            WHERE cl.id >= %s AND ce.listing_id IS NULL
            ORDER BY cl.id
        """, (start_id,))
    
    ids = [row[0] for row in cur.fetchall()]
    
    if limit:
        ids = ids[:limit]
    
    if not ids:
        print("No listings found")
        cur.close()
        conn.close()
        return 0
    
    print(f"Queueing {len(ids)} listings...")
    start_time = datetime.now()
    
    # Batch insert in chunks of 10000 for efficiency
    batch_size = 10000
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i+batch_size]
        # Use execute_values for safe bulk insert
        from psycopg2.extras import execute_values
        execute_values(
            cur,
            "INSERT INTO embedding_queue (listing_id) VALUES %s ON CONFLICT (listing_id) DO NOTHING",
            [(id,) for id in batch]
        )
        conn.commit()
        print(f"  Queued {min(i+batch_size, len(ids))}/{len(ids)}")
    
    elapsed = (datetime.now() - start_time).total_seconds()
    
    cur.close()
    conn.close()
    
    print(f"Queued {len(ids)} listings in {elapsed:.1f}s")
    return len(ids)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-id', type=int, default=1)
    parser.add_argument('--end-id', type=int, default=None)
    parser.add_argument('--limit', type=int, default=None, help='Limit number of listings to queue (for testing)')
    args = parser.parse_args()
    
    queued = queue_listing_ids(args.start_id, args.end_id, args.limit)
    
    if queued > 0:
        print(f"\npg_cron will process ~{min(queued, 672)} listings per minute")
        print(f"Estimated completion: {queued / 672:.0f} minutes")

if __name__ == '__main__':
    main()
