#!/usr/bin/env python3
import boto3
import json
import os
import psycopg2
from datetime import datetime

def get_db_connection():
    region = os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')
    secrets = boto3.client('secretsmanager', region_name=region)
    secret = secrets.get_secret_value(SecretId='car-search/db-credentials')
    creds = json.loads(secret['SecretString'])
    
    return psycopg2.connect(
        host=creds['host'],
        port=creds['port'],
        database=creds['database'],
        user=creds['username'],
        password=creds['password'],
        sslmode='require'
    )

def generate_fake_listing():
    # GLM-4.7 is only available in us-east-1
    bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
    
    prompt = """Generate a realistic used car listing as JSON. Choose a RANDOM manufacturer from this list:
toyota, honda, ford, chevrolet, bmw, mercedes-benz, audi, volkswagen, nissan, hyundai, mazda, subaru, jeep, dodge, ram, gmc, lexus, porsche, tesla, volvo

Required fields:
- manufacturer (lowercase, from list above - pick randomly)
- model (lowercase, appropriate for the manufacturer)
- year (2010-2024)
- price (5000-50000)
- odometer (10000-150000)
- condition (one of: excellent, like new, good, fair)
- fuel (one of: gas, diesel, electric, hybrid)
- transmission (one of: automatic, manual)
- type (one of: sedan, suv, truck, coupe, hatchback, wagon, van, convertible)
- drive (one of: fwd, rwd, 4wd)
- paint_color (lowercase)
- cylinders (e.g., "4 cylinders", "6 cylinders")
- description (2-3 sentences describing the car)

Return ONLY valid JSON, no markdown."""

    response = bedrock.invoke_model(
        modelId='zai.glm-4.7',
        contentType='application/json',
        body=json.dumps({
            'max_tokens': 500,
            'temperature': 1.0,
            'messages': [{'role': 'user', 'content': prompt}]
        })
    )
    
    result = json.loads(response['body'].read())
    listing_json = result['choices'][0]['message']['content'].strip()
    
    if listing_json.startswith('```'):
        listing_json = listing_json.split('```')[1].replace('json', '').strip()
    
    return json.loads(listing_json)

def insert_listing(conn, listing):
    cur = conn.cursor()
    
    # Get max ID
    cur.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM car_listings")
    new_id = cur.fetchone()[0]
    
    cur.execute("""
        INSERT INTO car_listings (
            id, manufacturer, model, year, price, odometer, condition,
            fuel, transmission, type, drive, paint_color, cylinders, description,
            posting_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        new_id,
        listing.get('manufacturer'),
        listing.get('model'),
        listing.get('year'),
        listing.get('price'),
        listing.get('odometer'),
        listing.get('condition'),
        listing.get('fuel'),
        listing.get('transmission'),
        listing.get('type'),
        listing.get('drive'),
        listing.get('paint_color'),
        listing.get('cylinders'),
        listing.get('description'),
        datetime.now()
    ))
    
    conn.commit()
    listing_id = cur.fetchone()[0]
    cur.close()
    
    return listing_id

if __name__ == '__main__':
    print("Generating fake car listing...")
    listing = generate_fake_listing()
    
    print("\nGenerated listing:")
    print(json.dumps(listing, indent=2))
    
    print("\nInserting into database...")
    conn = get_db_connection()
    listing_id = insert_listing(conn, listing)
    conn.close()
    
    print(f"\n✓ Inserted listing with ID: {listing_id}")
    print("Trigger will queue embedding generation automatically.")
