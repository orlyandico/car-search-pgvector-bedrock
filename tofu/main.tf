terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# KMS key for encryption across all resources
resource "aws_kms_key" "main" {
  description             = "car-search encryption key"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EnableRootAccountAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudWatchLogs"
        Effect = "Allow"
        Principal = {
          Service = "logs.${var.aws_region}.amazonaws.com"
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"
          }
        }
      }
    ]
  })

  tags = {
    Project = "car-search"
  }
}

resource "aws_kms_alias" "main" {
  name          = "alias/car-search"
  target_key_id = aws_kms_key.main.key_id
}

# VPC and Networking
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name    = "car-search-vpc"
    Project = "car-search"
  }
}

# CKV2_AWS_12: Restrict default security group
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name    = "car-search-default-sg-restricted"
    Project = "car-search"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name    = "car-search-igw"
    Project = "car-search"
  }
}

# CKV_AWS_130: Public subnets do not assign public IP by default;
# EC2 instances use associate_public_ip_address explicitly instead
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name    = "car-search-public-${count.index + 1}"
    Project = "car-search"
  }
}

# Private Subnets (for Aurora and Lambda)
resource "aws_subnet" "private" {
  count             = 3
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 10}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name    = "car-search-private-${count.index + 1}"
    Project = "car-search"
  }
}

# Elastic IP for NAT Gateway
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = {
    Name    = "car-search-nat-eip"
    Project = "car-search"
  }
}

# NAT Gateway
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  tags = {
    Name    = "car-search-nat"
    Project = "car-search"
  }

  depends_on = [aws_internet_gateway.main]
}

# Public Route Table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name    = "car-search-public-rt"
    Project = "car-search"
  }
}

# Private Route Table
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }

  tags = {
    Name    = "car-search-private-rt"
    Project = "car-search"
  }
}

# Route Table Associations
resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Security Group
resource "aws_security_group" "main" {
  name        = "car-search-sg"
  description = "Security group for car-search Aurora and Lambda"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "PostgreSQL from VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block]
  }

  ingress {
    description = "PostgreSQL self-reference"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    self        = true
  }

  ingress {
    description = "HTTPS for VPC endpoints"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    self        = true
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "car-search-sg"
    Project = "car-search"
  }
}

# VPC Endpoints
resource "aws_vpc_endpoint" "bedrock" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.main.id]
  private_dns_enabled = true

  tags = {
    Name    = "car-search-bedrock-endpoint"
    Project = "car-search"
  }
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.main.id]
  private_dns_enabled = true

  tags = {
    Name    = "car-search-secretsmanager-endpoint"
    Project = "car-search"
  }
}

# Aurora Password
resource "random_password" "aurora" {
  length  = 32
  special = false
}

# CKV_AWS_149: Secrets Manager encrypted with KMS CMK
resource "aws_secretsmanager_secret" "db_credentials" {
  name_prefix = "car-search/db-credentials-"
  description = "Aurora PostgreSQL credentials for car-search"
  kms_key_id  = aws_kms_key.main.arn
  recovery_window_in_days = 0

  tags = {
    Project = "car-search"
  }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    host     = aws_rds_cluster.main.endpoint
    port     = 5432
    database = "car_search"
    username = "carapp"
    password = random_password.aurora.result
  })
}

# Aurora Subnet Group
resource "aws_db_subnet_group" "main" {
  name       = "car-search-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name    = "car-search-subnet-group"
    Project = "car-search"
  }
}

# Aurora DB Cluster Parameter Group
resource "aws_rds_cluster_parameter_group" "main" {
  name        = "car-search-cluster-params"
  family      = "aurora-postgresql17"
  description = "Custom parameter group for car-search cluster"

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements,pg_cron"
    apply_method = "pending-reboot"
  }

  parameter {
    name  = "cron.database_name"
    value = "postgres"
  }

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "0"
  }

  tags = {
    Name    = "car-search-cluster-params"
    Project = "car-search"
  }
}

# Aurora IAM Role for Lambda Invocation
resource "aws_iam_role" "aurora_lambda" {
  name = "car-search-aurora-lambda-role"

  lifecycle {
    ignore_changes = [name]
  }

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "rds.amazonaws.com"
      }
      Action = "sts:AssumeRole"
      Condition = {
        StringEquals = {
          "aws:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })

  tags = {
    Project = "car-search"
  }
}

resource "aws_iam_role_policy" "aurora_lambda" {
  name = "car-search-aurora-lambda-policy"
  role = aws_iam_role.aurora_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "lambda:InvokeFunction"
      ]
      Resource = aws_lambda_function.embeddings.arn
    }]
  })
}

# Attach role to Aurora cluster
resource "aws_rds_cluster_role_association" "aurora_lambda" {
  db_cluster_identifier = aws_rds_cluster.main.id
  feature_name          = "Lambda"
  role_arn              = aws_iam_role.aurora_lambda.arn

  depends_on = [aws_iam_role_policy.aurora_lambda]
}

