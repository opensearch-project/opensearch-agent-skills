---
name: observability
description: >
  Analyze logs, investigate traces, and run falsification-driven incident
  investigations in OpenSearch. Use this skill when the user wants to query
  logs with PPL, analyze error patterns, discover log patterns, investigate
  traces, check stack health, perform root-cause analysis across multiple
  signals, or perform any observability task. Activate even if the user says
  log analysis, Fluent Bit, Fluentd, Logstash, syslog, traceId, OpenTelemetry,
  PPL, span, latency, error rate, anomaly detection, root cause, RCA,
  postmortem, or log analytics without mentioning OpenSearch.
compatibility: Requires a running OpenSearch cluster. PPL queries require the SQL plugin (built-in).
metadata:
  author: opensearch-project
  version: "2.0"
---

# Observability

Category skill for log analytics, trace investigation, and incident root-cause analysis with OpenSearch.

## Skills

| Skill | Description |
|---|---|
| [log-analytics](log-analytics/SKILL.md) | Query and analyze log data — error patterns, log volume, anomaly detection, PPL queries |
| [trace-analytics](trace-analytics/SKILL.md) | Investigate distributed traces — slow spans, error spans, service maps, agent invocations |
| [popperian-sre](popperian-sre/SKILL.md) | Falsification-driven incident investigation — generates competing hypotheses, designs evidence queries meant to disprove each one, and refuses to recommend remediation when evidence is insufficient |

## When to Use

| User Intent | Skill |
|---|---|
| Query logs, analyze errors, discover patterns, check log volume | [log-analytics](log-analytics/SKILL.md) |
| Investigate traces, debug spans, analyze latency, service dependencies | [trace-analytics](trace-analytics/SKILL.md) |
| Both logs and traces (e.g., correlate errors with spans) | Start with the primary intent, cross-reference using `traceId` |
| "Why did X happen" / root-cause an incident across multiple signals / weigh competing explanations before recommending a fix | [popperian-sre](popperian-sre/SKILL.md) |
