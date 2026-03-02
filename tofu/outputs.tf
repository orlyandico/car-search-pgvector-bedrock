output "cloudfront_url" {
  description = "CloudFront distribution URL (HTTPS with valid AWS certificate)"
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.main.dns_name
}

output "alb_url" {
  description = "HTTP URL for the ALB (use CloudFront URL instead)"
  value       = "http://${aws_lb.main.dns_name}"
}

output "bedrock_guardrail_id" {
  description = "Bedrock Guardrail ID for prompt injection protection"
  value       = aws_bedrock_guardrail.main.guardrail_id
}

output "bedrock_guardrail_version" {
  description = "Bedrock Guardrail version"
  value       = aws_bedrock_guardrail_version.main.version
}

output "aurora_endpoint" {
  description = "Aurora cluster endpoint"
  value       = aws_rds_cluster.main.endpoint
}

output "aurora_reader_endpoint" {
  description = "Aurora cluster reader endpoint"
  value       = aws_rds_cluster.main.reader_endpoint
}

output "db_secret_arn" {
  description = "Secrets Manager secret ARN"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.embeddings.function_name
}

output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.main.id
}

output "nat_gateway_id" {
  description = "NAT Gateway ID (can be destroyed after data loading)"
  value       = aws_nat_gateway.main.id
}

output "loader_instance_ip" {
  description = "Public IP of data loader EC2 instance"
  value       = aws_instance.loader.public_ip
}

output "loader_ssh_command" {
  description = "SSH command to connect to loader instance"
  value       = "ssh ec2-user@${aws_instance.loader.public_ip}"
}
