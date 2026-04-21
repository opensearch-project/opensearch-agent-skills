# OpenSearch Log Analytics Guide

## Overview

This guide instructs you on how to perform log analytics against an existing OpenSearch cluster. The approach is discovery-first: understand what indices exist, learn the schema, sample the data, then build queries. Do not assume any particular index pattern or field names — discover them.

## Connecting to the Cluster

Before proceeding, determine the cluster type. If it's not clear from context, ask the user:

- "Is your OpenSearch cluster running locally, on Amazon OpenSearch Service (managed), or Amazon OpenSearch Serverless?"
- "What is the endpoint URL?"
- "How do you authenticate — username/password, AWS IAM role, or AWS profile?"

This is important because the connection method, authentication, and available features differ between local, AOS, and AOSS clusters.

### Preferred: opensearch-mcp-server (handles AOS/AOSS auth automatically)

If the `opensearch-mcp-server` MCP server is available, prefer its tools over curl — they handle SigV4 authentication for Amazon OpenSearch Service (AOS) and Serverless (AOSS) transparently. Key tools:

- `ListIndexTool` — list indices with doc counts and sizes
- `IndexMappingTool` — get index mappings and settings
- `SearchIndexTool` — search with Query DSL
- `GenericOpenSearchApiTool` — call any OpenSearch API (including `/_plugins/_ppl` for PPL queries)

If the MCP server is not available, follow the auto-install instructions in the main SKILL.md — it covers endpoint collection, auth configuration for local/AOS/AOSS, and IDE restart.

### Fallback: curl (local clusters or basic auth)

For local clusters with basic auth, use curl with `-sk -u` flags. All curl examples in this guide use environment variables:

| Variable | Default | Description |
|---|---|---|
| `OPENSEARCH_ENDPOINT` | `https://localhost:9200` | OpenSearch base URL |
| `OPENSEARCH_USER` | `admin` | OpenSearch username |
| `OPENSEARCH_PASSWORD` | `My_password_123!@#` | OpenSearch password |

> For AOS/AOSS endpoints, curl requires `--aws-sigv4` which needs AWS credentials configured. The MCP server is simpler — use it when available.

## Phase 1 — Discover Available Indices

Before writing any query, find out what log indices exist on the cluster.

### List All Indices

Via MCP server:
```
Use ListIndexTool to list all indices
```

Via curl:
```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  "$OPENSEARCH_ENDPOINT/_cat/indices?format=json&h=index,health,docs.count,store.size&s=docs.count:desc"
```

Look for indices that suggest logs: names containing `log`, `logs`, `events`, `audit`, `access`, `syslog`, `otel`, `cwl` (CloudWatch Logs), or date-based patterns like `logs-2024.01.15`.

### List Index Patterns with Aliases

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  "$OPENSEARCH_ENDPOINT/_cat/aliases?format=json&h=alias,index&s=alias"
```

### Check Data Streams

Modern log setups may use data streams instead of plain indices:

Via MCP server:
```
Use GenericOpenSearchApiTool with path="/_data_stream" and method="GET"
```

Via curl:
```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  "$OPENSEARCH_ENDPOINT/_data_stream?pretty"
```

After discovering indices, ask the user which index or index pattern they want to analyze if it's not obvious. If there are multiple log indices, ask about the relationship between them (e.g., are they daily rollover indices for the same data? different applications? different log levels?).

## Phase 2 — Understand the Schema

Once you know the target index pattern, inspect its mapping to learn the available fields.

### Get Index Mapping

Via MCP server:
```
Use IndexMappingTool with index="<INDEX_PATTERN>"
```

Via curl:
```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  "$OPENSEARCH_ENDPOINT/<INDEX_PATTERN>/_mapping?pretty"
```

Via PPL:

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "describe <INDEX_NAME>"}'
```

> Use a concrete index name (e.g., `logs-2024.01.15`) for `describe`, not a wildcard pattern.

### Identify Key Fields

From the mapping, identify:

1. **Timestamp field** — usually `@timestamp`, `timestamp`, `time`, or `event.created`
2. **Log level field** — `level`, `log.level`, `severity`, `severityText`, `loglevel`
3. **Message field** — `message`, `msg`, `body`, `log`, `event.original`
4. **Service/source field** — `service`, `service.name`, `host.name`, `source`, `kubernetes.pod.name`, `resource.attributes.service.name`
5. **Error fields** — `error.message`, `error.stack_trace`, `exception.type`
6. **Correlation fields** — `traceId`, `trace_id`, `spanId`, `request_id`, `correlation_id`

