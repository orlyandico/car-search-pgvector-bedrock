# Threat Model: AI-Powered Vehicle Search Application

**Date**: 27 February 2026  
**System**: Car Search with pgvector and Amazon Bedrock  
**Classification**: Public Demo Application  
**Criticality**: Low

## Executive Summary

This threat model analyses the security posture of an AI-powered semantic search application built on PostgreSQL with Amazon Bedrock integration. The system demonstrates adding vector search capabilities to existing PostgreSQL applications, handling 400K vehicle listings with hybrid search combining traditional SQL, full-text search, and semantic vector similarity.

**Key Findings**:

- 8 threats identified across Information Disclosure, Denial of Service, Tampering, and Elevation of Privilege categories
- 9 mitigations implemented or identified, with 7 already deployed
- High-severity threats around API cost escalation and database access are mitigated through rate limiting, IAM policies, and network isolation
- Prompt injection risks addressed via Bedrock Guardrails with HIGH strength filtering
- SQL injection prevented through parameterised queries

**Risk Level**: Medium (acceptable for demo application with implemented controls)

## System Overview

### Business Context

**Purpose**: Demonstrate AI-powered search capabilities for PostgreSQL applications without rebuilding infrastructure

**Key Characteristics**:
- Industry: Technology
- Data Sensitivity: Internal (vehicle listings from public Kaggle dataset)
- User Base: Small (demo/prototype)
- Geographic Scope: Global
- Deployment: AWS Cloud (Public)
- Authentication: None (public access)
- System Criticality: Low
- Financial Impact: Minimal
- Regulatory Requirements: None

### Architecture Components

**Frontend & CDN**:
- CloudFront Distribution (C001): HTTPS termination, TLS 1.2 minimum, AWS-provided certificate
- Application Load Balancer (C003): HTTP only, restricted to CloudFront IP ranges

**Compute**:
- Flask Application (C004): EC2 r7g.large, Python 3.12, port 5000
- Lambda Embeddings Function (C007): Python 3.12, private subnet, 512MB memory, 15s timeout, reserved concurrency 10

**Data Storage**:
- Aurora PostgreSQL (C005): Serverless v2, PostgreSQL 17.7, private subnet, pgvector extension, 400K listings, KMS encryption

**Security Services**:
- AWS WAF (C002): Rate limiting 15 requests/minute per IP
- Bedrock Guardrails (C006): PROMPT_ATTACK filter at HIGH strength
- Secrets Manager (C008): KMS-encrypted credentials, VPC endpoint access

**Network**:
- VPC Endpoints (C009): Bedrock Runtime and Secrets Manager in private subnets

**AI Services**:
- Bedrock Runtime (C010): GLM-4.7 for query parsing, Cohere Embed v4 for embeddings

### Data Flow

1. User → CloudFront (HTTPS) → ALB (HTTP) → Flask App
2. Flask App → Bedrock Runtime (via VPC endpoint) for LLM query parsing and embeddings
3. Flask App → Aurora PostgreSQL for data retrieval and vector similarity search
4. Lambda → Bedrock Runtime (via VPC endpoint) for batch embedding generation
5. Lambda → Aurora PostgreSQL for embedding storage

## Threat Analysis

### T1: Prompt Injection Attack

**Threat ID**: 89d08514-5c12-4f8e-8497-6db9bc2e64ea  
**Category**: Information Disclosure  
**Severity**: Medium  
**Likelihood**: Possible

**Description**:  
External attacker with network access to Flask application injects malicious prompts to extract training data or manipulate LLM responses.

**Impact**:  
Exposure of training data patterns, manipulation of search results.

**Affected Components**: Flask Application (C004)

**Mitigation**:  
✅ **Implemented**: Bedrock Guardrails with PROMPT_ATTACK filter at HIGH strength  
- Configured in tofu/main.tf
- Referenced in app.py via environment variables
- Blocks malicious prompts before reaching LLM

**Status**: Mitigated

---

### T2: Training Data Exposure

**Threat ID**: c64ef107-4df8-4434-9519-e3f3b5c2eab4  
**Category**: Information Disclosure  
**Severity**: Low  
**Likelihood**: Possible

