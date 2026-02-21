#!/usr/bin/env python3
import json
import sys
import os
import boto3
import argparse
import csv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
from llm_utils import extract_filters

def load_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), 'synthetic_query_prompt.txt')
    with open(prompt_path) as f:
        return f.read().strip()

# Update these with your model IDs
GLM_MODEL = 'zai.glm-4.7'
NOVA_BASE_MODEL = 'us.amazon.nova-micro-v1:0'
NOVA_FINETUNED_ARN = 'arn:aws:bedrock:us-east-1:010928215215:custom-model-deployment/YOUR_DEPLOYMENT_NAME'

def generate_queries(client):
    response = client.invoke_model(
        modelId=GLM_MODEL,
        contentType='application/json',
        body=json.dumps({
            
            'max_tokens': 1000,
            'temperature': 1.0,
            'messages': [{'role': 'user', 'content': load_prompt()}]
        })
    )
    result = json.loads(response['body'].read())
    response_text = result['choices'][0]['message']['content'].strip()
    
    # Parse JSON array
    if response_text.startswith('```'):
        response_text = response_text.split('```')[1]
        if response_text.startswith('json'):
            response_text = response_text[4:]
        response_text = response_text.strip()
    
    return json.loads(response_text)

def compare_outputs(client, query, glm_output, nova_base_output, nova_finetuned_output):
    comparison_prompt = f"""Compare these three JSON outputs from filter extraction models for the query: "{query}"

GLM-4.7 (baseline - the model we're trying to replace):
{glm_output}

Nova Micro base (before fine-tuning):
{nova_base_output}

Nova Micro fine-tuned (after fine-tuning):
{nova_finetuned_output}

Evaluate each Nova model against the GLM-4.7 baseline:

1. Are all three valid JSON?
2. Does Nova base extract the same filters as GLM-4.7? Any missing or incorrect filters?
3. Does Nova fine-tuned extract the same filters as GLM-4.7? Any missing or incorrect filters?
4. Did fine-tuning improve Nova's accuracy?

Provide two verdicts with reasoning:
- Nova Base vs GLM-4.7: PASS if Nova base extracts equivalent or better filters than GLM-4.7, FAIL if it misses important filters or extracts incorrect ones
- Nova Fine-tuned vs GLM-4.7: PASS if Nova fine-tuned extracts equivalent or better filters than GLM-4.7, FAIL if it misses important filters or extracts incorrect ones

Format (must follow exactly):
Analysis: <3-4 sentences comparing all three outputs>
Nova Base vs GLM-4.7: PASS or FAIL - <reason>
Nova Fine-tuned vs GLM-4.7: PASS or FAIL - <reason>"""

    response = client.invoke_model(
        modelId=GLM_MODEL,
        contentType='application/json',
        body=json.dumps({
            
            'max_tokens': 500,
            'messages': [{'role': 'user', 'content': comparison_prompt}]
        })
    )
    result = json.loads(response['body'].read())
    response_text = result['choices'][0]['message']['content'].strip()
    
    # Parse analysis and verdicts with reasons
    lines = response_text.split('\n')
    analysis = ''
    nova_base_verdict = 'UNKNOWN'
    nova_base_reason = ''
    nova_finetuned_verdict = 'UNKNOWN'
    nova_finetuned_reason = ''
    
    for line in lines:
        if line.startswith('Analysis:'):
            analysis = line.replace('Analysis:', '').strip()
        elif 'Nova Base vs GLM-4.7:' in line:
            parts = line.split(' - ', 1)
            nova_base_verdict = 'PASS' if 'PASS' in parts[0] else 'FAIL'
            nova_base_reason = parts[1].strip() if len(parts) > 1 else ''
        elif 'Nova Fine-tuned vs GLM-4.7:' in line:
            parts = line.split(' - ', 1)
            nova_finetuned_verdict = 'PASS' if 'PASS' in parts[0] else 'FAIL'
            nova_finetuned_reason = parts[1].strip() if len(parts) > 1 else ''
    
    return analysis, nova_base_verdict, nova_base_reason, nova_finetuned_verdict, nova_finetuned_reason

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--finetuned-arn', help='Fine-tuned model deployment ARN')
    parser.add_argument('--output', default='test_results.csv', help='Output CSV file')
    args = parser.parse_args()
    
    finetuned_arn = args.finetuned_arn or NOVA_FINETUNED_ARN
    
    if 'YOUR_DEPLOYMENT_NAME' in finetuned_arn:
        print("Error: Update NOVA_FINETUNED_ARN in script or use --finetuned-arn")
        sys.exit(1)
    
    client = boto3.client('bedrock-runtime', region_name='us-east-1')
    
    print("Generating 20 synthetic queries...")
    queries = generate_queries(client)
    print(f"Generated {len(queries)} queries\n")
    
    results = []
    
    for i, query in enumerate(queries, 1):
        print(f"=== Query {i}/20 ===")
        print(f"Query: {query}\n")
        
        print("Calling GLM-4.7 baseline...")
        glm_filters, glm_semantic = extract_filters(client, query, model_id=GLM_MODEL)
        glm_output = json.dumps({'filters': glm_filters, 'semantic_query': glm_semantic})
        print(f"GLM-4.7: {glm_output}\n")
        
        print("Calling Nova Micro base (before fine-tuning)...")
        nova_base_filters, nova_base_semantic = extract_filters(client, query, model_id=NOVA_BASE_MODEL)
        nova_base_output = json.dumps({'filters': nova_base_filters, 'semantic_query': nova_base_semantic})
        print(f"Nova Base: {nova_base_output}\n")
        
        print("Calling Nova Micro fine-tuned...")
        nova_ft_filters, nova_ft_semantic = extract_filters(client, query, model_id=finetuned_arn)
        nova_ft_output = json.dumps({'filters': nova_ft_filters, 'semantic_query': nova_ft_semantic})
        print(f"Nova Fine-tuned: {nova_ft_output}\n")
        
        print("Comparing outputs with GLM-4.7...")
        analysis, base_verdict, base_reason, ft_verdict, ft_reason = compare_outputs(client, query, glm_output, nova_base_output, nova_ft_output)
        print(f"Analysis: {analysis}")
        print(f"Nova Base vs GLM-4.7: {base_verdict} - {base_reason}")
        print(f"Nova Fine-tuned vs GLM-4.7: {ft_verdict} - {ft_reason}\n")
        print("-" * 80 + "\n")
        
        results.append({
            'query': query,
            'glm_output': glm_output,
            'nova_base_output': nova_base_output,
            'nova_finetuned_output': nova_ft_output,
            'analysis': analysis,
            'nova_base_verdict': base_verdict,
            'nova_base_reason': base_reason,
            'nova_finetuned_verdict': ft_verdict,
            'nova_finetuned_reason': ft_reason
        })
    
    # Write CSV report
    with open(args.output, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['query', 'glm_output', 'nova_base_output', 'nova_finetuned_output', 'analysis', 'nova_base_verdict', 'nova_base_reason', 'nova_finetuned_verdict', 'nova_finetuned_reason'])
        writer.writeheader()
        writer.writerows(results)
    
    # Summary
    base_pass = sum(1 for r in results if r['nova_base_verdict'] == 'PASS')
    ft_pass = sum(1 for r in results if r['nova_finetuned_verdict'] == 'PASS')
    
    print(f"\n{'='*80}")
    print(f"SUMMARY")
    print(f"{'='*80}")
    print(f"Total queries: {len(results)}")
    print(f"\nNova Base vs GLM-4.7:")
    print(f"  Pass: {base_pass} ({base_pass/len(results)*100:.1f}%)")
    print(f"  Fail: {len(results)-base_pass} ({(len(results)-base_pass)/len(results)*100:.1f}%)")
    print(f"\nNova Fine-tuned vs GLM-4.7:")
    print(f"  Pass: {ft_pass} ({ft_pass/len(results)*100:.1f}%)")
    print(f"  Fail: {len(results)-ft_pass} ({(len(results)-ft_pass)/len(results)*100:.1f}%)")
    print(f"\nImprovement: {ft_pass - base_pass} queries ({(ft_pass - base_pass)/len(results)*100:.1f}%)")
    print(f"\nResults saved to: {args.output}")

if __name__ == '__main__':
    main()
