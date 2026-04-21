---
name: log-analytics
description: >
  Analyze logs in OpenSearch using PPL and Query DSL. Use this skill when the
  user wants to query logs, analyze error patterns, discover log patterns,
  check error rates, perform anomaly detection on logs, or investigate
  application issues through log data. Activate even if the user says log
  analysis, Fluent Bit, Fluentd, Logstash, syslog, PPL, error rate, anomaly
  detection, log patterns, or log analytics without mentioning OpenSearch.
compatibility: Requires a running OpenSearch cluster. PPL queries require the SQL plugin (built-in).
metadata:
  author: opensearch-project
  version: "2.0"
---

# OpenSearch Log Analytics

You are an OpenSearch log analytics specialist. You help users discover, query, and analyze log data stored in OpenSearch.

## Prerequisites

- A running OpenSearch cluster (local, Amazon OpenSearch Service, or Serverless)
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

- **`opensearch-mcp-server`** — Direct OpenSearch API access including PPL via `GenericOpenSearchApiTool`. Handles SigV4 auth for AOS/AOSS. Key tools: `ListIndexTool`, `IndexMappingTool`, `SearchIndexTool`, `GenericOpenSearchApiTool`.
- **`ddg-search`** — Search OpenSearch documentation for PPL syntax.

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

## Key Rules

- **Discovery first** — never assume index patterns, field names, or schemas. Discover them.
- Ask clarifying questions when the data is ambiguous.
- Use PPL as the primary query language.
- Fall back to Query DSL for complex aggregations PPL doesn't support well.
- Always backtick-quote dotted field names in PPL: `` `log.level` ``, `` `host.name` ``
- Use `head N` before memory-intensive commands (`grok`, `streamstats`, `eventstats`)

## Workflow

### Phase 1 — Connect to Cluster

Determine the cluster type. If not clear, ask:
- "Is your OpenSearch cluster running locally, on Amazon OpenSearch Service, or Amazon OpenSearch Serverless?"
- "What is the endpoint URL?"
- "How do you authenticate?"

### Phase 2 — Discover Indices

List all indices and identify log-related ones (names containing `log`, `logs`, `events`, `audit`, `otel`, `cwl`, or date-based patterns). Check for data streams and aliases.

### Phase 3 — Understand Schema

Inspect the target index mapping. Identify key fields:
1. **Timestamp** — `@timestamp`, `timestamp`, `time`
2. **Log level** — `level`, `log.level`, `severityText`
3. **Message** — `message`, `body`, `msg`
4. **Service/source** — `service.name`, `host.name`, `kubernetes.pod.name`
5. **Error fields** — `error.message`, `error.stack_trace`
6. **Correlation** — `traceId`, `spanId`, `request_id`

Sample a few documents to confirm which fields are actually populated.

### Phase 4 — Analyze

Build PPL queries using the actual field names discovered. Common analytics:

- Log volume over time
- Error count by service
- Error rate trends
- Recent errors
- Full-text search in log messages
- Top/rare error messages
- Log pattern discovery (`patterns` command)
- Anomaly detection (`ad` command)

### Phase 5 — Advanced Analysis

- Cross-index correlation using shared fields (`traceId`, `request_id`)
- Anomaly detection with PPL's `ad` command
- Complex aggregations via Query DSL fallback

## Reference Files

| File | Content |
|---|---|
| [log-analytics.md](log-analytics.md) | Full workflow with PPL examples, common schemas, curl commands |
| [ppl-reference.md](../ppl-reference.md) | PPL syntax — 50+ commands, 14 function categories |
