#!/usr/bin/env python3
"""Generate fine-tuning data from synthetic queries."""
import json
import sys
import os
import argparse
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
from llm_utils import extract_filters

import boto3


def load_prompt_template():
    prompt_path = os.path.join(os.path.dirname(__file__), '..', 'app', 'filter_prompt.txt')
    
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    
    with open(prompt_path) as f:
        content = f.read()
    lines = content.split('\n')
    if lines[0].startswith('# Model:'):
        return '\n'.join(lines[1:]).strip()
    return content.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', default='data/synthetic_queries.jsonl')
    parser.add_argument('--output', default='data/finetune_data.jsonl')
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        raise FileNotFoundError(f"Input file not found: {args.input}")

    # GLM-4.7 is only available in us-east-1
    client = boto3.client('bedrock-runtime', region_name='us-east-1')
    template = load_prompt_template()

    with open(args.input) as f_in, open(args.output, 'w') as f_out:
        for i, line in enumerate(f_in, 1):
            query = json.loads(line)['query']
            print(f"{i}. {query}", flush=True)

            try:
                start = time.time()
                filters, semantic_query = extract_filters(client, query, model_id='zai.glm-4.7')
                elapsed_ms = (time.time() - start) * 1000

                print(f"   {elapsed_ms:.0f}ms", flush=True)
                print(f"    -> {json.dumps({'filters': filters, 'semantic_query': semantic_query})}", flush=True)

                prompt = template.format(query=query)
                output = json.dumps({'filters': filters, 'semantic_query': semantic_query}, separators=(',', ':'))
                
                # Bedrock fine-tuning format
                record = {
                    "schemaVersion": "bedrock-conversation-2024",
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}]
                        },
                        {
                            "role": "assistant",
                            "content": [{"text": output}]
                        }
                    ]
                }
                
                f_out.write(json.dumps(record) + '\n')
                f_out.flush()
            except Exception as e:
                print(f"   Error: {e}", flush=True)

    print(f"\nFine-tuning data saved to {args.output}")


if __name__ == '__main__':
    main()