**Description**:  
Malicious insider with access to training_data.jsonl file reads user queries and LLM responses.

**Impact**:  
Exposure of user search patterns and system behaviour.

**Affected Components**: Flask Application (C004)

**Mitigation**:  
⚠️ **Identified**: File system permissions restricting access to training_data.jsonl  
- Set file permissions to 600 (owner read/write only)
- Ensure proper EC2 instance access controls
- Consider encrypting training data at rest

**Status**: Requires implementation

---

### T3: Database Credential Theft

**Threat ID**: f80787c9-28bc-462a-b893-ff727ca9986c  
**Category**: Information Disclosure  
**Severity**: High  
**Likelihood**: Unlikely

**Description**:  
Malicious insider with access to Secrets Manager retrieves database credentials.

**Impact**:  
Full database access and data exfiltration of 400K vehicle listings.

**Affected Components**: Secrets Manager (C008)

**Mitigation**:  
✅ **Implemented**: IAM policies restricting Secrets Manager access to authorised principals only  
- Lambda and EC2 IAM roles with least privilege
- VPC endpoint access only (no public internet access)
- KMS encryption for secrets at rest

**Status**: Mitigated

---

### T4: Database Data Exfiltration

**Threat ID**: 6bbdb2aa-5ebe-4d21-a332-6d163b336768  
**Category**: Information Disclosure  
**Severity**: High  
**Likelihood**: Possible

**Description**:  
Malicious insider with database access credentials extracts vehicle listing data and embeddings from Aurora database.

**Impact**:  
Exposure of 400K vehicle listings and proprietary embedding data.

**Affected Components**: Aurora PostgreSQL (C005)

**Mitigation**:  
✅ **Implemented**: Network isolation with private subnets and security groups  
- Aurora in private subnets with no public access
- Security group allows only VPC traffic on port 5432
- IAM database authentication enabled
- Encryption at rest with KMS CMK

**Status**: Mitigated

---

### T5: API Cost Escalation Attack

**Threat ID**: 8e92602e-3983-4d0f-9492-9cbff837a18b  
**Category**: Denial of Service  
**Severity**: High  
**Likelihood**: Likely

**Description**:  
External attacker with internet access sends high volume of requests to exhaust Bedrock API quota and incur excessive costs.

**Impact**:  
Service unavailability and uncontrolled API costs (GLM-4.7 costs $0.60/$2.20 per 1M tokens).

**Affected Components**: AWS WAF (C002), Flask Application (C004)

**Mitigations**:  
✅ **Implemented**: AWS WAF rate limiting at 15 requests/minute per IP  
- Attached to CloudFront distribution
- Blocks excessive requests before reaching application

✅ **Implemented**: Lambda reserved concurrency limit of 10  
- Configured in tofu/main.tf
- Prevents runaway Lambda costs

⚠️ **Identified**: CloudWatch monitoring and alerting for abnormal request patterns  
- Configure alarms for WAF blocked requests
- Monitor Lambda invocation spikes
- Alert on Bedrock API throttling

**Status**: Partially mitigated (monitoring recommended)

---

### T6: SQL Injection

**Threat ID**: 235a1acb-3f42-463d-9737-b604a0336639  
**Category**: Tampering  
**Severity**: Medium  
**Likelihood**: Possible

**Description**:  
External attacker with network access injects SQL through search parameters.

**Impact**:  
Unauthorised database access or data modification.

**Affected Components**: Flask Application (C004)

**Mitigation**:  
✅ **Implemented**: Parameterised SQL queries using psycopg2 with %s placeholders  
- All database queries in app.py use parameterised queries
- No string concatenation for SQL construction
- Prevents SQL injection attacks

**Status**: Mitigated

---

### T7: Lambda Privilege Escalation

**Threat ID**: c0b57ca1-e2f3-4fbc-98cb-a24d85caddaa  
**Category**: Elevation of Privilege  
**Severity**: Medium  
**Likelihood**: Possible

**Description**:  
Malicious insider with Lambda execution role exploits Lambda function to access Bedrock or database beyond intended scope.

**Impact**:  
Unauthorised access to AWS services or data.

**Affected Components**: Lambda Embeddings Function (C007)

