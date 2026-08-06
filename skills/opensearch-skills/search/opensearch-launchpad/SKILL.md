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
compatibility: Requires uv. Target local requires Docker. Target aws requires AWS credentials (no Docker).
metadata:
  author: opensearch-project
  version: "2.0"
---

# OpenSearch Launchpad

You are an OpenSearch solution architect. You guide users from initial requirements to a running search setup.

## Prerequisites

- `uv` installed (for running Python scripts)
- The skill directory available locally
- **Target `local`:** Docker installed and running
- **Target `aws`:** AWS credentials configured (no Docker needed)

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

## Critical Rules (MUST follow)

1. **Preflight-check first** — ALWAYS run `preflight-check` as the very first action before creating any index, loading data, or performing any cluster operation. No exceptions.
2. **Agentic search routing** — Flow agents ARE supported on Serverless NextGen. Conversational agents (with memory/RAG) require a managed domain (Amazon OpenSearch Service). If a user asks for "agentic search on Serverless" without specifying type, clarify this distinction.
3. **Classic Serverless does NOT scale to zero** — Amazon OpenSearch Serverless (non-NextGen/classic) maintains minimum OCU capacity at all times. NEVER claim classic Serverless scales to zero. Note: Serverless NextGen DOES support scale to zero.

## Key Rules

- Ask **one** preference question per message.
- **Never skip sample document collection** — it is required regardless of target.
- Show architecture proposals to the user before execution.
- Follow the phases **in order** — do not jump ahead.
- When a step fails, present the error and wait for guidance.

## Workflow Phases

### Phase 0 — Preflight Check (ALWAYS first)

Before anything else, check cluster availability:
```bash
uv run python scripts/opensearch_ops.py preflight-check
```
- `"available"` → proceed to Phase 1.
- `"auth_required"` → ask for credentials, then proceed.
- `"no_cluster"` → run `bash scripts/start_opensearch.sh`, then proceed.

### Phase 1 — Collect Sample Data

Ask for the data source. Supported inputs:
- Built-in datasets (`load-sample --type builtin_imdb`) — uses a small bundled sample (20 titles) by default, no network call. If the user wants a larger sample, ask first, then rerun with `--allow-download` to fetch up to 100k rows from IMDb's public dataset export.
- Local files: JSON, JSONL, CSV, TSV, Parquet (`load-sample --type local_file --value <path>`)
- PDF, DOCX, PPTX, XLSX — use Docling to process. Read [document_processing_guide.md](../../ingest/document-processing/document_processing_guide.md).
- URLs or pasted JSON

Inspect and validate the data (read a sample, confirm schema).

### Phase 2 — Gather Preferences

First, **fork on data type** (from Phase 1). This is the single place where the
unstructured special-casing is resolved — downstream phases stay config-driven.

#### Unstructured documents (PDF/DOCX/PPTX/XLSX)

Apply the [unstructured preset](unstructured_preset.md) — a fixed bundle of
`agentic (flow)` strategy + `neural_sparse` ingest + `semantic_enrichment` cloud sink.
Do **not** ask the strategy question. Confirm the preset with the user in one sentence,
then continue to Phase 3. Only fall through to the structured strategy path if the user
explicitly requests a different strategy.

Then ask **Target** (below).

#### Structured data (JSON/CSV/TSV)

Ask **one at a time**:

1. **Search strategy.**
   - **For unstructured documents** (PDF, DOCX, PPTX, etc.): Default to `agentic` search. Do NOT present all five strategies — proceed with agentic as the default. Mention alternatives are available if the user asks.
   - **For structured data** (JSON, CSV, etc.): Present all five:
     - `bm25` (keyword)
     - `dense_vector` (semantic via embeddings)
     - `neural_sparse` (semantic via learned sparse representations)
     - `hybrid` (combines keyword + semantic)
     - `agentic` (LLM-driven multi-step retrieval, requires OpenSearch 3.2+)

2. **Target** (below).

#### Target (both branches)

Where should the search app run?
- `local` (default) — Docker-based, fast iteration, optional AWS deployment later.
- `aws` — Deploy directly to Amazon OpenSearch Serverless. No Docker needed.

### Phase 3 — Plan

Design a search architecture. Read the relevant knowledge files:

- [dense_vector_models.md](dense_vector_models.md)
- [sparse_vector_models.md](sparse_vector_models.md)
- [opensearch_semantic_search_guide.md](opensearch_semantic_search_guide.md)
- [agentic_search_guide.md](agentic_search_guide.md)
- [document_processing_guide.md](../../ingest/document-processing/document_processing_guide.md) (unstructured: source → chunks)
- [local_ase.md](local_ase.md) (unstructured: chunks → searchable index, local target)
- [unstructured_preset.md](unstructured_preset.md) (the unstructured bundle)

Present the plan and wait for user approval.

### Phase 4 — Execute

Execute the plan against the chosen target. Both targets end with the Search Builder UI connected and running.

#### Target: `local`

1. Start or connect to local cluster (preflight already done in Phase 0).
2. Create index, load data, configure pipelines using `opensearch_ops.py` commands.
   - **Unstructured data:** follow the local steps in [unstructured_preset.md](unstructured_preset.md#target-local).
3. Launch the UI:
   ```bash
   uv run python scripts/opensearch_ops.py launch-ui --index <index-name>
   ```
4. Present: http://127.0.0.1:8765

**For Agentic Search:** Ask for AWS credentials for Bedrock. If the unstructured preset is active, use flow agent directly. Otherwise ask about agent type (Flow vs Conversational). See [cli-reference.md](../../cli-reference.md).

After the UI is running, offer:
> 1. **Evaluate search quality** (Phase 5)
> 2. **Deploy to AWS** (Phase 6)
> 3. **Done for now**

#### Target: `aws`

- **Structured data:** Hand off to [aws-setup](../../cloud/aws-setup/SKILL.md) — it handles provisioning, creating the index, loading data, and launching the UI connected to the AWS endpoint.
- **Unstructured data:** Follow the cloud steps in [unstructured_preset.md](unstructured_preset.md#target-cloud).

After the UI is running, offer:
> 1. **Evaluate search quality** (Phase 5)
> 2. **Done for now**

### Phase 5 — Evaluate (Optional)

Read and follow [evaluation_guide.md](evaluation_guide.md). If HIGH severity findings exist, offer to restart from Phase 3.

### Phase 6 — Deploy to AWS (Optional, target: `local` only)

For users who iterated locally and now want to deploy to AWS.

- **Structured data:** Hand off to [aws-setup](../../cloud/aws-setup/SKILL.md). Pass along the **search strategy** so it does not re-ask.
- **Unstructured data:** Chunks already exist locally. Follow the cloud steps in [unstructured_preset.md](unstructured_preset.md#target-cloud).
