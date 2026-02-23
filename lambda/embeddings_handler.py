import json
import psycopg2
import boto3
from botocore.config import Config
import os

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

def compose_embedding_text(row):
    parts = []
    
    if row['year']: parts.append(str(int(row['year'])))
    if row['manufacturer']: parts.append(row['manufacturer'])
    if row['model']: parts.append(row['model'])
    
    details = []
    if row['type']: details.append(row['type'])
    if row['condition']: details.append(f"{row['condition']} condition")
    if row['odometer']: details.append(f"{int(row['odometer'])} miles")
    if row['fuel']: details.append(f"{row['fuel']} fuel")
    if row['transmission']: details.append(f"{row['transmission']} transmission")
    if row['drive']: details.append(f"{row['drive']} drive")
    if row['paint_color']: details.append(row['paint_color'])
    if row['price']: details.append(f"${int(row['price'])}")
    
    if parts:
        text = ' '.join(parts)
        if details:
            text += ', ' + ', '.join(details) + '.'
    else:
        text = ', '.join(details) + '.' if details else ''
    
    if row['description']:
        desc = row['description'][:2000]
        if len(row['description']) > 2000:
            desc = desc.rsplit(' ', 1)[0]
        if text:
            text += '\n' + desc
        else:
            text = desc
    
    return text or 'No description'

def lambda_handler(event, context):
    listing_ids = event.get('listing_ids', [])
    print(f"Received request for {len(listing_ids)} listing IDs")
    
    if not listing_ids:
        print("ERROR: No listing_ids provided")
        return {'statusCode': 400, 'body': 'No listing_ids provided'}
    
    conn = None
    try:
        print(f"Connecting to database...")
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Fetch listings
        print(f"Fetching listings from database...")
        cur.execute("""
            SELECT id, year, manufacturer, model, type, condition, odometer, fuel,
                   transmission, drive, paint_color, price, description
            FROM car_listings
            WHERE id = ANY(%s)
        """, (listing_ids,))
        
        rows = cur.fetchall()
        print(f"Found {len(rows)} listings in database")
        
        if not rows:
            print("WARNING: No listings found for provided IDs")
            return {'statusCode': 200, 'body': 'No listings found'}
        
        # Compose texts
        cols = ['id', 'year', 'manufacturer', 'model', 'type', 'condition', 'odometer',
                'fuel', 'transmission', 'drive', 'paint_color', 'price', 'description']
        listings = [dict(zip(cols, row)) for row in rows]
        texts = [compose_embedding_text(l) for l in listings]
        print(f"Composed {len(texts)} embedding texts")
        
        # Call Bedrock with limited retries
        print(f"Calling Bedrock for embeddings...")
        bedrock_config = Config(
            retries={'max_attempts': 2, 'mode': 'standard'}
        )
        bedrock = boto3.client('bedrock-runtime', config=bedrock_config)
        response = bedrock.invoke_model(
            modelId='global.cohere.embed-v4:0',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'texts': texts,
                'input_type': 'search_document',
                'embedding_types': ['float'],
                'output_dimension': 1024
            })
        )
        
        result = json.loads(response['body'].read())
        embeddings = result['embeddings']['float']
        print(f"Received {len(embeddings)} embeddings from Bedrock")
        
        # Upsert embeddings
        print(f"Upserting embeddings to database...")
        processed_ids = []
        for listing, text, embedding in zip(listings, texts, embeddings):
            cur.execute("""
                INSERT INTO car_embeddings (listing_id, embedding_text, embedding)
                VALUES (%s, %s, %s)
                ON CONFLICT (listing_id) DO UPDATE SET
                    embedding_text = EXCLUDED.embedding_text,
                    embedding = EXCLUDED.embedding,
                    created_at = NOW()
            """, (listing['id'], text, embedding))
            processed_ids.append(listing['id'])
        
        # Clear successfully processed IDs from queue (if table exists)
        try:
            print(f"Clearing {len(processed_ids)} IDs from embedding_queue...")
            cur.execute("DELETE FROM embedding_queue WHERE listing_id = ANY(%s)", (processed_ids,))
        except psycopg2.Error as e:
            print(f"WARNING: Failed to clear queue (table may not exist): {e}")
        
        conn.commit()
        cur.close()
        
        print(f"Successfully processed {len(listings)} listings")
        return {
            'statusCode': 200,
            'body': json.dumps({'processed': len(listings)})
        }
        
    except psycopg2.Error as e:
        print(f"ERROR: Database error: {e}")
        if conn:
            conn.rollback()
        return {'statusCode': 500, 'body': f'Database error: {str(e)}'}
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        if conn:
            conn.rollback()
        return {'statusCode': 500, 'body': f'Error: {str(e)}'}
    finally:
        if conn:
            conn.close()