If the mapping is large or unclear, ask the user: "I see fields like X, Y, Z — which field contains the log message? Which one is the log level?"

### Sample Documents

Always look at a few real documents to understand the actual data shape — mappings alone can be misleading (e.g., dynamic fields, nested objects, multi-value fields):

Via MCP server:
```
Use SearchIndexTool with index="<INDEX_PATTERN>" and query={"size": 5, "sort": [{"<TIMESTAMP_FIELD>": "desc"}]}
```

Or use GenericOpenSearchApiTool for PPL:
```
Use GenericOpenSearchApiTool with path="/_plugins/_ppl", method="POST", body={"query": "source=<INDEX_PATTERN> | head 5"}
```

Via curl (PPL):
```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=<INDEX_PATTERN> | head 5"}'
```

Review the sample documents to confirm:
- Which fields are actually populated (vs defined but empty)
- The format of timestamps, log levels, and messages
- Whether the message field is structured JSON or free-text
- Whether there are nested objects that need backtick-quoting in PPL

## Phase 3 — Ask Clarifying Questions (If Needed)

If the schema is not self-explanatory, ask the user:

- "What does this index contain? Application logs, access logs, audit logs?"
- "I see multiple log indices (X, Y, Z) — are these from different services or different time periods?"
- "The message field appears to contain JSON — should I parse specific fields from it?"
- "I see a `trace_id` field — do you want to correlate logs with traces?"
- "What time range are you interested in?"

Do not skip this step if the data is ambiguous. Getting the schema right upfront saves failed queries later.

## Phase 4 — Perform Analytics

With the schema understood, build PPL queries using the actual field names discovered above. All examples below use placeholder field names — substitute with the real ones.

### Running PPL Queries

Via MCP server (preferred for AOS/AOSS):
```
Use GenericOpenSearchApiTool with path="/_plugins/_ppl", method="POST", body={"query": "<PPL_QUERY>"}
```

Via curl (local clusters):
```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "<PPL_QUERY>"}'
```

### Log Volume Over Time

```
source=<INDEX_PATTERN> | stats count() as volume by span(<TIMESTAMP_FIELD>, 1h)
```

### Error Count by Service

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | stats count() as errors by <SERVICE_FIELD> | sort - errors
```

### Error Rate Trend

```
source=<INDEX_PATTERN> | stats count() as total, sum(case(<LEVEL_FIELD> = 'ERROR', 1 else 0)) as errors by span(<TIMESTAMP_FIELD>, 1h)
```

### Recent Errors

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | fields <TIMESTAMP_FIELD>, <SERVICE_FIELD>, <MESSAGE_FIELD> | sort - <TIMESTAMP_FIELD> | head 20
```

### Full-Text Search

```
source=<INDEX_PATTERN> | where match(<MESSAGE_FIELD>, 'connection timeout') | sort - <TIMESTAMP_FIELD> | head 20
```

### Top Error Messages

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | top 10 <MESSAGE_FIELD>
```

### Rare Error Messages

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | rare <MESSAGE_FIELD>
```

### Log Pattern Discovery

Automatically cluster similar log messages:

```
source=<INDEX_PATTERN> | where <LEVEL_FIELD> = 'ERROR' | patterns <MESSAGE_FIELD> | fields <MESSAGE_FIELD>, patterns_field | head 30
```

### Error Breakdown by Level and Service

```
source=<INDEX_PATTERN> | stats count() by <LEVEL_FIELD>, <SERVICE_FIELD>
```

### Time-Filtered Queries

```
source=<INDEX_PATTERN> | where <TIMESTAMP_FIELD> > DATE_SUB(NOW(), INTERVAL 1 HOUR) | stats count() by <LEVEL_FIELD>
```

### Unique Services/Hosts

```
source=<INDEX_PATTERN> | stats distinct_count(<SERVICE_FIELD>) as services, distinct_count(<HOST_FIELD>) as hosts
```

### Latency from Structured Logs

If logs contain a duration/latency field:

```
source=<INDEX_PATTERN> | stats avg(<DURATION_FIELD>) as avg_ms, percentile(<DURATION_FIELD>, 95) as p95_ms, percentile(<DURATION_FIELD>, 99) as p99_ms by <SERVICE_FIELD>
```

