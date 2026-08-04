---
name: management
description: >
  Manage and operate an OpenSearch cluster. Use this skill when the user wants
  to check cluster health, diagnose red or yellow cluster status, investigate
  unassigned shards, fix shard allocation problems, monitor node resource usage
  (JVM heap, CPU, disk), identify hot threads, configure cluster settings,
  manage index lifecycle (ISM policies, rollover, retention), set up alerting
  monitors and destinations, or perform any operational task against a running
  OpenSearch cluster. Activate when the user says: cluster health, cluster red,
  unassigned shards, node down, JVM pressure, circuit breaker tripped, ISM policy,
  rollover, index retention, alerting, monitor, slow queries, hot threads,
  cluster settings, or shard allocation.
compatibility: Requires a running OpenSearch cluster. uv required for helper scripts.
metadata:
  author: opensearch-project
  version: "1.0"
---

# Management

Category skill for operating and maintaining OpenSearch clusters.

## Skills

| Skill | Description |
|---|---|
| [cluster-operations](cluster-operations/SKILL.md) | Diagnose and fix cluster health — red/yellow status, unassigned shards, node issues, JVM pressure, circuit breakers, slow queries, shard rerouting |

## Routing

| User Intent | Skill |
|---|---|
| Cluster is red or yellow, shards unassigned, nodes down | [cluster-operations](cluster-operations/SKILL.md) |
| JVM heap pressure, circuit breaker trips, hot threads | [cluster-operations](cluster-operations/SKILL.md) |
| Slow queries, profile API, query optimization | [cluster-operations](cluster-operations/SKILL.md) |
| ISM policies, rollover, index retention, delete by age | [cluster-operations](cluster-operations/SKILL.md) |
| Set up alerting monitors, SNS/Slack notifications | [cluster-operations](cluster-operations/SKILL.md) |
| General cluster tuning, settings, shards per node | [cluster-operations](cluster-operations/SKILL.md) |

## Not Covered

This category covers **cluster operations and lifecycle management** only.
It does NOT cover:
- Building search applications → see [search/opensearch-launchpad](../search/opensearch-launchpad/SKILL.md)
- Log querying and PPL analytics → see [observability/log-analytics](../observability/log-analytics/SKILL.md)
- Distributed tracing → see [observability/trace-analytics](../observability/trace-analytics/SKILL.md)
- Document chunking → see [ingest/document-processing](../ingest/document-processing/SKILL.md)
- AWS provisioning → see [cloud/aws-setup](../cloud/aws-setup/SKILL.md)
