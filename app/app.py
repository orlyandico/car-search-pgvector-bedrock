#!/usr/bin/env python3
import warnings
warnings.filterwarnings('ignore', message='Boto3 will no longer support Python')

from flask import Flask, render_template, request, jsonify
import psycopg2
import boto3
import json
import os
import logging
import sys
from datetime import datetime, timezone
from threading import Lock
from llm_utils import extract_filters

app = Flask(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Training data collection
TRAINING_DATA_FILE = os.path.join(os.path.dirname(__file__), 'training_data.jsonl')
training_data_lock = Lock()

def log_training_data(query, filters, semantic_query):
    """Thread-safe logging of query data for fine-tuning"""
    try:
        with training_data_lock:
            with open(TRAINING_DATA_FILE, 'a') as f:
                entry = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'query': query,
                    'filters': filters,
                    'semantic_query': semantic_query
                }
                f.write(json.dumps(entry) + '\n')
    except Exception as e:
        logger.error(f"Failed to log training data: {e}")

# Load filter extraction prompt
FILTER_PROMPT_PATH = os.path.join(os.path.dirname(__file__), 'filter_prompt.txt')
with open(FILTER_PROMPT_PATH, 'r') as f:
    FILTER_PROMPT_TEMPLATE = f.read()

def get_db_connection():
    sm = boto3.client('secretsmanager', region_name=os.environ.get('AWS_DEFAULT_REGION', 'eu-west-2'))
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

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search')
def search_page():
    return render_template('search.html')

@app.route('/hybrid')
def chat_page():
    return render_template('hybrid.html')

@app.route('/semantic')
def semantic_page():
    return render_template('semantic.html')

@app.route('/keyword')
def keyword_page():
    return render_template('keyword.html')

@app.route('/health')
def health():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
        return jsonify({'status': 'healthy'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 503

@app.route('/api/search', methods=['POST'])
def api_search():
    try:
        filters = request.json or {}
        logger.info(f"Received filters: {filters}")
        
        query = "SELECT * FROM car_listings WHERE 1=1"
        params = []
        
        if filters.get('manufacturers'):
            query += " AND manufacturer = ANY(%s)"
            params.append(filters['manufacturers'])
        
        if filters.get('types'):
            query += " AND type = ANY(%s)"
            params.append(filters['types'])
        
        if filters.get('min_year'):
            query += " AND year >= %s"
            params.append(int(filters['min_year']))
        
        if filters.get('max_year'):
            query += " AND year <= %s"
            params.append(int(filters['max_year']))
        
        if filters.get('min_price'):
            query += " AND price >= %s"
            params.append(int(filters['min_price']))
        
        if filters.get('max_price'):
            query += " AND price <= %s"
            params.append(int(filters['max_price']))
        
        if filters.get('min_odometer'):
            query += " AND odometer >= %s"
            params.append(int(filters['min_odometer']))
        
        if filters.get('max_odometer'):
            query += " AND odometer <= %s"
            params.append(int(filters['max_odometer']))
        
        if filters.get('fuel'):
            query += " AND fuel = %s"
            params.append(filters['fuel'])
        
        if filters.get('transmission'):
            query += " AND transmission = %s"
            params.append(filters['transmission'])
        
        if filters.get('condition'):
            query += " AND condition = %s"
            params.append(filters['condition'])
        
        if filters.get('color'):
            query += " AND paint_color = %s"
            params.append(filters['color'])
        
        if filters.get('states'):
            query += " AND state = ANY(%s)"
            params.append(filters['states'])
        
        if filters.get('keywords'):
            query += " AND to_tsvector('english', COALESCE(description, '')) @@ plainto_tsquery('english', %s)"
            params.append(filters['keywords'])
        
        sort_by = filters.get('sort_by', 'price')
        if sort_by == 'year':
            query += " ORDER BY year DESC"
        elif sort_by == 'odometer':
            query += " ORDER BY odometer ASC"
        else:
            query += " ORDER BY price ASC"
        
        query += " LIMIT 10"
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        
        columns = [desc[0] for desc in cur.description]
        results = []
        for row in cur.fetchall():
            results.append(dict(zip(columns, row)))
        
        cur.close()
        conn.close()
        
        return jsonify(results)
    
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'error': 'Something went wrong'}), 500

