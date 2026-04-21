# Trace Querying with PPL

## Overview

PPL query templates for investigating trace data in OpenSearch. Traces are stored in `otel-v1-apm-span-*`, service maps in `otel-v2-apm-service-map-*`. All queries use the PPL API at `/_plugins/_ppl` with HTTPS and basic auth.

## Base Command

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "<PPL_QUERY>"}'
```

## Trace Index Key Fields

| Field | Type | Description |
|---|---|---|
| `traceId` | keyword | Unique 128-bit trace identifier |
| `spanId` | keyword | Unique 64-bit span identifier |
| `parentSpanId` | keyword | Parent span ID (empty for root spans) |
| `serviceName` | keyword | Service that produced the span |
| `name` | text | Span operation name |
| `kind` | keyword | Span kind (SERVER, CLIENT, INTERNAL, PRODUCER, CONSUMER) |
| `startTime` | date | Span start timestamp |
| `endTime` | date | Span end timestamp |
| `durationInNanos` | long | Span duration in nanoseconds |
| `status.code` | integer | 0=Unset, 1=Ok, 2=Error |
| `attributes.gen_ai.operation.name` | keyword | GenAI operation type |
| `attributes.gen_ai.agent.name` | keyword | Agent name |
| `attributes.gen_ai.agent.id` | keyword | Agent identifier |
| `attributes.gen_ai.request.model` | keyword | Requested model |
| `attributes.gen_ai.usage.input_tokens` | long | Input token count |
| `attributes.gen_ai.usage.output_tokens` | long | Output token count |
| `attributes.gen_ai.tool.name` | keyword | Tool name |
| `attributes.gen_ai.tool.call.id` | keyword | Tool call identifier |
| `attributes.gen_ai.tool.call.arguments` | text | Tool call arguments (JSON) |
| `attributes.gen_ai.tool.call.result` | text | Tool call result (JSON) |
| `attributes.gen_ai.conversation.id` | keyword | Conversation identifier |
| `attributes.error_type` | keyword | Error type category |
| `events.attributes.exception.type` | keyword | Exception class/type |
| `events.attributes.exception.message` | text | Exception message |
| `events.attributes.exception.stacktrace` | text | Exception stacktrace |

## Agent Invocation Spans

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = '\''invoke_agent'\'' | fields traceId, spanId, `attributes.gen_ai.agent.name`, `attributes.gen_ai.request.model`, durationInNanos, startTime | sort - startTime | head 20"}'
```

## Tool Execution Spans

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = '\''execute_tool'\'' | fields traceId, spanId, `attributes.gen_ai.tool.name`, durationInNanos, startTime | sort - startTime | head 20"}'
```

## Slow Spans

Default threshold: 5 seconds (5,000,000,000 nanoseconds). Adjust as needed:

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where durationInNanos > 5000000000 | fields traceId, spanId, serviceName, name, durationInNanos, startTime | sort - durationInNanos | head 20"}'
```

## Error Spans

`status.code` = 2 means ERROR in OTel:

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `status.code` = 2 | fields traceId, spanId, serviceName, name, `status.code`, startTime | sort - startTime | head 20"}'
```

## Token Usage by Model

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.usage.input_tokens` > 0 | stats sum(`attributes.gen_ai.usage.input_tokens`) as total_input, sum(`attributes.gen_ai.usage.output_tokens`) as total_output by `attributes.gen_ai.request.model`"}'
```

## Token Usage by Agent

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.usage.input_tokens` > 0 | stats sum(`attributes.gen_ai.usage.input_tokens`) as total_input, sum(`attributes.gen_ai.usage.output_tokens`) as total_output by `attributes.gen_ai.agent.name`"}'
```

## Service Operations Listing

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | stats count() by serviceName, `attributes.gen_ai.operation.name`"}'
```

## Service Map Queries

> **Important:** `sourceNode`, `targetNode`, `sourceOperation`, `targetOperation` in `otel-v2-apm-service-map-*` are nested struct objects, not flat strings. Each node has `keyAttributes.name` for the service name.

### Service Topology

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v2-apm-service-map-* | dedup nodeConnectionHash | fields sourceNode, targetNode, sourceOperation, targetOperation"}'
```

## Remote Service Identification with coalesce()

Different OTel instrumentation libraries use different attributes. Use `coalesce()` to check multiple fields:

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where serviceName = '\''frontend'\'' | where kind = '\''SPAN_KIND_CLIENT'\'' | eval _remoteService = coalesce(`attributes.net.peer.name`, `attributes.server.address`, `attributes.rpc.service`, `attributes.db.system`, `attributes.gen_ai.system`, '\''unknown'\'') | stats count() as calls by _remoteService | sort - calls"}'
```

## Trace Tree Reconstruction

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where traceId = '\''<TRACE_ID>'\'' | fields traceId, spanId, parentSpanId, serviceName, name, startTime, endTime, durationInNanos, `status.code` | sort startTime"}'
```

## Root Span Identification

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where traceId = '\''<TRACE_ID>'\'' AND parentSpanId = '\'''\'' | fields traceId, spanId, serviceName, name, durationInNanos, startTime, endTime"}'
```

## GenAI Operation Types

| Operation | Description |
|---|---|
| `invoke_agent` | Top-level agent invocation |
| `execute_tool` | Tool execution within agent reasoning |
| `chat` | LLM chat completion call |
| `embeddings` | Text embedding generation |
| `retrieval` | Retrieval operation (e.g., RAG) |
| `create_agent` | Agent creation/initialization |
| `text_completion` | Text completion (non-chat) |
| `generate_content` | Generic content generation |

## Exception and Error Querying

### Spans with Exceptions

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `status.code` = 2 | fields traceId, spanId, serviceName, name, `events.attributes.exception.type`, `events.attributes.exception.message`, `attributes.error_type`, startTime | sort - startTime | head 20"}'
```

## Conversation Tracking

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.conversation.id` != '\'''\'' | stats count() as turns, sum(`attributes.gen_ai.usage.input_tokens`) as total_input_tokens, sum(`attributes.gen_ai.usage.output_tokens`) as total_output_tokens by `attributes.gen_ai.conversation.id`"}'
```

## Tool Call Inspection

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = '\''execute_tool'\'' | fields traceId, spanId, `attributes.gen_ai.tool.name`, `attributes.gen_ai.tool.call.id`, `attributes.gen_ai.tool.call.arguments`, `attributes.gen_ai.tool.call.result`, durationInNanos, startTime | sort - startTime | head 20"}'
```

## AWS Managed OpenSearch

Replace local endpoint with SigV4:

```bash
curl -s --aws-sigv4 "aws:amz:REGION:es" \
  --user "$AWS_ACCESS_KEY_ID:$AWS_SECRET_ACCESS_KEY" \
  -X POST https://DOMAIN-ID.REGION.es.amazonaws.com/_plugins/_ppl \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `attributes.gen_ai.operation.name` = '\''invoke_agent'\'' | head 20"}'
```
