---
name: cloud
description: >
  Deploy OpenSearch search applications to managed cloud providers. Use this
  skill when the user wants to provision an OpenSearch domain or serverless
  collection on AWS, provision a managed OpenSearch service on Aiven, deploy
  search configurations, set up Bedrock connectors, configure IAM roles for
  OpenSearch, or migrate a local setup to a managed OpenSearch. Activate even
  if the user says AOS, AOSS, OpenSearch Service, serverless collection,
  Bedrock connector, SigV4, AWS deployment, Aiven, or managed OpenSearch.
compatibility: >
  AWS deployment requires AWS credentials (IAM role or access keys). Aiven
  deployment requires the Aiven MCP server and an Aiven API token.
metadata:
  author: opensearch-project
  version: "2.0"
---

# Cloud

Category skill for deploying OpenSearch to managed cloud infrastructure.

## Skills

| Skill | Description |
|---|---|
| [aws-setup](aws-setup/SKILL.md) | Provision and configure Amazon OpenSearch Service domains and Serverless collections, then deploy search configurations |
| [aiven-setup](aiven-setup/SKILL.md) | Provision a managed Aiven for OpenSearch service, then deploy search configurations to it |
| [managed-ingestion-service](managed-ingestion-service/SKILL.md) | Ingest chunks at scale via OSIS pipelines with optional ASE (semantic_enrichment) |

## When to Use

Read [aws-setup/SKILL.md](aws-setup/SKILL.md) when the user wants to:
- Provision an Amazon OpenSearch Service domain
- Create an Amazon OpenSearch Serverless collection
- Deploy a local search setup to AWS
- Set up Bedrock connectors for ML models
- Configure IAM roles and access policies for OpenSearch

Read [aiven-setup/SKILL.md](aiven-setup/SKILL.md) when the user wants to:
- Provision a managed OpenSearch service on Aiven
- Deploy a local search setup to Aiven for OpenSearch
- Manage or monitor Aiven-hosted OpenSearch (metrics, logs, service state)
- Deploy across AWS, GCP, Azure, DigitalOcean, or UpCloud via Aiven

Read [managed-ingestion-service/SKILL.md](managed-ingestion-service/SKILL.md) when the user wants to:
- Ingest JSONL chunks into an AOS domain or AOSS collection at scale via OSIS
- Set up an OSIS pipeline with semantic_enrichment (ASE)
- Upload chunks to S3 and create a managed ingestion pipeline

## Usage Attribution

For all cloud work under this category, tag AWS requests with the application id `opensearch-agent-skills` so calls made by these skills are attributable in AWS-side logs:
- **Shell `aws` commands:** prefix per-command with `AWS_SDK_UA_APP_ID=opensearch-agent-skills` (never `export` globally).
- **`awslabs.aws-api-mcp-server`:** set `"AWS_SDK_UA_APP_ID": "opensearch-agent-skills"` in the server's MCP `env` block.

This applies to every AWS service (opensearch, opensearchserverless, iam, sts, s3, …), not just OpenSearch calls.