@app.route('/api/hybrid', methods=['POST'])
def api_chat():
    try:
        print("=== CHAT REQUEST RECEIVED ===", flush=True)
        user_query = request.json.get('query', '')
        if not user_query:
            return jsonify({'error': 'Query required'}), 400
        
        print(f"Chat query: {user_query}", flush=True)
        
        bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_DEFAULT_REGION', 'eu-west-2'))
        
        # Extract structured filters using LLM
        filters, semantic_query = extract_filters(bedrock, user_query)
        semantic_query = semantic_query.strip() if semantic_query else ''
            
        print(f"Extracted filters: {filters}", flush=True)
        print(f"Semantic query: '{semantic_query}'", flush=True)
        
        # Log training data
        log_training_data(user_query, filters, semantic_query)
        
        # Generate query embedding using semantic query (or original query if empty)
        embed_text = semantic_query if semantic_query else user_query
        print(f"Calling Bedrock for embedding with: '{embed_text}'", flush=True)
        response = bedrock.invoke_model(
            modelId='global.cohere.embed-v4:0',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'texts': [embed_text],
                'input_type': 'search_query',
                'embedding_types': ['float'],
                'output_dimension': 1024
            })
        )
        
        embedding = json.loads(response['body'].read())['embeddings']['float'][0]
        print(f"Received embedding with {len(embedding)} dimensions", flush=True)
        
        # Build hybrid query with filters
        print("Querying database with filters...", flush=True)
        query = """
            SELECT cl.*, 1 - (ce.embedding <=> %s::vector) AS similarity
            FROM car_embeddings ce
            JOIN car_listings cl ON cl.id = ce.listing_id
            WHERE 1=1
        """
        params = [embedding]
        
        if filters.get('min_price'):
            query += " AND cl.price >= %s"
            params.append(filters['min_price'])
        if filters.get('max_price'):
            query += " AND cl.price <= %s"
            params.append(filters['max_price'])
        if filters.get('min_year'):
            query += " AND cl.year >= %s"
            params.append(filters['min_year'])
        if filters.get('max_year'):
            query += " AND cl.year <= %s"
            params.append(filters['max_year'])
        if filters.get('min_odometer'):
            query += " AND cl.odometer >= %s"
            params.append(filters['min_odometer'])
        if filters.get('max_odometer'):
            query += " AND cl.odometer <= %s"
            params.append(filters['max_odometer'])
        if filters.get('type'):
            query += " AND cl.type = %s"
            params.append(filters['type'])
        if filters.get('fuel'):
            query += " AND cl.fuel = %s"
            params.append(filters['fuel'])
        if filters.get('transmission'):
            query += " AND cl.transmission = %s"
            params.append(filters['transmission'])
        if filters.get('condition'):
            query += " AND cl.condition = %s"
            params.append(filters['condition'])
        if filters.get('manufacturers'):
            query += " AND cl.manufacturer = ANY(%s)"
            params.append(filters['manufacturers'])
        if filters.get('drive'):
            query += " AND cl.drive = %s"
            params.append(filters['drive'])
        if filters.get('paint_color'):
            query += " AND cl.paint_color = %s"
            params.append(filters['paint_color'])
        if filters.get('cylinders'):
            query += " AND cl.cylinders = %s"
            params.append(filters['cylinders'])
        if filters.get('title_status'):
            query += " AND cl.title_status = %s"
            params.append(filters['title_status'])
        if filters.get('size'):
            query += " AND cl.size = %s"
            params.append(filters['size'])
        if filters.get('state'):
            query += " AND cl.state = %s"
            params.append(filters['state'])
        
        query += " ORDER BY ce.embedding <=> %s::vector LIMIT 10"
        params.append(embedding)
        
        conn = get_db_connection()
        cur = conn.cursor()
        print(f"SQL Query: {query}", flush=True)
        print(f"Executing query with {len(params)} parameters", flush=True)
        print(f"Non-embedding params: {params[1:-1]}", flush=True)
        cur.execute(query, params)
        
        print(f"Query executed, fetching results...", flush=True)
        rows = cur.fetchall()
        print(f"Fetched {len(rows)} rows from database", flush=True)
        
        columns = [desc[0] for desc in cur.description]
        results = []
        for row in rows:
            results.append(dict(zip(columns, row)))
        
        cur.close()
        conn.close()
        
        print(f"Found {len(results)} results", flush=True)
        
        return jsonify(results)
    
    except Exception as e:
        print(f"CHAT ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'error': 'Something went wrong'}), 500

@app.route('/api/semantic', methods=['POST'])
def api_semantic():
    try:
        user_query = request.json.get('query', '')
        if not user_query:
            return jsonify({'error': 'Query required'}), 400
        
        bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_DEFAULT_REGION', 'eu-west-2'))
        
        # Generate query embedding
        response = bedrock.invoke_model(
            modelId='global.cohere.embed-v4:0',
            contentType='application/json',
            accept='application/json',
            body=json.dumps({
                'texts': [user_query],
                'input_type': 'search_query',
                'embedding_types': ['float'],
                'output_dimension': 1024
            })
        )
        
        embedding = json.loads(response['body'].read())['embeddings']['float'][0]
        
        # Pure semantic search - no filters
        query = """
            SELECT cl.*, 1 - (ce.embedding <=> %s::vector) AS similarity
            FROM car_embeddings ce
            JOIN car_listings cl ON cl.id = ce.listing_id
            ORDER BY ce.embedding <=> %s::vector
            LIMIT 10
        """
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, [embedding, embedding])
        
        columns = [desc[0] for desc in cur.description]
        results = [dict(zip(columns, row)) for row in cur.fetchall()]
        
        cur.close()
        conn.close()
        
        return jsonify(results)
    
    except Exception as e:
        logger.error(f"Semantic search error: {e}")
        return jsonify({'error': 'Something went wrong'}), 500

