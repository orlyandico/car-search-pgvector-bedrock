#!/bin/bash
set -e

# Configuration
BUCKET_NAME="${1:-car-search-finetuning}"
REGION="${2:-$(aws configure get region || echo 'us-west-2')}"
ROLE_NAME="BedrockFineTuningRole"
JOB_NAME="filter-extraction-nova-$(date +%Y%m%d-%H%M%S)"
MODEL_NAME="filter-extraction-nova"
TRAINING_DATA="data/finetune_data.jsonl"

# Get AWS account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "==> Configuration"
echo "Account ID: $ACCOUNT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo "Job name: $JOB_NAME"
echo ""

# Check Nova Micro availability
echo "==> Checking Nova Micro 128k availability in $REGION"
if ! aws bedrock list-foundation-models --region $REGION --query 'modelSummaries[?modelId==`amazon.nova-micro-v1:0:128k`]' --output text | grep -q nova; then
    echo "Error: amazon.nova-micro-v1:0:128k not available in $REGION"
    echo ""
    echo "Available models with FINE_TUNING support:"
    aws bedrock list-foundation-models --region $REGION --query 'modelSummaries[?contains(customizationsSupported, `FINE_TUNING`)].{ModelId:modelId, Name:modelName}' --output table
    echo ""
    echo "Try a different region: ./finetune.sh $BUCKET_NAME us-east-1"
    exit 1
fi

# Check training data exists
if [ ! -f "$TRAINING_DATA" ]; then
    echo "Error: Training data not found at $TRAINING_DATA"
    echo "Run: python3 generate_finetune_data.py"
    exit 1
fi

echo "==> Creating S3 bucket (if needed)"
if aws s3api head-bucket --bucket $BUCKET_NAME 2>/dev/null; then
    BUCKET_REGION=$(aws s3api get-bucket-location --bucket $BUCKET_NAME --query LocationConstraint --output text)
    # us-east-1 returns "None" for LocationConstraint
    [ "$BUCKET_REGION" = "None" ] && BUCKET_REGION="us-east-1"
    
    if [ "$BUCKET_REGION" != "$REGION" ]; then
        echo "Error: Bucket $BUCKET_NAME is in $BUCKET_REGION but job is in $REGION"
        echo "Bucket and fine-tuning job must be in the same region"
        echo ""
        echo "Options:"
        echo "  1. Use bucket's region: ./finetune.sh $BUCKET_NAME $BUCKET_REGION"
        echo "  2. Create new bucket: ./finetune.sh ${BUCKET_NAME}-${REGION} $REGION"
        exit 1
    fi
    echo "Bucket exists in $REGION"
else
    echo "Creating bucket in $REGION"
    if [ "$REGION" = "us-east-1" ]; then
        aws s3 mb s3://$BUCKET_NAME
    else
        aws s3 mb s3://$BUCKET_NAME --region $REGION
    fi
fi

echo "==> Uploading training data"
aws s3 sync data/ s3://$BUCKET_NAME/training/ --exclude "*" --include "finetune_data.jsonl"

echo "==> Creating IAM role (if needed)"
cat > /tmp/trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF

if aws iam get-role --role-name $ROLE_NAME &>/dev/null; then
    echo "Role $ROLE_NAME already exists, updating policies"
else
    echo "Creating role $ROLE_NAME"
    aws iam create-role \
      --role-name $ROLE_NAME \
      --assume-role-policy-document file:///tmp/trust-policy.json
fi

cat > /tmp/s3-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::$BUCKET_NAME/*",
        "arn:aws:s3:::$BUCKET_NAME"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::$BUCKET_NAME/output/*"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name S3Access \
  --policy-document file:///tmp/s3-policy.json

echo "==> Adding S3 bucket policy for Bedrock"
cat > /tmp/bucket-policy.json << EOF
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
        "arn:aws:s3:::$BUCKET_NAME/*",
        "arn:aws:s3:::$BUCKET_NAME"
      ],
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "$ACCOUNT_ID"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:$REGION:$ACCOUNT_ID:model-customization-job/*"
        }
      }
    },
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::$BUCKET_NAME/output/*",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "$ACCOUNT_ID"
        },
        "ArnLike": {
          "aws:SourceArn": "arn:aws:bedrock:$REGION:$ACCOUNT_ID:model-customization-job/*"
        }
      }
    }
  ]
}
EOF

aws s3api put-bucket-policy \
  --bucket $BUCKET_NAME \
  --policy file:///tmp/bucket-policy.json

# Wait for role to propagate
echo "==> Waiting for IAM role to propagate (30s)"
sleep 30

echo "==> Starting fine-tuning job"
ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"

aws bedrock create-model-customization-job \
  --region $REGION \
  --job-name $JOB_NAME \
  --custom-model-name $MODEL_NAME \
  --role-arn $ROLE_ARN \
  --base-model-identifier amazon.nova-micro-v1:0:128k \
  --training-data-config s3Uri=s3://$BUCKET_NAME/training/finetune_data.jsonl \
  --output-data-config s3Uri=s3://$BUCKET_NAME/output/ \
  --hyper-parameters epochCount=3

echo ""
echo "==> Fine-tuning job started: $JOB_NAME"
echo ""
echo "Check status:"
echo "  aws bedrock get-model-customization-job --region $REGION --job-identifier $JOB_NAME"
echo ""
echo "Model ARN (after completion):"
echo "  arn:aws:bedrock:$REGION:$ACCOUNT_ID:custom-model/$MODEL_NAME"
echo ""
echo "Usage:"
echo "  ./finetune.sh [bucket-name] [region]"
echo "  Example: ./finetune.sh my-bucket us-east-1"
