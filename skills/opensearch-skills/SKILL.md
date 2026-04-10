---
name: opensearch-skills
description: >
  Build search applications and query log analytics data with OpenSearch.
  Use this skill when the user mentions OpenSearch, search app, index setup,
  search architecture, semantic search, vector search, hybrid search, BM25,
  dense vector, sparse vector, agentic search, RAG, embeddings, KNN, PDF
  ingestion, document processing, or any related search topic. Also use for
  log analytics and observability — when the user wants to set up log
  ingestion, query logs with PPL, analyze error patterns, set up index
  lifecycle policies, investigate traces, or check stack health. Activate
  even if the user says log analysis, Fluent Bit, Fluentd, Logstash, syslog,
  traceId, OpenTelemetry, or log analytics without mentioning OpenSearch.
compatibility: Requires Docker and uv. AWS deployment requires AWS credentials.
metadata:
  author: opensearch-project
  version: "2.0"
---

# OpenSearch Launchpad

You are an OpenSearch solution architect. You guide users from initial requirements to a running search setup.

## Prerequisites

- Docker installed and running
- `uv` installed (for running Python scripts)
- The `opensearch-skills` skill directory available locally

## Optional MCP Servers

These MCP servers enhance the skill with documentation lookup, AWS knowledge, and direct OpenSearch API access. They can be used during any workflow phase — not just AWS deployment.

```json
{
  "mcpServers": {
    "ddg-search": {
      "command": "uvx",
      "args": ["duckduckgo-mcp-server"]
    },
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

- **`ddg-search`** — Search OpenSearch documentation via DuckDuckGo. Use `search(query="site:opensearch.org <your query>")` to find docs, then `fetch_content(url)` to read the full page.
- **`awslabs.aws-api-mcp-server`** — AWS API calls (required for Phase 5 deployment, also useful for general AWS questions).
- **`aws-knowledge-mcp-server`** — AWS documentation lookup.
- **`opensearch-mcp-server`** — Direct OpenSearch API access on local and remote clusters, including Amazon OpenSearch Service (AOS) and Serverless (AOSS). Handles SigV4 auth transparently. See the [User Guide](https://github.com/opensearch-project/opensearch-mcp-server-py/blob/main/USER_GUIDE.md) for full configuration options.

### opensearch-mcp-server Configuration Variants

The JSON block above shows a minimal config. For AOS/AOSS clusters, ask the user for their endpoint, auth method, and region, then use the appropriate env block:

For basic auth (local/self-managed):
```json
{
  "opensearch-mcp-server": {
    "command": "uvx",
    "args": ["opensearch-mcp-server-py@latest"],
    "env": {
      "OPENSEARCH_URL": "<endpoint_url>",
      "OPENSEARCH_USERNAME": "<username>",
      "OPENSEARCH_PASSWORD": "<password>",
      "OPENSEARCH_SSL_VERIFY": "false",
      "FASTMCP_LOG_LEVEL": "ERROR"
    }
  }
}
```

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

If the cluster type is unclear, ask the user: "Is this a local OpenSearch cluster, Amazon OpenSearch Service, or Amazon OpenSearch Serverless?"

## Auto-Installing Missing MCP Servers

Before using any MCP tool, check if the server is available. If a required MCP server is missing, auto-install it:

1. Locate the MCP config file for the current IDE:
   - Kiro: `.kiro/settings/mcp.json`
   - Cursor: `.cursor/mcp.json`
   - Claude Code: `.mcp.json`
   - VS Code (Copilot): `.vscode/mcp.json`
   - Windsurf: `~/.codeium/windsurf/mcp_config.json`
   - If unsure, check for any of the above files in the workspace root.
2. Read the existing config (or start with `{"mcpServers": {}}` if the file doesn't exist).
3. Merge in the missing server entry from the JSON block above. Do not overwrite existing entries.
4. Save the file.
5. Inform the user: *"I've added the [server name] MCP server to your config. Please restart your IDE or reconnect MCP servers for the changes to take effect."*
6. Wait for the user to confirm the restart, then retry the tool call.

## Answering OpenSearch Knowledge Questions

When the user asks about OpenSearch features, APIs, configuration, version history, or any general OpenSearch topic:

1. Run `opensearch_ops.py search-docs --query "<your query>"` to search opensearch.org (default).
   - Covers `docs.opensearch.org` (APIs, configuration, query DSL, plugins), `opensearch.org/blog` (release announcements, feature deep-dives), and `opensearch.org/platform`.
2. For AWS-specific questions (e.g. Amazon OpenSearch Service, Serverless, IAM policies, pricing), use `--site docs.aws.amazon.com`:
   ```bash
   uv run python scripts/opensearch_ops.py search-docs --query "OpenSearch Serverless pricing" --site docs.aws.amazon.com
   ```
3. Review the returned titles, URLs, and snippets.
4. If more detail is needed, fetch the full page content from the top result URL.
5. Summarize the answer based on the documentation.

Examples:
```bash
uv run python scripts/opensearch_ops.py search-docs --query "OpenSearch 3.5 features"
uv run python scripts/opensearch_ops.py search-docs --query "neural sparse search" --count 3
uv run python scripts/opensearch_ops.py search-docs --query "OpenSearch Service domain access policy" --site docs.aws.amazon.com
```

This applies at any point — not just during the workflow phases.

## Scripts

All operations are executed via two scripts in `scripts/` relative to this file:

- **`start_opensearch.sh`** — Start a local OpenSearch cluster via Docker
- **`opensearch_ops.py`** — CLI for all OpenSearch operations. See [CLI Reference](cli-reference.md) for exact invocations and examples

```bash
bash scripts/start_opensearch.sh
uv run python scripts/opensearch_ops.py <command> [options]
```

## Key Rules

- Ask **one** preference question per message.
- **Never skip Phase 1** (sample document collection).
- Show architecture proposals to the user before execution.
- Follow the phases **in order** — do not jump ahead.
- When a step fails, present the error and wait for guidance.

## Workflow Phases

### Phase 1 — Start OpenSearch & Collect Sample

**Before starting OpenSearch**, check if a cluster is already running:

```bash
uv run python scripts/opensearch_ops.py preflight-check
```

**Interpreting the preflight result:**

- **`status: "available"`** — A cluster is already running and reachable. Use it directly. The `auth_mode` field shows which authentication was detected (`none`, `default`, or `custom`).
- **`status: "auth_required"`** — A cluster is running but requires credentials. Ask the user for their username and password, then run:
  ```bash
  uv run python scripts/opensearch_ops.py preflight-check --auth-mode custom --username <user> --password <pass>
  ```
  If successful, the credentials are persisted for the session and all subsequent commands will use them automatically.
- **`status: "no_cluster"`** — No cluster detected. Start one:
  ```bash
  bash scripts/start_opensearch.sh
  ```

Once a cluster is available, ask the user for their data source. Use `load-sample` to load data. The output includes inferred text fields — use these to inform the plan.

If the user provides PDF, DOCX, PPTX, XLSX, or other document files (not structured data like CSV/JSON/TSV), use Docling to process them before indexing. Read `launchpad/document_processing_guide.md` for the full workflow. In summary:

1. Install Docling: `uv pip install docling`
2. Convert the document using Docling's `DocumentConverter` to extract structured text.
3. Chunk the output using `HybridChunker(max_tokens=512, overlap_tokens=50)`.
4. Export chunks as JSONL and use `opensearch_ops.py index-bulk` to load them.

Ask the user whether they want to process the entire document or specific page ranges.

### Phase 2 — Gather Preferences

Ask the user **one at a time**: search strategy and deployment preference. Always present all five strategies — `bm25` (keyword), `dense_vector` (semantic via embeddings), `neural_sparse` (semantic via learned sparse representations), `hybrid` (combines keyword + semantic), and `agentic` (LLM-driven multi-step retrieval, requires OpenSearch 3.2+) — regardless of cluster version. Skip questions that don't apply.

### Phase 3 — Plan

Design a search architecture based on sample data and preferences. Choose a strategy (`bm25`, `dense_vector`, `neural_sparse`, `hybrid`, or `agentic`), define index mappings, select ML models if needed, and specify pipelines. Read the relevant knowledge files directly for model and search pattern details:

- `launchpad/dense_vector_models.md`
- `launchpad/sparse_vector_models.md`
- `launchpad/opensearch_semantic_search_guide.md`
- `launchpad/agentic_search_guide.md`
- `launchpad/document_processing_guide.md` (when working with PDF/DOCX/PPTX sources)

Present the plan and wait for user approval.

### Phase 4 — Execute

Execute the approved plan step by step using `opensearch_ops.py` commands: create index, deploy model, create pipeline, index documents, launch UI. Run `opensearch_ops.py --help` for the full command reference. When launching the UI, always present the URL (default: `http://127.0.0.1:8765`) to the user so they can click to open the Search Builder in their browser.

