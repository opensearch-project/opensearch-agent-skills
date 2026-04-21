---
name: cloud
description: >
  Deploy OpenSearch search applications to AWS. Use this skill when the user
  wants to provision an OpenSearch domain or serverless collection on AWS,
  deploy search configurations, set up Bedrock connectors, configure IAM
  roles for OpenSearch, or migrate a local setup to Amazon OpenSearch Service
  or Serverless. Activate even if the user says AOS, AOSS, OpenSearch Service,
  serverless collection, Bedrock connector, SigV4, or AWS deployment.
compatibility: Requires AWS credentials (IAM role or access keys).
metadata:
  author: opensearch-project
  version: "2.0"
---

# Cloud

Category skill for deploying OpenSearch to cloud infrastructure.

## Skills

| Skill | Description |
|---|---|
| [aws-setup](aws-setup/SKILL.md) | Provision and configure Amazon OpenSearch Service domains and Serverless collections, then deploy search configurations |

## When to Use

Read [aws-setup/SKILL.md](aws-setup/SKILL.md) when the user wants to:
- Provision an Amazon OpenSearch Service domain
- Create an Amazon OpenSearch Serverless collection
- Deploy a local search setup to AWS
- Set up Bedrock connectors for ML models
- Configure IAM roles and access policies for OpenSearch
