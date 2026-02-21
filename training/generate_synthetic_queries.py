#!/usr/bin/env python3
import boto3
import json
import argparse
import os

def load_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), 'synthetic_query_prompt.txt')
    with open(prompt_path) as f:
        return f.read().strip()

def main():
    parser = argparse.ArgumentParser(description='Generate synthetic car search queries')
    parser.add_argument('--num-queries', type=int, default=1000, help='Number of queries to generate (default: 1000)')
    parser.add_argument('--output', default='data/synthetic_queries.jsonl', help='Output file path')
    args = parser.parse_args()

    # Create output directory if needed
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    print(f"Generating {args.num_queries} synthetic queries...")

    client = boto3.client('bedrock-runtime', region_name='us-east-1')
    prompt = load_prompt()

    # Write to JSONL with immediate flush
    with open(args.output, 'w') as f:
        queries = []
        batch_num = 0

        while len(queries) < args.num_queries:
            batch_num += 1
            print(f"Batch {batch_num} (total: {len(queries)}/{args.num_queries})...", flush=True)

            response = client.invoke_model(
                modelId='zai.glm-4.7',
                contentType='application/json',
                body=json.dumps({

                    'max_tokens': 1000,
                    'temperature': 1.0,
                    'messages': [{'role': 'user', 'content': prompt}]

                })
            )

            result = json.loads(response['body'].read())
            response_text = result['choices'][0]['message']['content'].strip()

            # Parse JSON array
            try:
                if response_text.startswith('```'):
                    response_text = response_text.split('```')[1]
                    if response_text.startswith('json'):
                        response_text = response_text[4:]
                    response_text = response_text.strip()

                batch_queries = json.loads(response_text)

                for query in batch_queries:
                    if len(queries) >= args.num_queries:
                        break
                    queries.append(query)
                    f.write(json.dumps({'query': query}) + '\n')
                    f.flush()

                # Show token usage
                usage = result.get('usage', {})
                input_tokens = usage.get('prompt_tokens', 0)
                output_tokens = usage.get('completion_tokens', 0)

            except Exception as e:
                print(f"  Failed to parse: {e}", flush=True)
                continue

    print(f"\nGenerated {len(queries)} queries")
    print(f"Saved to {args.output}")

    # Show sample
    print("\nSample queries:")
    for q in queries[:10]:
        print(f"  - {q}")

if __name__ == '__main__':
    main()
