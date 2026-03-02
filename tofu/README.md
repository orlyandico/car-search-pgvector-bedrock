# Car Search Infrastructure

Terraform configuration for car-search demo application.

## Architecture

- **VPC**: 10.0.0.0/16 with public and private subnets
- **Aurora Serverless v2**: PostgreSQL 17.7 (0.5-8 ACU) in private subnets
- **Lambda**: In private subnets with VPC endpoints
- **NAT Gateway**: For data loading (can be destroyed after)
- **VPC Endpoints**: Bedrock Runtime, Secrets Manager

## Prerequisites

- Terraform >= 1.0
- AWS CLI configured
- Python 3.12+

## Deployment

### 1. Initialize Terraform

```bash
cd terraform
terraform init
```

### 2. Deploy Infrastructure

```bash
terraform apply
```

This creates:
- VPC with public/private subnets
- Aurora Serverless v2 cluster
- Lambda function (placeholder)
- VPC endpoints
- NAT Gateway
- Security groups

### 3. Deploy Lambda Code

```bash
cd ..
python3 scripts/setup_lambda.py
```

This updates the Lambda function with actual code.

### 4. Load Data

The NAT Gateway allows data loading from your local machine:

```bash
python3 scripts/download_dataset.py
python3 scripts/load_data.py
```

### 5. Generate Embeddings

```bash
python3 scripts/generate_embeddings.py
```

### 6. (Optional) Destroy NAT Gateway

After data loading, you can destroy the NAT Gateway to save costs (~$0.045/hour):

```bash
terraform destroy -target=aws_nat_gateway.main -target=aws_eip.nat
```

Note: This will break data loading but Lambda will still work via VPC endpoints.

## Outputs

```bash
terraform output
```

Shows:
- Aurora endpoint
- Lambda function name
- VPC and subnet IDs
- Security group ID

## Teardown

```bash
terraform destroy
```

**Note**: Secrets Manager has a 30-day recovery window by default. This configuration uses `name_prefix` for the database credentials secret to avoid conflicts on repeated deployments. The `recovery_window_in_days = 0` setting forces immediate deletion on destroy.

## Cost Estimate

4-hour demo:
- Aurora Serverless v2 (0.5 ACU avg): ~$0.06
- NAT Gateway: ~$0.18
- VPC Endpoints (2): ~$0.08
- Bedrock embeddings (400K): ~$8.00
- **Total: ~$8.32**

Without NAT Gateway (after data loading): ~$8.14