**Mitigation**:  
✅ **Implemented**: Least privilege IAM roles for Lambda with specific resource ARNs  
- Lambda IAM role grants access only to specific Bedrock models
- Specific Secrets Manager secret ARN access only
- No wildcard permissions

**Status**: Mitigated

---

### T8: WAF Bypass via Distributed Attack

**Threat ID**: d412f017-e359-45db-b034-b2aaa5039b20  
**Category**: Denial of Service  
**Severity**: Medium  
**Likelihood**: Possible

**Description**:  
External attacker with internet access bypasses WAF rate limiting through distributed attack or IP rotation.

**Impact**:  
Service degradation and increased costs.

**Affected Components**: CloudFront Distribution (C001), Application Load Balancer (C003)

**Mitigation**:  
✅ **Implemented**: AWS WAF rate limiting at 15 requests/minute per IP  
- Global rate limit across all source IPs
- Automatic blocking of IPs exceeding limit

**Additional Recommendations**:
- Consider AWS Shield Standard (included by default)
- Monitor CloudWatch metrics for blocked requests
- Implement CAPTCHA for suspicious traffic patterns

**Status**: Mitigated (with monitoring recommended)

## Security Controls Summary

### Implemented Controls

1. **Network Security**:
   - Private subnets for Aurora and Lambda
   - Security groups restricting traffic to VPC only
   - VPC endpoints for Bedrock and Secrets Manager (no internet access)
   - CloudFront with HTTPS termination (TLS 1.2 minimum)
   - ALB restricted to CloudFront IP ranges

2. **Access Control**:
   - IAM roles with least privilege for Lambda and EC2
   - IAM database authentication enabled
   - Secrets Manager with KMS encryption
   - No public database access

3. **Application Security**:
   - Parameterised SQL queries (SQL injection prevention)
   - Bedrock Guardrails with PROMPT_ATTACK filter (prompt injection prevention)
   - Input validation via LLM filter extraction

4. **Rate Limiting & DoS Protection**:
   - AWS WAF with 15 requests/minute per IP
   - Lambda reserved concurrency limit of 10
   - CloudFront caching (reduces backend load)

5. **Encryption**:
   - TLS 1.2 for all external communications
   - Aurora encryption at rest with KMS CMK
   - Secrets Manager encryption with KMS CMK
   - EC2 root volume encryption with KMS

6. **Monitoring**:
   - CloudWatch Logs for Lambda and Aurora
   - WAF metrics for blocked requests
   - Enhanced monitoring for RDS (60-second intervals)
   - Performance Insights enabled

### Identified Gaps

1. **Training Data Protection**:
   - File system permissions for training_data.jsonl not explicitly configured
   - No encryption at rest for training data file
   - **Recommendation**: Set file permissions to 600 and consider encrypting sensitive logs

2. **Monitoring & Alerting**:
   - CloudWatch alarms not configured for abnormal patterns
   - No alerting for WAF blocked requests or Lambda throttling
   - **Recommendation**: Configure CloudWatch alarms for security events

3. **Secrets Rotation**:
   - Aurora password rotation not configured
   - **Recommendation**: Enable automatic secret rotation in Secrets Manager

## Risk Assessment

### High-Severity Threats

**T3: Database Credential Theft** (High/Unlikely)  
- **Status**: Mitigated via IAM policies and VPC endpoints
- **Residual Risk**: Low (requires compromised IAM credentials)

**T4: Database Data Exfiltration** (High/Possible)  
- **Status**: Mitigated via network isolation and encryption
- **Residual Risk**: Low (requires network access to private subnet)

**T5: API Cost Escalation Attack** (High/Likely)  
- **Status**: Partially mitigated via WAF and Lambda limits
- **Residual Risk**: Medium (distributed attacks could bypass IP-based rate limiting)
- **Recommendation**: Implement CloudWatch alarms and consider additional cost controls

### Medium-Severity Threats

**T1: Prompt Injection Attack** (Medium/Possible)  
- **Status**: Mitigated via Bedrock Guardrails
- **Residual Risk**: Low (HIGH strength filter blocks most attacks)

**T6: SQL Injection** (Medium/Possible)  
- **Status**: Mitigated via parameterised queries
- **Residual Risk**: Very Low (code review confirms no string concatenation)

