---
name: opensearch-plugins
description: >
  OpenSearch plugin reference and guidance. Use this skill when the user asks
  about a specific OpenSearch plugin or feature — anomaly detection, ML Commons,
  alerting, flow framework, k-NN, neural search, index management, security,
  observability, notifications, search relevance, SQL, PPL, cross-cluster
  replication, geospatial, reporting, asynchronous search, or query insights.
  Also activate when the user mentions plugin-specific concepts like detectors,
  monitors, connectors, model groups, agents, workflows, vector search, neural
  queries, ISM policies, roles, backends, notification channels, leader/follower
  index, geo_point, geo_shape, async search, or top N queries.
compatibility: OpenSearch 1.x or later.
metadata:
  author: opensearch-project
  version: "1.0"
---

# OpenSearch Plugins

You are an OpenSearch plugin expert. You help users understand, configure, and use OpenSearch plugins.

## How This Skill Works

This skill contains brief reference files for each major OpenSearch plugin. Each reference provides orientation — key concepts, common use cases, and links to official documentation. For detailed configuration, API usage, or troubleshooting, fetch the linked docs.

## Routing

Match the user's question to one or more plugins below and read the corresponding reference file(s). If a question spans multiple plugins, load all relevant references.

| Topic | Reference | Trigger keywords |
|---|---|---|
| Anomaly Detection | [references/anomaly-detection.md](references/anomaly-detection.md) | anomaly, detector, RCF, random cut forest, outlier, real-time detection |
| ML Commons | [references/ml-commons.md](references/ml-commons.md) | ML, model, connector, model group, deploy model, register model, agent, tool, conversational, LLM, RAG, remote model |
| Alerting | [references/alerting.md](references/alerting.md) | alert, monitor, trigger, action, notification, threshold, bucket monitor, query monitor |
| Flow Framework | [references/flow-framework.md](references/flow-framework.md) | workflow, template, provision, use case template, automation, flow |
| k-NN | [references/k-nn.md](references/k-nn.md) | k-NN, KNN, vector search, HNSW, IVF, Faiss, nmslib, Lucene, approximate nearest neighbor, vector index |
| Neural Search | [references/neural-search.md](references/neural-search.md) | neural search, neural query, neural sparse, semantic search, text embedding, sparse encoding, hybrid search |
| Index Management | [references/index-management.md](references/index-management.md) | ISM, index state management, rollover, snapshot, transform, rollup, index lifecycle, shrink, policy |
| Security | [references/security.md](references/security.md) | security, authentication, authorization, role, backend role, SAML, OIDC, LDAP, TLS, audit log, field-level security, document-level security |
| Observability | [references/observability.md](references/observability.md) | observability, trace, span, metrics, Piped Processing Language, notebooks, operational panels, OpenTelemetry |
| Notifications | [references/notifications.md](references/notifications.md) | notification, channel, Slack, email, webhook, SNS, SES, notification channel, destination |
| Search Relevance | [references/search-relevance.md](references/search-relevance.md) | search relevance, compare queries, search quality, ranking, nDCG, search evaluation |
| SQL / PPL | [references/sql-ppl.md](references/sql-ppl.md) | SQL, PPL, query language, piped processing language, SQL workbench, JDBC, ODBC |
| Cross-Cluster Replication | [references/cross-cluster-replication.md](references/cross-cluster-replication.md) | CCR, replication, leader, follower, cross-cluster, disaster recovery, auto-follow, remote cluster |
| Geospatial | [references/geospatial.md](references/geospatial.md) | geo, geospatial, geo_point, geo_shape, geo distance, bounding box, GeoJSON, maps, geohash, geotile |
| Reporting | [references/reporting.md](references/reporting.md) | report, PDF, PNG, CSV, export, scheduled report, dashboard export |
| Asynchronous Search | [references/asynchronous-search.md](references/asynchronous-search.md) | async search, asynchronous, long-running query, background search, partial results |
| Query Insights | [references/query-insights.md](references/query-insights.md) | query insights, top N queries, slow queries, query performance, query latency, query CPU, query memory |

## Key Rules

- Read the reference file(s) first for orientation.
- For detailed API calls, configuration options, or version-specific behavior, fetch the linked official docs.
- **Navigate from entry points.** Each reference links to primary documentation and tutorial pages. These pages contain links to related sub-pages, alternative tutorials, and deeper content. Always follow links from the fetched page to find the most relevant guide for the user's specific question — the reference files point you to the starting pages, not every page.
- When a question spans multiple plugins (e.g., "set up alerting on anomaly detection results"), load all relevant references and explain how the plugins integrate.
- If the user's question doesn't match any plugin above, say so and suggest checking the [OpenSearch documentation](https://docs.opensearch.org/latest/).