### Extract Fields from Unstructured Messages

If the message field contains unstructured text, use grok or parse to extract fields:

```
source=<INDEX_PATTERN> | grok <MESSAGE_FIELD> '%{IP:client_ip} %{WORD:method} %{URIPATHPARAM:path} %{NUMBER:status}' | stats count() by status
```

> **Caveat:** `grok` processes all matching rows in memory. Add `| head N` before `grok` on large indices to avoid resource errors.

## Phase 5 — Advanced Analysis

### Cross-Index Correlation

If logs span multiple indices (e.g., application logs + access logs), correlate using shared fields like `request_id`, `trace_id`, or timestamp proximity:

Step 1 — Find an event of interest in one index:

```
source=<APP_LOGS> | where <LEVEL_FIELD> = 'ERROR' | fields <CORRELATION_FIELD>, <TIMESTAMP_FIELD>, <MESSAGE_FIELD> | head 10
```

Step 2 — Look up the same correlation ID in the other index:

```
source=<ACCESS_LOGS> | where <CORRELATION_FIELD> = '<VALUE>' | fields <TIMESTAMP_FIELD>, <MESSAGE_FIELD>
```

### Anomaly Detection

Use PPL's built-in anomaly detection on numeric fields (e.g., log volume, error count):

```
source=<INDEX_PATTERN> | stats count() as volume by span(<TIMESTAMP_FIELD>, 5m) | ad time_field=<TIMESTAMP_FIELD>
```

> The `ad` command auto-detects input fields from the pipeline. It works best on time-series data with regular intervals.

### Query DSL for Complex Aggregations

For queries that PPL doesn't support well (nested aggregations, scripted fields), fall back to Query DSL:

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/<INDEX_PATTERN>/_search" \
  -H 'Content-Type: application/json' \
  -d '{
    "size": 0,
    "query": {
      "bool": {
        "must": [{"match": {"<LEVEL_FIELD>": "ERROR"}}],
        "filter": [{"range": {"<TIMESTAMP_FIELD>": {"gte": "now-1h"}}}]
      }
    },
    "aggs": {
      "by_service": {
        "terms": {"field": "<SERVICE_FIELD>", "size": 20},
        "aggs": {
          "over_time": {
            "date_histogram": {"field": "<TIMESTAMP_FIELD>", "fixed_interval": "5m"}
          }
        }
      }
    }
  }'
```

## Common Log Schemas Reference

When you encounter these common schemas, use the field mappings below:

### Elastic Common Schema (ECS)

Timestamp: `@timestamp`, Level: `log.level`, Message: `message`, Service: `service.name`, Host: `host.name`, Error: `error.message`

### OTel Logs (logs-otel-v1-*)

Timestamp: `@timestamp`, Level: `severityText`, Message: `body`, Service: `` `resource.attributes.service.name` `` (backtick-quoted), Trace: `traceId`, Span: `spanId`

### Simple JSON Logs

Timestamp: `timestamp` or `@timestamp`, Level: `level`, Message: `message` or `msg`, Service: `service`, Host: `host`

### Syslog

Timestamp: `@timestamp`, Level: `severity`, Message: `message`, Host: `host`, Program: `program`, Facility: `facility`

### Apache/Nginx Access Logs

Client: `clientip`, Request: `request`, Status: `response`, Bytes: `bytes`, Method: `verb`, Agent: `agent`

## Key PPL Tips for Log Analytics

- Always backtick-quote dotted field names: `` `log.level` ``, `` `host.name` ``
- Use `head N` before memory-intensive commands (`grok`, `streamstats`, `eventstats`)
- Use `span(<timestamp>, <interval>)` for time bucketing — common intervals: `5m`, `15m`, `1h`, `1d`
- Use `match()` for full-text search, `like` for wildcard patterns, `match_phrase()` for exact phrases
- Use `patterns` for automatic log message clustering
- Use `dedup` to find unique error messages: `dedup <MESSAGE_FIELD> | fields <MESSAGE_FIELD>`
- See [ppl-reference.md](../ppl-reference.md) for the full PPL command and function reference
- If a PPL query fails with a syntax error, search the docs: `uv run python scripts/opensearch_ops.py search-docs --query "PPL <command> syntax"`