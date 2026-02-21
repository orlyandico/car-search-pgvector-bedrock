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

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

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

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name    = "car-search-igw"
    Project = "car-search"
  }
}

# Public Subnets (for NAT Gateway)
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

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

# Secrets Manager Secret
resource "aws_secretsmanager_secret" "db_credentials" {
  name        = "car-search/db-credentials"
  description = "Aurora PostgreSQL credentials for car-search"

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

  tags = {
    Name    = "car-search-cluster-params"
    Project = "car-search"
  }
}

# Aurora IAM Role for Lambda Invocation
resource "aws_iam_role" "aurora_lambda" {
  name = "car-search-aurora-lambda-role"

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

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 8
  }

  tags = {
    Name    = "car-search-cluster"
    Project = "car-search"
  }
}

# Aurora Serverless v2 Instance
resource "aws_rds_cluster_instance" "main" {
  identifier         = "car-search-instance"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version

  tags = {
    Name    = "car-search-instance"
    Project = "car-search"
  }
}

# Reboot Aurora cluster to apply parameter group changes
resource "null_resource" "reboot_cluster" {
  triggers = {
    parameter_group = aws_rds_cluster_parameter_group.main.id
  }

  provisioner "local-exec" {
    command = "aws rds reboot-db-cluster --db-cluster-identifier ${aws_rds_cluster.main.cluster_identifier} --region ${var.aws_region} || true"
  }

  depends_on = [
    aws_rds_cluster.main,
    aws_rds_cluster_instance.main
  ]
}

# Lambda IAM Role
resource "aws_iam_role" "lambda" {
  name = "car-search-lambda-role"

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
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:car-search/*"
      }
    ]
  })
}

# Lambda Function (placeholder - will be deployed via script)
resource "aws_lambda_function" "embeddings" {
  function_name = "car-search-embeddings"
  role          = aws_iam_role.lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12"
  timeout       = 900
  memory_size   = 512

  filename         = "${path.module}/lambda_placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_placeholder.zip")

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.main.id]
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
resource "tls_private_key" "loader" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "loader" {
  key_name   = "car-search-loader"
  public_key = tls_private_key.loader.public_key_openssh

  tags = {
    Project = "car-search"
  }
}

resource "local_file" "private_key" {
  content         = tls_private_key.loader.private_key_pem
  filename        = "${path.module}/car-search-loader.pem"
  file_permission = "0400"
}

# EC2 IAM Role
resource "aws_iam_role" "loader" {
  name = "car-search-loader-role"

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
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:car-search/*"
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
    description = "Flask app from my IP"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["${chomp(data.http.my_ip.response_body)}/32"]
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
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = "r7g.large"
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.loader.id, aws_security_group.main.id]
  key_name               = aws_key_pair.loader.key_name
  iam_instance_profile   = aws_iam_instance_profile.loader.name

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
  }

  user_data = <<-EOF
              #!/bin/bash
              dnf update -y
              dnf install -y python3 python3-pip git postgresql15
              pip3 install pandas psycopg2-binary boto3 requests tqdm flask python-dateutil
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
