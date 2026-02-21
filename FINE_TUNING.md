# Part 2: Fine-Tuning for Cost Optimisation


## Context: The LLM cost problem at scale

In [Part 1](https://builder.aws.com/content/39t2trPcTmD3eZ9k5zBmmharFoQ/ai-powered-search-for-postgresql-applications), we built a hybrid search system for a PostgreSQL database with 400K vehicle listings. The system used GLM-4.7 to extract structured filters from natural language queries like "German automatic convertible between $5k and $7k", then applies those filters to PostgreSQL whilst using pgvector for semantic ranking.

**The cost challenge**: At 10M searches/day, GLM-4.7's filter extraction costs **$312K/month** ($3.7M/year). This operational cost makes the pattern impractical for production deployment at scale. GLM-4.7-Flash reduces this to $45K/month (86% savings), but fine-tuning can achieve even greater cost reduction. Base models like Amazon Nova Micro were tested but had lower out-of-the-box performance.

**The solution**: Fine-tune Amazon Nova Micro on synthesised training data to replace GLM-4.7. This approach reduces inference costs to **$18.9K/month** (94% savings vs GLM-4.7, 58% savings vs GLM-4.7-Flash) whilst maintaining filter extraction quality.

This article shows how to:
1. Generate or collect training data from production queries
2. Fine-tune Amazon Nova Micro in Bedrock
3. Deploy the model for on-demand inference
4. Test the fine-tuned model against the GLM-4.7 baseline


## Why standard Nova Micro failed

Initial testing with base Nova Micro (before fine-tuning) revealed extraction errors that made it unsuitable for production:

**Critical failures (85% failure rate vs GLM-4.7 baseline):**
- **Price vs mileage confusion**: Interpreted "under 100k miles" as `min_price: 100000` instead of `max_odometer: 100000`
- **Missing structured filters**: Failed to extract vehicle type, fuel type, or manufacturer constraints
- **Field mapping errors**: Mapped "clean title" to `condition` instead of `title_status`
- **Hallucinated filters**: Added spurious filters like `fuel: "other"` or `condition: "excellent"` not present in queries
- **Semantic query errors**: Left `semantic_query` empty or included already-filtered terms

These errors would return completely wrong results (vehicles over budget instead of under, missing critical requirements like fuel type or manufacturer).

**Why GLM-4.7 was used initially:**
- GLM-4.7 correctly extracted filters with 95%+ accuracy out of the box
- No fine-tuning required for production deployment
- Reliable field mapping and value interpretation
- Proper handling of price ranges, mileage constraints, and multi-value filters
- MIT licence permits using outputs as training data for fine-tuning

However, at $312K/month for 10M queries/day, GLM-4.7's operational cost made the pattern impractical at scale. GLM-4.7-Flash offers a middle ground at $45K/month, but fine-tuned Nova Micro achieves the best cost-performance ratio at $18.9K/month.


## Why fine-tuning works for this use case

Filter extraction is a **narrow, well-defined task**:
- Input: Natural language query
- Output: Structured JSON with filters and semantic query
- Schema: Fixed set of 13 filterable fields
- Examples: Abundant (production logs or synthetic generation)

This makes it ideal for fine-tuning a smaller model. GLM-4.7's general capabilities aren't needed - we only need accurate filter extraction for car search queries.

## How fine-tuning fixed Nova Micro

Fine-tuning on 1000 training examples (GLM-4.7's responses to synthetic queries) transformed Nova Micro's performance:

**Improvement: 80% of previously failing queries now pass (95% pass rate vs GLM-4.7)**

**Specific corrections:**
- **Price/mileage disambiguation**: Correctly interprets "under 50k miles" as `max_odometer: 50000` vs "under $50k" as `max_price: 50000`
- **Complete filter extraction**: Captures all relevant manufacturers, fuel types, vehicle types, and drive configurations
- **Accurate field mapping**: Maps "clean title" to `title_status`, "4wd" to `drive`, "coupe" to `type` (not `model`)
- **No hallucinations**: Extracts only filters present in the query
- **Proper semantic queries**: Preserves qualitative terms like "reliable", "luxury", "tow package" for semantic search

**Example transformation:**

Query: `"4wd truck with tow package under $25,000 in good condition"`

**Nova Base (FAIL):**
```json
{
  "filters": {"max_price": 25000, "drive": "4wd", "condition": "good"},
  "semantic_query": "truck with tow package"
}
```
Missing: `type: "truck"` filter (critical structured attribute left in semantic query)

**Nova Fine-tuned (PASS):**
```json
{
  "filters": {"max_price": 25000, "drive": "4wd", "type": "truck", "condition": "good"},
  "semantic_query": "tow package"
}
```
Correctly extracts all structured filters, isolates only "tow package" for semantic search.

Fine-tuning taught Nova Micro the exact schema, field mappings, and extraction logic used by GLM-4.7, achieving equivalent quality at 94% lower cost.

## Approach: Bedrock with Amazon Nova Micro

Fine-tune Amazon Nova Micro 128k in Bedrock and use on-demand inference (no provisioned throughput required).

**Advantages:**
- On-demand pricing (pay per token)
- No infrastructure management
- Integrated with Bedrock API
- Similar cost to fine-tuned open-weights models on SageMaker

**Region availability:**
- **us-east-1**: Nova Micro 128k fine-tuning supported
- **us-west-2**: GLM-4.7, Llama models only (no Nova)
- **eu-west-1, ap-southeast-1**: Limited fine-tuning support

**Important:** 
- S3 bucket and Bedrock job must be in the same region. Use us-east-1 for Nova Micro.
- On-demand deployments for custom models only available in **us-east-1** and **us-west-2**
- Your application must call the deployment in the same region where it was created

**Costs (on-demand inference):**
- Input: $0.035 per 1M tokens (custom model)
- Output: $0.14 per 1M tokens (custom model)
- Monthly hosting: $1.95
- **Monthly cost** (10M queries/day, 1000 input + 200 output tokens): ~$18,902/month
- **Savings vs GLM-4.7**: 94% cost reduction ($312K → $18.9K/month)
- **Savings vs GLM-4.7-Flash**: 58% cost reduction ($45K → $18.9K/month)

**Note:** Fine-tuned Nova Micro on-demand pricing is comparable to running fine-tuned open-weights models (Llama, Mistral) on SageMaker real-time endpoints, but without the infrastructure overhead.

## Training Data Sources

The repository provides two approaches for generating training data. You need 1000-10000 query-response pairs for effective fine-tuning.

### 1. Production query logging (recommended)

The Flask application from Part 1 automatically logs all hybrid search queries to `app/training_data.jsonl`:

- **Format**: JSONL (JSON Lines) - one JSON object per line
- **Thread-safe**: Uses file locking for concurrent writes
- **Contents**: Original query, extracted filters, semantic query, timestamp
- **Location**: `app/training_data.jsonl`

**Example entries**:
```jsonl
{"timestamp": "2026-02-16T13:05:00Z", "query": "german automatic convertible $5k-$7k", "filters": {"manufacturer": ["bmw", "mercedes-benz", "audi"], "transmission": "automatic", "type": "convertible", "min_price": 5000, "max_price": 7000}, "semantic_query": "convertible"}
{"timestamp": "2026-02-16T13:06:15Z", "query": "reliable family suv under 20k", "filters": {"type": "suv", "max_price": 20000}, "semantic_query": "reliable family"}
```

This captures real user queries and GLM-4.7's filter extraction responses, providing high-quality training data that reflects actual usage patterns.

**Why production data is better:**
- Reflects real user language and query patterns
- Includes edge cases and variations not in synthetic data
- Pre-validated by GLM-4.7 (high-quality labels)
- No additional generation cost

**Converting production logs to Bedrock format:**

Logging happens automatically on every hybrid search request, building a dataset of real-world queries and GLM-4.7's responses. After collecting 1000-10000 examples, this data can be used to fine-tune Nova Micro. Production logs need conversion before fine-tuning using the conversion script:


```bash
cd training
python3 convert_production_logs.py --input ../app/training_data.jsonl --output data/finetune_data.jsonl
```

This script:
- Reads production logs from `app/training_data.jsonl`
- Loads the prompt template from `app/filter_prompt.txt`
- Formats each record into Bedrock conversation format
- Outputs to `data/finetune_data.jsonl` ready for fine-tuning

### 2. Synthetic data generation (for bootstrapping)

If you don't have production data yet, generate synthetic training data before deployment:

**Generate synthetic queries** (`training/generate_synthetic_queries.py`):

Creates diverse natural language car search queries using GLM-4.7 4.5 with prompt caching:

```bash
cd training
python3 generate_synthetic_queries.py --num-queries 1000 --output data/synthetic_queries.jsonl
```

Parameters:
- `--num-queries`: Number of queries to generate (default: 1000)
- `--output`: Output file path (default: data/synthetic_queries.jsonl)

Features:
- Generates 20 queries per batch for maximum diversity
- Prompt caching is not used, as the prompt is under 1024 tokens
- Displays cache statistics and token usage per batch
- Temperature 1.0 for varied outputs
- Writes queries incrementally (safe to interrupt)

Generates queries covering:
- Mixed structured filters (price, year, manufacturer, odometer, drive, condition, etc.) and unstructured features (sunroof, leather)
- Natural conversational language ("I need", "looking for", direct descriptions)
- Varying complexity (simple: "cheap honda", complex: "german diesel automatic suv under $20k with low miles")
- Regional terms ("german" = BMW/Mercedes/Audi, "japanese" = Toyota/Honda/Nissan, "american" = Ford/Chevy/Dodge)
- Price formats ($5k, $5000, "under 10k", "between 15 and 20 thousand")
- Common features (sunroof, leather seats, backup camera, third row, tow package, heated seats)
- Condition/quality terms (reliable, fuel efficient, low miles, well maintained, clean title)
- Specificity variations (specific model vs general type)

**Process queries through GLM-4.7** (`training/generate_finetune_data.py`):

Runs synthetic queries through the exact filter extraction logic used by the application:

```bash
cd training
python3 generate_finetune_data.py --input data/synthetic_queries.jsonl --output data/finetune_data.jsonl
```

Parameters:
- `--input`: Input queries file (default: data/synthetic_queries.jsonl)
- `--output`: Output training data file (default: data/finetune_data.jsonl)

Features:
- Uses exact prompt from `app/filter_prompt.txt` (same as production)
- Displays cache hit ratio and latency per query
- Outputs JSONL with query, extracted filters, and semantic query
- Thread-safe for concurrent processing

**Training data format**:
```jsonl
{
  "schemaVersion": "bedrock-conversation-2024",
  "messages": [
    {
      "role": "user",
      "content": [{"text": "Extract filters from: german automatic convertible $5k-$7k"}]
    },
    {
      "role": "assistant",
      "content": [{"text": "{\"filters\":{\"manufacturer\":[\"bmw\",\"mercedes-benz\",\"audi\"],\"transmission\":\"automatic\",\"type\":\"convertible\",\"min_price\":5000,\"max_price\":7000},\"semantic_query\":\"convertible\"}"}]
    }
  ]
}
```

The `generate_finetune_data.py` script automatically formats data in this structure, using the exact prompt template from `app/filter_prompt.txt` as the user message and GLM-4.7's JSON response as the assistant message.

## Directory Structure

```
training/
├── finetune.sh                     # Automated fine-tuning script
├── synthetic_query_prompt.txt      # Shared prompt template for query generation
├── generate_synthetic_queries.py   # Creates diverse car search queries via GLM-4.7
├── generate_finetune_data.py       # Processes queries through filter extraction
├── convert_production_logs.py      # Converts production logs to Bedrock format
├── test_fine_tuning.py             # Tests fine-tuned model against GLM-4.7 baseline
└── data/
    ├── synthetic_queries.jsonl     # Generated queries (input)
    └── finetune_data.jsonl         # Training data (Bedrock format)
```

## Fine-Tuning Workflow

**1. Generate training data**:

Use production data or synthetic data:

**Option A: Use production data** (recommended after deployment):
```bash
# Production queries automatically logged to app/training_data.jsonl
wc -l app/training_data.jsonl

# Convert to Bedrock format
cd training
python3 convert_production_logs.py --input ../app/training_data.jsonl --output data/finetune_data.jsonl
```

**Option B: Generate synthetic data** (for bootstrapping):
```bash
# Generate 1000 synthetic queries (20 per batch with prompt caching)
cd training
python3 generate_synthetic_queries.py --num-queries 1000

# Process through GLM-4.7 to create training pairs
python3 generate_finetune_data.py
```

**2. Run fine-tuning script**:

```bash
cd training
./finetune.sh my-bucket-name us-east-1
```

The script automatically:
- Validates region supports Nova Micro fine-tuning
- Checks S3 bucket region matches job region
- Creates S3 bucket in correct region (if needed)
- Uploads training data (uses sync to avoid re-uploads)
- Creates/updates IAM role with S3 permissions
- Adds S3 bucket policy for Bedrock service access
- Starts Bedrock fine-tuning job
- Prints status check command and model ARN

**Region requirements:**
- Nova Micro 128k fine-tuning only available in us-east-1
- S3 bucket must be in same region as fine-tuning job
- Script validates both requirements before starting

**Script usage:**
```bash
./finetune.sh [bucket-name] [region]

# Examples
./finetune.sh my-bucket us-east-1              # Specify bucket and region
```

**3. Check job status**:

```bash
aws bedrock get-model-customization-job --region us-east-1 --job-identifier filter-extraction-nova-TIMESTAMP
```

Replace `TIMESTAMP` with the value from the script output. Fine-tuning takes 2-4 hours.

**4. Create on-demand deployment**:

After the fine-tuning job completes (status: `Completed`), create an on-demand deployment (requires AWS CLI 2.33+):

```bash
# Check CLI version
aws --version  # Must be 2.33.0 or higher

# Get the custom model ARN from the job output
MODEL_ARN=$(aws bedrock get-model-customization-job \
  --region us-east-1 \
  --job-identifier filter-extraction-nova-TIMESTAMP \
  --query 'outputModelArn' \
  --output text)

# Create deployment
aws bedrock create-custom-model-deployment \
  --region us-east-1 \
  --model-deployment-name filter-extraction-nova \
  --model-arn $MODEL_ARN

# Get deployment ARN (wait ~1 minute for deployment to become Active)
aws bedrock list-custom-model-deployments \
  --region us-east-1 \
  --query 'customModelDeployments[?modelArn==`'$MODEL_ARN'`].customModelDeploymentArn' \
  --output text
```

Save the deployment ARN - you'll need it for inference.

**5. Test fine-tuned model**:

After the deployment is active, test the model against the GLM-4.7 baseline:

```bash
cd training

# Update NOVA_FINETUNED_ARN in test_fine_tuning.py with your deployment ARN, or:
python3 test_fine_tuning.py --finetuned-arn arn:aws:bedrock:us-east-1:ACCOUNT:custom-model-deployment/NAME --output test_results.csv
```

This script:
- Generates 20 diverse synthetic queries using GLM-4.7
- Tests each query against three models:
  - **GLM-4.7 4.5** (baseline - what we're replacing)
  - **Nova Micro base** (before fine-tuning - to measure baseline capability)
  - **Nova Micro fine-tuned** (after fine-tuning - to measure improvement)
- Uses **GLM-4.7 as LLM-as-judge** to compare outputs
- Provides two pass/fail verdicts per query:
  - Nova Base vs GLM-4.7 (shows baseline Nova capability)
  - Nova Fine-tuned vs GLM-4.7 (shows fine-tuning improvement)
- Generates CSV report with columns: query, glm_output, nova_base_output, nova_finetuned_output, analysis, nova_base_verdict, nova_finetuned_verdict
- Displays summary statistics showing improvement from fine-tuning

The script uses `extract_filters()` from `llm_utils.py` for all three models, ensuring identical prompt logic.

**Output:**
- Console: Real-time progress with detailed three-way comparison for each query
- CSV file: Complete results for analysis (default: test_results.csv)
- Summary: Pass/fail statistics for both comparisons plus improvement metric

**Example output:**

```
=== Query 4/20 ===
Query: 4wd truck with tow package under 25k, clean title preferred

Calling GLM-4.7 baseline...
GLM-4.7: {"filters": {"max_price": 25000, "drive": "4wd", "type": "truck", "title_status": "clean"}, "semantic_query": "tow package"}

Calling Nova Micro base (before fine-tuning)...
Nova Base: {"filters": {"min_price": 25000, "drive": "4wd", "condition": "clean", "type": "truck"}, "semantic_query": "tow package"}

Calling Nova Micro fine-tuned...
Nova Fine-tuned: {"filters": {"max_price": 25000, "drive": "4wd", "type": "truck", "title_status": "clean"}, "semantic_query": "tow package"}

Comparing outputs with GLM-4.7...
Analysis: All three outputs are valid JSON. The Nova base model made two critical errors: it extracted "min_price" instead of "max_price" (reversing the user's intent for a budget constraint) and mapped "clean title" to a "condition" filter instead of "title_status". The Nova fine-tuned model corrects both errors and produces output identical to the GLM-4.7 baseline.

Nova Base vs GLM-4.7: FAIL - Nova base critically misinterprets "under 25k" as min_price instead of max_price, which would return completely wrong results (vehicles over $25k instead of under). It also incorrectly maps "clean title" to the "condition" field instead of "title_status".

Nova Fine-tuned vs GLM-4.7: PASS - Nova fine-tuned produces identical output to GLM-4.7, correctly extracting max_price: 25000, title_status: "clean", and all other filters with proper field names and values.
```

This example shows how fine-tuning corrects critical errors in the base model, transforming a query that would return wrong results into one that matches the baseline quality.

**Why three models?**
- GLM-4.7 baseline shows the quality bar we need to match
- Nova base shows whether the model can learn the task at all
- Nova fine-tuned shows the improvement from fine-tuning
- Comparing both helps validate that improvements come from fine-tuning, not just model selection

**6. Switch application to use fine-tuned model**:

After validating the fine-tuned model's quality, update the Flask application to use it:

```bash
# Set environment variable with deployment ARN
export FILTER_MODEL_ID="arn:aws:bedrock:us-east-1:ACCOUNT:custom-model-deployment/filter-extraction-nova"

# Restart application
cd app
python3 app.py
```

The application automatically uses the model specified in `FILTER_MODEL_ID` environment variable. The `llm_utils.py` module already supports custom model deployments via the Converse API.

**Alternative: Update filter_prompt.txt**:

You can also set the default model in `app/filter_prompt.txt`:

```
# Model: arn:aws:bedrock:us-east-1:ACCOUNT:custom-model-deployment/filter-extraction-nova

Extract structured filters from this car search query...
```

This makes the fine-tuned model the default without requiring environment variables.

**Important**: Ensure your application's Bedrock client uses `region_name='us-east-1'` to match the deployment region.

**7. Monitor and iterate**:

- Continue logging production queries to `app/training_data.jsonl`
- Periodically retrain with new data (every 3-6 months or when quality degrades)
- Monitor filter extraction accuracy and user feedback
- Compare costs: Nova deployment vs GLM-4.7 baseline

## Cost Analysis
## Cost Analysis

**Fine-tuning costs** (one-time):
- Bedrock Nova Micro 128k: ~$1.60 for 1000 examples

**Inference costs** (monthly at 10M queries/day, 200 input + 100 output tokens):
- **Bedrock Nova Micro on-demand**: $18,902/month
- **GLM-4.7 on-demand**: $312,000/month

**Savings**: 94% cheaper than GLM-4.7


## Expected Results

- **Cost reduction**: 94% cheaper than GLM-4.7
- **Latency**: Similar or faster (smaller model, optimised inference)
- **Quality**: 95%+ extraction accuracy with sufficient training data (1000+ examples)
- **Maintenance**: Retrain periodically with new production queries to handle evolving patterns


## IAM Permissions

The `finetune.sh` script automatically creates:

1. **IAM role** with S3 permissions for Bedrock
2. **S3 bucket policy** allowing Bedrock service access

Both are required for fine-tuning jobs.

**Manual setup** (if needed):

Create a Bedrock execution role with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket",
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket/*",
        "arn:aws:s3:::your-bucket"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:CreateModelCustomizationJob",
        "bedrock:GetModelCustomizationJob",
        "bedrock:InvokeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

Trust relationship:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

**S3 bucket policy** (also required):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket/*",
        "arn:aws:s3:::your-bucket"
      ],
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "ACCOUNT_ID"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:us-east-1:ACCOUNT_ID:model-customization-job/*"
        }
      }
    },
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::your-bucket/output/*",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "ACCOUNT_ID"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:us-east-1:ACCOUNT_ID:model-customization-job/*"
        }
      }
    }
  ]
}
```


## Summary

This article demonstrated how to reduce LLM inference costs by 94% through fine-tuning:

1. **Problem**: GLM-4.7 costs $312K/month for filter extraction at 10M queries/day
2. **Solution**: Fine-tune Amazon Nova Micro on production or synthetic training data
3. **Result**: $18.9K/month with equivalent quality (95%+ accuracy)


**Key takeaways**:
- Fine-tuning works well for narrow, well-defined tasks like filter extraction
- Production data provides better training quality than synthetic data
- On-demand deployment eliminates infrastructure management overhead
- Regular retraining with new production queries maintains quality over time


For the complete implementation including the hybrid search system, see [Part 1: AI-powered search for PostgreSQL applications](https://builder.aws.com/content/39t2trPcTmD3eZ9k5zBmmharFoQ/ai-powered-search-for-postgresql-applications).

## References

- [Bedrock Model Customization](https://docs.aws.amazon.com/bedrock/latest/userguide/custom-models.html)
- [Amazon Nova Models](https://docs.aws.amazon.com/bedrock/latest/userguide/nova-models.html)
