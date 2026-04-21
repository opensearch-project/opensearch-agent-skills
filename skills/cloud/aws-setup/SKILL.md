---
name: aws-setup
description: >
  Deploy OpenSearch search applications to Amazon OpenSearch Service or
  Amazon OpenSearch Serverless. Use this skill when the user wants to
  provision an OpenSearch domain or serverless collection on AWS, deploy
  search configurations to AWS, set up Bedrock connectors, configure IAM
  roles for OpenSearch, migrate a local search setup to AWS, or manage
  Amazon OpenSearch infrastructure. Activate even if the user says AOS,
  AOSS, OpenSearch Service, serverless collection, Bedrock connector,
  SigV4, or AWS deployment without mentioning search.
compatibility: >
  Requires AWS credentials (IAM role or access keys), awslabs.aws-api-mcp-server,
  and opensearch-mcp-server. A local search setup (from opensearch-launchpad) is
  recommended but not required.
metadata:
  author: opensearch-project
  version: "2.0"
---

# OpenSearch AWS Deployment

You are an AWS deployment specialist for OpenSearch. You help users provision and configure Amazon OpenSearch Service domains and Serverless collections, then deploy search configurations to them.

## Prerequisites

- AWS credentials configured (IAM role, access keys, or AWS profile)
- `uv` installed (for running helper scripts)
- A search configuration to deploy (typically built with the `opensearch-launchpad` skill)

## Required MCP Servers

```json
{
  "mcpServers": {
    "awslabs.aws-api-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.aws-api-mcp-server@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    },
    "aws-knowledge-mcp-server": {
      "command": "uvx",
      "args": ["fastmcp", "run", "https://knowledge-mcp.global.api.aws"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    },
    "opensearch-mcp-server": {
      "command": "uvx",
      "args": ["opensearch-mcp-server-py@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    }
  }
}
```

- **`awslabs.aws-api-mcp-server`** — AWS API calls for provisioning domains, collections, IAM roles.
- **`aws-knowledge-mcp-server`** — AWS documentation lookup.
- **`opensearch-mcp-server`** — Direct OpenSearch API access. Handles SigV4 auth for AOS/AOSS.

### opensearch-mcp-server Configuration for AWS

For Amazon OpenSearch Service (AOS):
```json
{
  "opensearch-mcp-server": {
    "command": "uvx",
    "args": ["opensearch-mcp-server-py@latest"],
    "env": {
      "OPENSEARCH_URL": "<endpoint_url>",
      "AWS_REGION": "<region>",
      "AWS_PROFILE": "<profile>",
      "FASTMCP_LOG_LEVEL": "ERROR"
    }
  }
}
```

For Amazon OpenSearch Serverless (AOSS):
```json
{
  "opensearch-mcp-server": {
    "command": "uvx",
    "args": ["opensearch-mcp-server-py@latest"],
    "env": {
      "OPENSEARCH_URL": "<endpoint_url>",
      "AWS_REGION": "<region>",
      "AWS_PROFILE": "<profile>",
      "AWS_OPENSEARCH_SERVERLESS": "true",
      "FASTMCP_LOG_LEVEL": "ERROR"
    }
  }
}
```

## Key Rules

- Do not describe **Amazon OpenSearch Serverless** as scaling to zero.
- **Agentic search** does not deploy to **Amazon OpenSearch Serverless** — use a **managed domain**.
- Do not assume **Serverless** matches a **managed domain** for every feature — confirm in AWS docs.
- Always validate AWS credentials before starting: `aws sts get-caller-identity`
- Track deployment state in `.opensearch-deploy-state.json` at the workspace root.
- When a step fails, present the error and wait for guidance.

## Deployment Target Selection

| Strategy | Target | Why |
|---|---|---|
| `bm25` | Serverless | Simple, no ML models needed |
| `neural_sparse` | Serverless | Automatic semantic enrichment built-in |
| `dense_vector` | Serverless | Bedrock connector supported |
| `hybrid` | Serverless | Combines BM25 + vector on serverless |
| `agentic` | Domain | Requires agent framework, not available on serverless |

## Workflow

### Step 1 — Provision Infrastructure

| Target | Guide |
|---|---|
| Serverless collection | [aoss/serverless-01-provision.md](aoss/serverless-01-provision.md) |
| Managed domain | [aos/domain-01-provision.md](aos/domain-01-provision.md) |

### Step 2 — Deploy Search Configuration

| Target | Guide |
|---|---|
| Serverless collection | [aoss/serverless-02-deploy-search.md](aoss/serverless-02-deploy-search.md) |
| Managed domain | [aos/domain-02-deploy-search.md](aos/domain-02-deploy-search.md) |

### Step 3 — Configure Agentic Search (domain only)

Only for agentic search on managed domains:
- [aos/domain-03-agentic-setup.md](aos/domain-03-agentic-setup.md)

### Step 4 — Connect Search UI

```bash
uv run python scripts/opensearch_ops.py connect-ui \
  --endpoint <endpoint> \
  --aws-region <region> \
  --aws-service <es|aoss> \
  --index <index-name>
```

### Step 5 — Provide Access Information

Give the user: endpoint URL, ARN, Dashboards URL, credentials, sample queries, Search Builder UI URL.

## Reference

See [reference.md](reference.md) for cost estimates, security best practices, HA configuration, monitoring, and troubleshooting.