@app.route('/api/keyword', methods=['POST'])
def api_keyword():
    try:
        print("=== KEYWORD REQUEST RECEIVED ===", flush=True)
        user_query = request.json.get('query', '')
        if not user_query:
            return jsonify({'error': 'Query required'}), 400
        
        print(f"Keyword query: {user_query}", flush=True)
        
        bedrock = boto3.client('bedrock-runtime', region_name=os.environ.get('AWS_DEFAULT_REGION', 'eu-west-2'))
        
        # Extract structured filters using LLM
        filters, semantic_query = extract_filters(bedrock, user_query)
        semantic_query = semantic_query.strip() if semantic_query else ''
        
        print(f"Extracted filters: {filters}", flush=True)
        print(f"Semantic query: '{semantic_query}'", flush=True)
        
        # Log training data
        log_training_data(user_query, filters, semantic_query)
        
        # Build query with filters + keyword search
        print("Building SQL query with filters...", flush=True)
        query = "SELECT * FROM car_listings WHERE 1=1"
        params = []
        
        if filters.get('min_price'):
            query += " AND price >= %s"
            params.append(filters['min_price'])
        if filters.get('max_price'):
            query += " AND price <= %s"
            params.append(filters['max_price'])
        if filters.get('min_year'):
            query += " AND year >= %s"
            params.append(filters['min_year'])
        if filters.get('max_year'):
            query += " AND year <= %s"
            params.append(filters['max_year'])
        if filters.get('min_odometer'):
            query += " AND odometer >= %s"
            params.append(filters['min_odometer'])
        if filters.get('max_odometer'):
            query += " AND odometer <= %s"
            params.append(filters['max_odometer'])
        if filters.get('type'):
            query += " AND type = %s"
            params.append(filters['type'])
        if filters.get('fuel'):
            query += " AND fuel = %s"
            params.append(filters['fuel'])
        if filters.get('transmission'):
            query += " AND transmission = %s"
            params.append(filters['transmission'])
        if filters.get('condition'):
            query += " AND condition = %s"
            params.append(filters['condition'])
        if filters.get('manufacturers'):
            query += " AND manufacturer = ANY(%s)"
            params.append(filters['manufacturers'])
        if filters.get('drive'):
            query += " AND drive = %s"
            params.append(filters['drive'])
        if filters.get('paint_color'):
            query += " AND paint_color = %s"
            params.append(filters['paint_color'])
        if filters.get('cylinders'):
            query += " AND cylinders = %s"
            params.append(filters['cylinders'])
        if filters.get('title_status'):
            query += " AND title_status = %s"
            params.append(filters['title_status'])
        if filters.get('size'):
            query += " AND size = %s"
            params.append(filters['size'])
        if filters.get('state'):
            query += " AND state = %s"
            params.append(filters['state'])
        
        # Add keyword search on description only if semantic query exists
        if semantic_query:
            query += " AND to_tsvector('english', COALESCE(description, '')) @@ plainto_tsquery('english', %s)"
            params.append(semantic_query)
        
        query += " LIMIT 10"
        
        print(f"SQL Query: {query}", flush=True)
        print(f"Executing query with {len(params)} parameters", flush=True)
        print(f"Non-keyword params: {params[:-1]}", flush=True)
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(query, params)
        
        print(f"Query executed, fetching results...", flush=True)
        rows = cur.fetchall()
        print(f"Fetched {len(rows)} rows from database", flush=True)
        
        columns = [desc[0] for desc in cur.description]
        results = [dict(zip(columns, row)) for row in rows]
        
        cur.close()
        conn.close()
        
        print(f"Found {len(results)} results", flush=True)
        
        return jsonify(results)
    
    except Exception as e:
        print(f"KEYWORD ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()
        logger.error(f"Keyword search error: {e}")
        return jsonify({'error': 'Something went wrong'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
