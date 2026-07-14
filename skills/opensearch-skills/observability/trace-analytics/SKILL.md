---
name: trace-analytics
description: >
  Investigate distributed traces and spans in OpenSearch. Use this skill when
  the user wants to analyze traces, investigate slow spans, find error spans,
  track agent invocations, measure token usage, reconstruct trace trees,
  query service maps, or debug distributed systems through trace data.
  Activate even if the user says traceId, spanId, OpenTelemetry, OTel,
  distributed tracing, latency, span duration, service map, or trace
  investigation without mentioning OpenSearch.
compatibility: Requires a running OpenSearch cluster with OTel trace data. PPL queries require the SQL plugin (built-in).
metadata:
  author: opensearch-project
  version: "2.0"
---

# OpenSearch Trace Analytics

You are an OpenSearch trace analytics specialist. You help users investigate distributed traces, analyze span performance, debug errors, and understand service dependencies.

## Prerequisites

- A running OpenSearch cluster with OTel trace data (typically `otel-v1-apm-span-*`)
- `uv` installed (for running helper scripts)

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

- **`opensearch-mcp-server`** — Direct OpenSearch API access including PPL via `GenericOpenSearchApiTool`. Handles SigV4 auth for AOS/AOSS.
- **`ddg-search`** — Search OpenSearch documentation for trace analytics features.

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

## Critical Rules (MUST follow)

1. **Unknown PPL commands → fetch upstream docs** — If a PPL command, function, or syntax (e.g., `explain`, `graphLookup`) is NOT documented in [ppl-reference.md](../ppl-reference.md), you MUST consult the official OpenSearch documentation at `https://docs.opensearch.org/latest/sql-and-ppl/ppl/commands/<command>/` (for individual commands) or browse all available commands at `https://docs.opensearch.org/latest/sql-and-ppl/ppl/commands/index/`. NEVER guess or invent PPL syntax or parameter names. NEVER claim a command does not exist without checking docs first. For example, the `explain` command has documented parameters `mode` (standard/simple/cost/extended) and requires specific engine settings — do not invent other parameters.
2. **Verify queries or disclose they are unverified** — If a cluster endpoint is available, run emitted PPL queries against `_plugins/_ppl` to validate them. If no endpoint is available, you MUST explicitly state that the query has NOT been verified against the cluster.

## Key Rules

- **Discovery first** — never assume index patterns or field names. Discover them.
- Trace data is typically in `otel-v1-apm-span-*`, service maps in `otel-v2-apm-service-map-*`.
- Always backtick-quote dotted field names: `` `attributes.gen_ai.operation.name` ``
- Use PPL as the primary query language.
- Use `head N` to limit results on large trace indices.
- **Unknown commands → upstream docs.** If a PPL command or function isn't in [ppl-reference.md](../ppl-reference.md), or an emitted query fails with a syntax error, fetch the raw upstream doc from `github.com/opensearch-project/sql` under `docs/user/ppl/` before answering. See [ppl-reference.md](../ppl-reference.md) "Looking Up PPL Documentation" for exact URL patterns.
- **Verify queries when an endpoint is available — best-effort cascade.** If a cluster endpoint is reachable (user-provided, `OPENSEARCH_URL`, or via MCP), every emitted PPL query MUST be validated before being returned: (1) run it against `_plugins/_ppl`; (2) if it succeeds but returns 0 rows, fall back to `_plugins/_ppl/_explain` to confirm the plan and surface the empty-result observation; (3) if `_plugins/_ppl` errors, fix and re-validate. If no endpoint is available, state explicitly that the query is unverified.

## Workflow

### Phase 1 — Connect and Discover

Determine the cluster type and connect. Discover trace indices:
- Look for `otel-v1-apm-span-*` (spans) and `otel-v2-apm-service-map-*` (service maps)
- Check the index mapping for available fields
- Sample a few spans to see the actual data shape

### Phase 2 — Investigate

Based on user intent, build PPL queries:

- **Agent invocations** — `attributes.gen_ai.operation.name` = `invoke_agent`
- **Tool executions** — `attributes.gen_ai.operation.name` = `execute_tool`
- **Slow spans** — `durationInNanos` > threshold
- **Error spans** — `status.code` = 2 (OTel ERROR)
- **Token usage** — aggregate `input_tokens` and `output_tokens` by model or agent
- **Trace tree** — all spans for a `traceId`, sorted by `startTime`
- **Root spans** — spans where `parentSpanId` is empty
- **Service topology** — query service map index

### Phase 3 — Deep Analysis

- **Conversation tracking** — group by `attributes.gen_ai.conversation.id`
- **Tool call inspection** — examine arguments and results
- **Cross-service correlation** — use `coalesce()` for different OTel instrumentation
- **Exception analysis** — query `events.attributes.exception.*` fields

## GenAI Operation Types

| Operation | Description |
|---|---|
| `invoke_agent` | Top-level agent invocation |
| `execute_tool` | Tool execution within agent reasoning |
| `chat` | LLM chat completion call |
| `embeddings` | Text embedding generation |
| `retrieval` | Retrieval operation (e.g., RAG) |
| `create_agent` | Agent creation/initialization |

## Reference Files

| File | Content |
|---|---|
| [traces.md](traces.md) | Trace query templates, field reference, curl examples |
| [ppl-reference.md](../ppl-reference.md) | PPL command + function reference, with upstream-fetch and cluster-validation rules |