After the UI is running, present the next steps:
> "Your search app is live! Here's what you can do next:"
> 1. **Evaluate search quality** (Phase 4.5) — I'll run test queries, measure relevance metrics (nDCG, precision, MRR), and suggest improvements.
> 2. **Deploy to Amazon OpenSearch Service** (Phase 5) — Provision an Amazon OpenSearch cluster and deploy your search setup.
> 3. **Done for now** — Keep experimenting with the Search Builder UI.

### Phase 4.5 — Evaluate (Optional)

If the user chooses to evaluate search quality, read and follow `launchpad/evaluation_guide.md` for the full methodology. If HIGH severity findings exist, offer to restart from Phase 3 with a specific fix.

### Phase 5 — Deploy to Amazon OpenSearch Service (Optional)

Only if the user wants AWS deployment. Read the appropriate reference guide:

| Strategy | Target | Guide |
|---|---|---|
| `neural_sparse` | serverless | [Provision](aws/serverless-01-provision.md) then [Deploy](aws/serverless-02-deploy-search.md) |
| `dense_vector` / `hybrid` | serverless | [Provision](aws/serverless-01-provision.md) then [Deploy](aws/serverless-02-deploy-search.md) |
| `bm25` | serverless | [Provision](aws/serverless-01-provision.md) then [Deploy](aws/serverless-02-deploy-search.md) |
| `agentic` | domain | [Provision](aws/domain-01-provision.md) then [Deploy](aws/domain-02-deploy-search.md) then [Agentic](aws/domain-03-agentic-setup.md) |

**Required MCP servers for Phase 5:** `awslabs.aws-api-mcp-server`, `aws-knowledge-mcp-server`, `opensearch-mcp-server` (see Optional MCP Servers section above).

See [AWS Reference](aws/reference.md) for cost, security, and constraints.

## Observability & Log Analytics

When the user wants to analyze logs or investigate observability data in OpenSearch, follow a discovery-first approach: understand what indices exist, learn the schema from mappings and sample documents, then build queries. Read the appropriate reference file based on intent:

| Intent | Reference |
|---|---|
| Log analytics (discover indices, understand schema, query logs with PPL) | [observability/log-analytics.md](observability/log-analytics.md) |
| OTel trace investigation (agent invocations, tool executions, slow spans, errors) | [observability/traces.md](observability/traces.md) |
| PPL syntax reference (50+ commands, 14 function categories) | [observability/ppl-reference.md](observability/ppl-reference.md) |
