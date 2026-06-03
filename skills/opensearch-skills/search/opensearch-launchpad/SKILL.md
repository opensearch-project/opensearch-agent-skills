---
name: opensearch-launchpad
description: >
  Build search applications with OpenSearch from scratch. Use this skill when
  the user mentions search app, index setup, search architecture, semantic
  search, vector search, hybrid search, BM25, dense vector, sparse vector,
  agentic search, RAG, embeddings, KNN, PDF ingestion, document processing,
  or any related search topic. Activate even if the user says search quality,
  evaluation, nDCG, precision, relevance tuning, or search builder without
  mentioning OpenSearch.
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
- The skill directory available locally

## Optional MCP Servers

```json
{
  "mcpServers": {
    "ddg-search": {
      "command": "uvx",
      "args": ["duckduckgo-mcp-server"]
    },
    "opensearch-mcp-server": {
      "command": "uvx",
      "args": ["opensearch-mcp-server-py@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    }
  }
}
```

- **`ddg-search`** — Search OpenSearch documentation. Use `search(query="site:opensearch.org <your query>")`.
- **`opensearch-mcp-server`** — Direct OpenSearch API access. Handles SigV4 auth for AOS/AOSS transparently.

### opensearch-mcp-server Configuration Variants

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

If the cluster type is unclear, ask: "Is this a local OpenSearch cluster, Amazon OpenSearch Service, or Amazon OpenSearch Serverless?"

## Scripts

All operations use shared scripts at the skill root:

```bash
bash scripts/start_opensearch.sh
uv run python scripts/opensearch_ops.py <command> [options]
```

See [cli-reference.md](../../cli-reference.md) for the full command reference.

## Key Rules

### Autonomy & Efficiency
- **If the user provides all necessary information** (index name, search strategy, model, cluster status, credentials), **proceed directly** to planning and execution. Do not ask for information already stated.
- **Batch missing questions**: If information IS missing, ask all needed questions in ONE message — never one question per message across multiple turns.
- **Skip Phase 2** if the user's prompt already specifies the search strategy.
- **Skip plan approval** for straightforward setups where the user has stated what they want. Only present the plan for approval when there are meaningful architectural decisions the user hasn't addressed.

### Recovery & Error Handling
- When a step fails, **diagnose the error and provide concrete fix commands** — do not just say "an error occurred, what would you like to do?"
- When the user describes a partial setup (some steps done, some failed), **resume from where it failed**. Do not redo completed steps. Reuse existing IDs (model_id, agent_id, pipeline names).
- When credentials expire, the fix is to refresh credentials and update the connector — **never re-deploy a model** that is already registered.

### Correctness
- **Never skip Phase 1** (preflight check) — always verify cluster is available first. However, if the user states "cluster is running" or "OpenSearch is already running", treat that as a passed preflight and proceed without waiting for output.
- **Only use commands documented in [cli-reference.md](../../cli-reference.md)**. Do not invent flags or arguments. If unsure about exact syntax, read the CLI reference first.
- Do not describe **Amazon OpenSearch Serverless** as scaling to zero.
- **Agentic search** does not deploy to **Amazon OpenSearch Serverless** — use a **managed domain**.
- Follow the phases **in order** unless the user's context allows skipping (e.g., cluster already running with data = skip sample loading).

## Workflow Phases

### Phase 1 — Start OpenSearch & Collect Sample

Check if a cluster is already running:

```bash
uv run python scripts/opensearch_ops.py preflight-check
```

- **`status: "available"`** — Cluster running. Use it directly.
- **`status: "auth_required"`** — Ask for credentials, then retry with `--auth-mode custom`.
- **`status: "no_cluster"`** — Start one: `bash scripts/start_opensearch.sh`

Once available:
- If the user **already has data in an index** (stated in their prompt), skip sample loading.
- If the user **specifies a data source** (file path, URL, builtin_imdb), load it directly with `load-sample`.
- Otherwise, ask for the data source.

