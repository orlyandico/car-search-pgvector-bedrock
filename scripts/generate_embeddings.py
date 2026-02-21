#!/usr/bin/env python3
import boto3
import json
import argparse
import psycopg2
from datetime import datetime

def get_db_connection():
    sm = boto3.client('secretsmanager')
    secret = sm.get_secret_value(SecretId='car-search/db-credentials')
    creds = json.loads(secret['SecretString'])
    
    return psycopg2.connect(
        host=creds['host'],
        port=creds['port'],
        database=creds['database'],
        user=creds['username'],
        password=creds['password'],
        sslmode='require'
    )

def get_listing_ids(start_id, end_id):
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
    cur.close()
    conn.close()
    
    return ids

def invoke_lambda(listing_ids):
    lambda_client = boto3.client('lambda')
    
    response = lambda_client.invoke(
        FunctionName='car-search-embeddings',
        InvocationType='RequestResponse',
        Payload=json.dumps({'listing_ids': listing_ids})
    )
    
    result = json.loads(response['Payload'].read())
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-id', type=int, default=1)
    parser.add_argument('--end-id', type=int, default=None)
    parser.add_argument('--batch-size', type=int, default=96)
    parser.add_argument('--limit', type=int, default=None, help='Limit number of listings to process (for testing)')
    args = parser.parse_args()
    
    print("Fetching listing IDs...")
    listing_ids = get_listing_ids(args.start_id, args.end_id)
    
    if args.limit:
        listing_ids = listing_ids[:args.limit]
        print(f"Limited to {len(listing_ids)} listings for testing")
    
    print(f"Found {len(listing_ids)} listings to process")
    
    if not listing_ids:
        print("No listings found")
        return
    
    total = len(listing_ids)
    processed = 0
    failed = 0
    start_time = datetime.now()
    
    print(f"\nProcessing in batches of {args.batch_size}...")
    
    for i in range(0, total, args.batch_size):
        batch = listing_ids[i:i+args.batch_size]
        batch_start = datetime.now()
        
        try:
            result = invoke_lambda(batch)
            
            if result.get('statusCode') == 200:
                body = json.loads(result['body'])
                count = body.get('processed', len(batch))
                processed += count
                elapsed = (datetime.now() - batch_start).total_seconds()
                print(f"Batch {i//args.batch_size + 1}/{(total + args.batch_size - 1)//args.batch_size}: "
                      f"Processed {count} listings ({elapsed:.1f}s)")
            else:
                print(f"Batch {i//args.batch_size + 1} failed: {result}")
                failed += len(batch)
        except Exception as e:
            print(f"Batch {i//args.batch_size + 1} error: {e}")
            failed += len(batch)
    
    total_elapsed = (datetime.now() - start_time).total_seconds()
    
    print(f"\nComplete!")
    print(f"Total processed: {processed}")
    print(f"Failed: {failed}")
    print(f"Time: {total_elapsed:.1f}s ({processed/total_elapsed:.0f} listings/sec)")

if __name__ == '__main__':
    main()
