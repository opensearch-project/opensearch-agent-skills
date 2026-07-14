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
      "env": { "FASTMCP_LOG_LEVEL": "ERROR", "AWS_SDK_UA_APP_ID": "opensearch-agent-skills" }
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

## Critical Rules (MUST follow)

1. **No agentic search on Serverless non-NextGen** — Agentic search (both flow agents and conversational agents) CANNOT be deployed to Serverless non-NextGen (v1/classic). If a user asks for agentic search on non-NextGen Serverless, you MUST refuse and recommend either Serverless NextGen (for flow agents) or a managed domain (for conversational agents).
2. **Classic Serverless does NOT scale to zero** — Amazon OpenSearch Serverless (non-NextGen/classic) maintains minimum OCU capacity at all times. NEVER claim classic Serverless scales to zero. Note: Serverless NextGen DOES support scale to zero.
3. **Validate credentials first** — ALWAYS run `aws sts get-caller-identity` as the first step before any provisioning or deployment operation.
4. **Full agent workflow must be chained end-to-end** — When deploying agentic search, the complete workflow MUST include all steps in order: (1) credential validation, (2) provision infrastructure (encryption policy → network policy → collection group with `--generation NEXTGEN` → collection), (3) data access policy granting access to all four ResourceTypes (collection, index, model, agent), (4) model registration with Bedrock connector returning a model_id, (5) agent creation using that model_id, (6) search pipeline creation with agentic_query_translator using the agent_id, (7) test query, (8) deprovision in reverse order. Outputs from each step must chain into the next.

## Key Rules

- **Serverless NextGen** supports only **flow agents** — conversational agents require a **managed domain**.
- Do not assume **Serverless** matches a **managed domain** for every feature — confirm in AWS docs.
- Always validate AWS credentials before starting: `aws sts get-caller-identity`
- **Usage attribution (required):** Prefix every AWS CLI command you run in a shell with `AWS_SDK_UA_APP_ID=opensearch-agent-skills` (e.g. `AWS_SDK_UA_APP_ID=opensearch-agent-skills aws <service> <command> ...`), regardless of service (opensearch, opensearchserverless, iam, sts, s3, …). Scope it per-command — do not `export` it globally. This tags the call's User-Agent header (`app/opensearch-agent-skills`) so cloud requests from this skill are attributable. AWS calls made through `awslabs.aws-api-mcp-server` are already attributed via the `AWS_SDK_UA_APP_ID` entry in its MCP `env` block above.
- Track deployment state in `.opensearch-deploy-state.json` at the workspace root.
- When a step fails, present the error and wait for guidance.

## Deployment Target Selection

Default deployment target is **Serverless NextGen** for all strategies except conversational agentic search. Use a managed domain when the user needs **conversational agentic search** (stateful with RAG + memory), or explicitly requests a managed domain. Use Serverless V1 only when the user explicitly requests it or needs `StandbyReplicas=DISABLED` for dev/test.

| Strategy | Target | Collection Type | Why |
|---|---|---|---|
| `bm25` | Serverless NextGen | SEARCH | Simple, no ML models needed |
| `neural_sparse` | Serverless NextGen | SEARCH | Automatic semantic enrichment built-in |
| `dense_vector` | Serverless NextGen | VECTORSEARCH | GPU-accelerated kNN, Bedrock connector supported |
| `hybrid` | Serverless NextGen | VECTORSEARCH | Combines BM25 + vector with GPU acceleration |
| `agentic` (flow) | Serverless NextGen | SEARCH | Stateless query planning, low latency, managed infra |
| `agentic` (conversational) | Domain | — | Stateful with RAG + memory, multi-turn conversations |
| Any (non-NextGen requested) | Serverless | — | Standard SDK, `StandbyReplicas=DISABLED` for dev/test |

## Workflow

Follow the guides linked in the table above, in order:

### Step 1 — Provision Infrastructure

| Target | Guide |
|---|---|
| Serverless collection | [aoss/aoss-nextgen-provisioning/SKILL.md](aoss/aoss-nextgen-provisioning/SKILL.md) |
| Managed domain | [aos/domain-01-provision.md](aos/domain-01-provision.md) |

### Step 2 — Deploy Search Configuration

| Target | Guide |
|---|---|
| Serverless collection | [aoss/serverless-02-deploy-search.md](aoss/serverless-02-deploy-search.md) |
| Managed domain | [aos/domain-02-deploy-search.md](aos/domain-02-deploy-search.md) |

### Step 3 — Configure Agentic Search (if applicable)

| Target | Guide |
|---|---|
| Conversational Agent Search | [aos/domain-03-agentic-setup.md](aos/domain-03-agentic-setup.md) |
| Flow Agent Search | [aoss/serverless-04-agentic-setup.md](aoss/serverless-04-agentic-setup.md) |

### Step 4 — Launch Search UI

```bash
uv run python scripts/opensearch_ops.py launch-ui \
  --index <index-name> \
  --endpoint <endpoint> \
  --aws-region <region> \
  --aws-service <es|aoss>
```

### Step 5 — Provide Access Information

Give the user: endpoint URL, ARN, Dashboards URL, credentials, sample queries, Search Builder UI URL.

## Reference

See [reference.md](reference.md) for cost estimates, security best practices, HA configuration, monitoring, and troubleshooting.
