---
name: observability
description: >
  Analyze logs and investigate traces in OpenSearch. Use this skill when the
  user wants to query logs with PPL, analyze error patterns, discover log
  patterns, investigate traces, check stack health, or perform any
  observability task. Activate even if the user says log analysis, Fluent Bit,
  Fluentd, Logstash, syslog, traceId, OpenTelemetry, PPL, span, latency,
  error rate, anomaly detection, or log analytics without mentioning OpenSearch.
compatibility: Requires a running OpenSearch cluster. PPL queries require the SQL plugin (built-in).
metadata:
  author: opensearch-project
  version: "2.0"
---

# Observability

Category skill for log analytics and trace investigation with OpenSearch.

## Skills

| Skill | Description |
|---|---|
| [log-analytics](log-analytics/SKILL.md) | Query and analyze log data — error patterns, log volume, anomaly detection, PPL queries |
| [trace-analytics](trace-analytics/SKILL.md) | Investigate distributed traces — slow spans, error spans, service maps, agent invocations |

## When to Use

| User Intent | Skill |
|---|---|
| Query logs, analyze errors, discover patterns, check log volume | [log-analytics](log-analytics/SKILL.md) |
| Investigate traces, debug spans, analyze latency, service dependencies | [trace-analytics](trace-analytics/SKILL.md) |
| Both logs and traces (e.g., correlate errors with spans) | Start with the primary intent, cross-reference using `traceId` |
