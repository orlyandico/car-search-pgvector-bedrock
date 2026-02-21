import json
import os

FILTER_PROMPT_PATH = os.path.join(os.path.dirname(__file__), 'filter_prompt.txt')
with open(FILTER_PROMPT_PATH, 'r') as f:
    prompt_content = f.read()
    # Extract model from first line if present
    lines = prompt_content.split('\n')
    if lines[0].startswith('# Model:'):
        DEFAULT_MODEL_ID = lines[0].replace('# Model:', '').strip()
        FILTER_PROMPT_TEMPLATE = '\n'.join(lines[1:]).strip()
    else:
        DEFAULT_MODEL_ID = 'zai.glm-4.7'
        FILTER_PROMPT_TEMPLATE = prompt_content

def extract_filters(bedrock_client, user_query, model_id=None):
    """Extract structured filters from natural language query using LLM.
    
    Args:
        bedrock_client: boto3 bedrock-runtime client
        user_query: Natural language search query
        model_id: Bedrock model ID (defaults to model from prompt file or env var)
    
    Returns:
        tuple: (filters dict, semantic_query string)
    """
    if model_id is None:
        model_id = os.environ.get('FILTER_MODEL_ID', DEFAULT_MODEL_ID)
    
    import boto3
    llm_client = boto3.client('bedrock-runtime', region_name='us-east-1')
    
    print(f"Using model: {model_id}", flush=True)
    
    filter_prompt = FILTER_PROMPT_TEMPLATE.format(query=user_query)
    
    response = llm_client.converse(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [{"text": filter_prompt}]
        }],
        inferenceConfig={'maxTokens': 200, 'temperature': 0.1}
    )
    filters_text = response["output"]["message"]["content"][0]["text"].strip()
    
    print(f"Raw LLM output: {filters_text}", flush=True)
    
    # Parse JSON response
    filters = {}
    semantic_query = user_query
    
    try:
        if filters_text.startswith('```'):
            filters_text = filters_text.split('```')[1]
            if filters_text.startswith('json'):
                filters_text = filters_text[4:]
            filters_text = filters_text.strip()
        
        response_json = json.loads(filters_text)
        filters = response_json.get('filters', {})
        semantic_query = response_json.get('semantic_query', user_query)
        
        # Don't override empty semantic_query - it's intentional when all terms are structural
        if semantic_query is None:
            semantic_query = user_query
    except Exception:
        pass
    
    return filters, semantic_query