**T7: Lambda Privilege Escalation** (Medium/Possible)  
- **Status**: Mitigated via least privilege IAM
- **Residual Risk**: Low (specific resource ARNs only)

**T8: WAF Bypass** (Medium/Possible)  
- **Status**: Mitigated via global rate limiting
- **Residual Risk**: Medium (sophisticated distributed attacks possible)

### Low-Severity Threats

**T2: Training Data Exposure** (Low/Possible)  
- **Status**: Requires implementation of file permissions
- **Residual Risk**: Medium (file currently world-readable on EC2)
- **Recommendation**: Immediate action to restrict file permissions

## Recommendations

### Immediate Actions (High Priority)

1. **Restrict Training Data File Permissions**:
   ```bash
   chmod 600 /home/ec2-user/app/training_data.jsonl
   chown ec2-user:ec2-user /home/ec2-user/app/training_data.jsonl
   ```

2. **Configure CloudWatch Alarms**:
   - WAF blocked requests > 100/minute
   - Lambda concurrent executions > 8
   - Aurora CPU utilisation > 80%
   - Bedrock API throttling events

3. **Enable Secrets Rotation**:
   - Configure automatic rotation for Aurora credentials (30-day cycle)

### Short-Term Actions (Medium Priority)

4. **Implement Request Logging**:
   - Log all search queries with timestamps and source IPs
   - Enable ALB access logs to S3
   - Configure log retention policies

5. **Add Security Headers**:
   - Configure CloudFront to add security headers (X-Frame-Options, X-Content-Type-Options, etc.)

6. **Review IAM Policies**:
   - Audit Lambda and EC2 IAM roles for excessive permissions
   - Remove unused permissions

### Long-Term Actions (Low Priority)

7. **Implement Authentication**:
   - Add Cognito or API key authentication for production use
   - Implement per-user rate limiting

8. **Add Audit Logging**:
   - Enable CloudTrail for API call auditing
   - Configure AWS Config for compliance monitoring

9. **Implement Backup Strategy**:
   - Configure Aurora automated backups (currently 1-day retention)
   - Test restore procedures

10. **Security Testing**:
    - Conduct penetration testing for prompt injection attacks
    - Test SQL injection prevention with automated tools
    - Validate WAF effectiveness against DDoS simulation

## Compliance & Regulatory Considerations

**Current Status**: No regulatory requirements (demo application with public dataset)

**If Moving to Production**:
- GDPR compliance if handling EU user data (requires consent, data retention policies, right to deletion)
- CCPA compliance if handling California resident data
- PCI DSS if handling payment card data (not applicable to vehicle listings)
- SOC 2 Type II for service provider trust

## Assumptions

1. **Network Security**: All internal network traffic within VPC is trusted
2. **AWS Service Security**: AWS-managed services (Bedrock, Secrets Manager, Aurora) follow AWS security best practices
3. **Data Sensitivity**: Vehicle listing data is non-sensitive (public Kaggle dataset)
4. **User Trust**: No authentication required for demo purposes (acceptable for low-criticality system)
5. **Cost Controls**: 15 requests/minute rate limit sufficient for demo traffic patterns
6. **Monitoring**: Manual monitoring acceptable for demo (automated alerting recommended for production)

## Conclusion

The car search application demonstrates a reasonable security posture for a demo system with low criticality. Key security controls are implemented:

- Network isolation prevents unauthorised database access
- IAM policies enforce least privilege
- Bedrock Guardrails protect against prompt injection
- Parameterised queries prevent SQL injection
- Rate limiting controls API costs

**Primary Risks**:
- API cost escalation from distributed attacks (partially mitigated)
- Training data exposure from inadequate file permissions (requires immediate action)
- Lack of monitoring and alerting (recommended for production)

**Overall Risk Level**: Medium (acceptable for demo, requires hardening for production)

**Next Steps**:
1. Implement immediate actions (file permissions, CloudWatch alarms)
2. Review and implement short-term recommendations
3. Plan for authentication and audit logging if moving to production
4. Conduct security testing before production deployment

---

**Document Version**: 1.0  
**Last Updated**: 27 February 2026  
**Next Review**: Before production deployment