# Aurora Serverless v2 Cluster
resource "aws_rds_cluster" "main" {
  cluster_identifier              = "car-search-cluster"
  engine                          = "aurora-postgresql"
  engine_mode                     = "provisioned"
  engine_version                  = "17.7"
  database_name                   = "car_search"
  master_username                 = "carapp"
  master_password                 = random_password.aurora.result
  db_subnet_group_name            = aws_db_subnet_group.main.name
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.main.name
  vpc_security_group_ids          = [aws_security_group.main.id]
  skip_final_snapshot             = true
  backup_retention_period         = 1
  deletion_protection             = false                         # Demo system - disabled for easy teardown
  copy_tags_to_snapshot           = true                          # CKV_AWS_313
  storage_encrypted               = true                          # CKV_AWS_96
  kms_key_id                      = aws_kms_key.main.arn          # CKV_AWS_327
  iam_database_authentication_enabled = true                      # CKV_AWS_162
  enabled_cloudwatch_logs_exports = ["postgresql"]                 # CKV_AWS_324, CKV2_AWS_27

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 8
  }

  tags = {
    Name    = "car-search-cluster"
    Project = "car-search"
  }
}

# Enhanced monitoring IAM role for RDS
resource "aws_iam_role" "rds_monitoring" {
  name = "car-search-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "monitoring.rds.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Project = "car-search"
  }
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# Aurora Serverless v2 Instance
resource "aws_rds_cluster_instance" "main" {
  identifier         = "car-search-instance"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version
  auto_minor_version_upgrade   = true                                    # CKV_AWS_226
  monitoring_interval           = 60                                     # CKV_AWS_118
  monitoring_role_arn           = aws_iam_role.rds_monitoring.arn         # CKV_AWS_118
  performance_insights_enabled  = true                                   # CKV_AWS_353
  performance_insights_kms_key_id = aws_kms_key.main.arn                 # CKV_AWS_354

  tags = {
    Name    = "car-search-instance"
    Project = "car-search"
  }
}

# Reboot Aurora cluster to apply parameter group changes
# Lambda IAM Role
resource "aws_iam_role" "lambda" {
  name = "car-search-lambda-role"

  lifecycle {
    ignore_changes = [name]
  }

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Project = "car-search"
  }
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_xray" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

resource "aws_iam_role_policy" "lambda_dlq" {
  name = "car-search-lambda-dlq-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sqs:SendMessage"
      Resource = aws_sqs_queue.lambda_dlq.arn
    }]
  })
}