If the user provides PDF, DOCX, PPTX, or XLSX files, use Docling to process them. Read [document_processing_guide.md](document_processing_guide.md) for the workflow.

### Phase 2 — Gather Preferences

**Skip this phase** if the user already specified their search strategy in the prompt.

If the strategy is unclear, present all five options and ask the user to choose:
- `bm25` (keyword)
- `dense_vector` (semantic via embeddings)
- `neural_sparse` (semantic via learned sparse representations)
- `hybrid` (combines keyword + semantic)
- `agentic` (LLM-driven multi-step retrieval, requires OpenSearch 3.2+)

Recognize natural language equivalents: "keyword search" = BM25, "semantic search" = dense_vector, "best of both" = hybrid, "AI-powered search" / "conversational search" = agentic.

### Phase 3 — Plan

Design a search architecture. Read the relevant knowledge files:

- [dense_vector_models.md](dense_vector_models.md)
- [sparse_vector_models.md](sparse_vector_models.md)
- [opensearch_semantic_search_guide.md](opensearch_semantic_search_guide.md)
- [agentic_search_guide.md](agentic_search_guide.md)
- [document_processing_guide.md](document_processing_guide.md)

**Fast-path**: If the user specified strategy, model, and index name — present a brief plan summary and proceed to execution in the same message. No separate approval turn needed.

**Standard path**: If there are open architectural decisions (model choice, weights, field mappings), present the plan and wait for approval.

### Phase 4 — Execute

Execute the plan using `opensearch_ops.py` commands. When launching the UI, present the URL (default: `http://127.0.0.1:8765`).

**For Dense Vector / Hybrid Search:** Execute these steps in sequence. Use exact command syntax from [cli-reference.md](../../cli-reference.md):

1. `deploy-model --name "huggingface/sentence-transformers/<model>"` → get model_id
2. `create-pipeline --name <pipeline> --index <index> --type ingest --body '{...text_embedding processor with model_id and field_map...}'`
3. `create-index --name <index> --body '{...knn_vector field with correct dimension...}'`
4. For hybrid: `create-pipeline --name <search-pipeline> --index <index> --type search --hybrid --weights '[0.3, 0.7]'`
5. `index-bulk --index <index> --source-file <path>`
6. `launch-ui --index <index>`

**For Agentic Search:** Use the composite command to set up the full pipeline in one step:

```bash
uv run python scripts/opensearch_ops.py setup-agentic-search \
  --index <index_name> --agent-type <flow|conversational> --region <aws_region>
```

This handles all steps automatically (deploy model → create agent → deploy RAG model → create pipeline). AWS credentials are read from environment variables. If a step fails, the output includes a `resume_hint` with the exact command to retry using `--model-id` and/or `--agent-id` to skip completed steps.

If AWS credentials and agent type are already in the user's prompt, proceed directly. Otherwise ask for both in **one message**. See [cli-reference.md](../../cli-reference.md) for all options.

**Verification after multi-step setup (dense/hybrid/agentic):** After completing pipeline setup, run diagnostics:

```bash
uv run python scripts/opensearch_ops.py check-agentic-setup --index <index_name>
```

This checks: index exists, pipeline attached, agent registered, model deployed. If any check fails, diagnose the issue and provide the fix command.

After the UI is running:
> "Your search app is live! Here's what you can do next:"
> 1. **Evaluate search quality** (Phase 4.5)
> 2. **Deploy to Amazon OpenSearch Service** — use the `aws-setup` skill
> 3. **Done for now** — Keep experimenting with the Search Builder UI.

### Phase 4.5 — Evaluate (Optional)

Read and follow [evaluation_guide.md](evaluation_guide.md). If HIGH severity findings exist, offer to restart from Phase 3.

### Phase 5 — Deploy to AWS (Optional)

Refer the user to the [aws-setup](../../cloud/aws-setup/SKILL.md) skill for the full deployment workflow.