resource "aws_iam_role_policy" "lambda_custom" {
  name = "car-search-lambda-policy"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:*:*:inference-profile/*",
          "arn:aws:bedrock:*::foundation-model/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:ListSecrets"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:car-search/*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = aws_kms_key.main.arn
      }
    ]
  })
}

# SQS Dead Letter Queue for Lambda (CKV_AWS_116)
resource "aws_sqs_queue" "lambda_dlq" {
  name                       = "car-search-embeddings-dlq"
  kms_master_key_id          = aws_kms_key.main.id
  message_retention_seconds  = 1209600 # 14 days

  tags = {
    Project = "car-search"
  }
}

# Lambda code signing (CKV_AWS_272)
resource "aws_signer_signing_profile" "lambda" {
  platform_id = "AWSLambda-SHA384-ECDSA"
  name_prefix = "car_search_"

  tags = {
    Project = "car-search"
  }
}

resource "aws_lambda_code_signing_config" "embeddings" {
  allowed_publishers {
    signing_profile_version_arns = [aws_signer_signing_profile.lambda.version_arn]
  }

  policies {
    untrusted_artifact_on_deployment = "Warn"
  }
}

# Lambda Function (placeholder - will be deployed via script)
resource "aws_lambda_function" "embeddings" {
  function_name = "car-search-embeddings"
  role          = aws_iam_role.lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 15
  memory_size   = 512
  reserved_concurrent_executions = 10    # CKV_AWS_115
  kms_key_arn   = aws_kms_key.main.arn   # CKV_AWS_173
  code_signing_config_arn = aws_lambda_code_signing_config.embeddings.arn  # CKV_AWS_272

  filename         = "${path.module}/lambda_placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_placeholder.zip")

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.main.id]
  }

  dead_letter_config {                   # CKV_AWS_116
    target_arn = aws_sqs_queue.lambda_dlq.arn
  }

  tracing_config {                       # CKV_AWS_50
    mode = "Active"
  }

  environment {
    variables = {
      BEDROCK_MODEL = "global.cohere.embed-v4:0"
    }
  }

  tags = {
    Project = "car-search"
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_vpc,
    aws_iam_role_policy_attachment.lambda_basic,
    aws_vpc_endpoint.bedrock,
    aws_vpc_endpoint.secretsmanager
  ]
}

# SSH Key Pair
resource "aws_key_pair" "loader" {
  key_name   = "car-search-loader"
  public_key = file("~/.ssh/id_rsa.pub")

  tags = {
    Project = "car-search"
  }
}

# EC2 IAM Role
resource "aws_iam_role" "loader" {
  name = "car-search-loader-role"

  lifecycle {
    ignore_changes = [name]
  }

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Project = "car-search"
  }
}

resource "aws_iam_role_policy" "loader" {
  name = "car-search-loader-policy"
  role = aws_iam_role.loader.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:ListSecrets"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:car-search/*"
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = aws_kms_key.main.arn
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.embeddings.arn
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:*:*:inference-profile/*",
          "arn:aws:bedrock:*::foundation-model/*"
        ]
      }
    ]
  })
}

resource "aws_iam_instance_profile" "loader" {
  name = "car-search-loader-profile"
  role = aws_iam_role.loader.name

  tags = {
    Project = "car-search"
  }
}

# ALB Security Group
resource "aws_security_group" "alb" {
  name        = "car-search-alb-sg"
  description = "Security group for Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from CloudFront"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "car-search-alb-sg"
    Project = "car-search"
  }
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# EC2 Security Group
data "http" "my_ip" {
  url = "https://checkip.amazonaws.com"
}

resource "aws_security_group" "loader" {
  name        = "car-search-loader-sg"
  description = "Security group for data loader EC2"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${chomp(data.http.my_ip.response_body)}/32"]
  }

  ingress {
    description = "Flask from ALB"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "car-search-loader-sg"
    Project = "car-search"
  }
}

# EC2 Instance
resource "aws_instance" "loader" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = "r7g.large"
  subnet_id                   = aws_subnet.public[0].id
  vpc_security_group_ids      = [aws_security_group.loader.id, aws_security_group.main.id]
  key_name                    = aws_key_pair.loader.key_name
  iam_instance_profile        = aws_iam_instance_profile.loader.name
  associate_public_ip_address = true       # Needed since map_public_ip_on_launch is now false
  ebs_optimized               = true       # CKV_AWS_135
  monitoring                  = true       # CKV_AWS_126

  metadata_options {                       # CKV_AWS_79: Enforce IMDSv2
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true                     # CKV_AWS_8
    kms_key_id  = aws_kms_key.main.arn
  }

  user_data = <<-EOF
              #!/bin/bash
              dnf update -y
              dnf install -y python3 python3-pip git postgresql15
              pip3 install pandas psycopg2-binary boto3 requests tqdm flask python-dateutil
              
              # Set Bedrock guardrail ID as environment variable
              echo "export BEDROCK_GUARDRAIL_ID=${aws_bedrock_guardrail.main.guardrail_id}" >> /etc/environment
              echo "export BEDROCK_GUARDRAIL_VERSION=${aws_bedrock_guardrail_version.main.version}" >> /etc/environment
              EOF

  tags = {
    Name    = "car-search-loader"
    Project = "car-search"
  }
}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }
}

# Application Load Balancer
resource "aws_lb" "main" {
  name               = "car-search-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  drop_invalid_header_fields = true

  tags = {
    Name    = "car-search-alb"
    Project = "car-search"
  }
}

# Target Group
resource "aws_lb_target_group" "flask" {
  name     = "car-search-flask-tg"
  port     = 5000
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 2
  }

  tags = {
    Name    = "car-search-flask-tg"
    Project = "car-search"
  }
}

# Register EC2 instance with target group
resource "aws_lb_target_group_attachment" "flask" {
  target_group_arn = aws_lb_target_group.flask.arn
  target_id        = aws_instance.loader.id
  port             = 5000
}

# HTTP Listener
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.flask.arn
  }
}

# CloudFront Distribution
resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  comment             = "car-search application"
  default_root_object = ""
  price_class         = "PriceClass_100"
  web_acl_id          = aws_wafv2_web_acl.main.arn

  origin {
    domain_name = aws_lb.main.dns_name
    origin_id   = "alb"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    allowed_methods        = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = true
      headers      = ["Host", "CloudFront-Forwarded-Proto"]

      cookies {
        forward = "all"
      }
    }

    min_ttl     = 0
    default_ttl = 0
    max_ttl     = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  lifecycle {
    ignore_changes = [viewer_certificate[0].minimum_protocol_version]
  }

  tags = {
    Name    = "car-search-cdn"
    Project = "car-search"
  }
}

# WAF Web ACL for rate limiting (CloudFront scope)
resource "aws_wafv2_web_acl" "main" {
  provider = aws.us_east_1
  name     = "car-search-rate-limit"
  scope    = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "global-rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 15
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "GlobalRateLimit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "CarSearchWAF"
    sampled_requests_enabled   = true
  }

  tags = {
    Name    = "car-search-waf"
    Project = "car-search"
  }
}

# Bedrock Guardrail for prompt injection protection
resource "aws_bedrock_guardrail" "main" {
  name                      = "car-search-guardrail"
  blocked_input_messaging   = "Your request was blocked due to security policy."
  blocked_outputs_messaging = "The response was blocked due to security policy."
  description               = "Guardrail for car search application to prevent prompt injection and jailbreak attempts"

  content_policy_config {
    filters_config {
      input_strength  = "HIGH"
      output_strength = "NONE"
      type            = "PROMPT_ATTACK"
    }
  }

  tags = {
    Name    = "car-search-guardrail"
    Project = "car-search"
  }
}

# Create guardrail version
resource "aws_bedrock_guardrail_version" "main" {
  guardrail_arn = aws_bedrock_guardrail.main.guardrail_arn
  description   = "Production version"
}
