# Query Insights

The Query Insights plugin provides monitoring and analysis of search query performance. It captures top N queries by latency, CPU, and memory, enabling identification of slow queries and optimization opportunities.

## Key Concepts

- **Top N queries** — Track the slowest, most CPU-intensive, or most memory-intensive queries over a configurable time window. Results are available via API and OpenSearch Dashboards.
- **Query metric types** — Three dimensions for ranking queries:
  - **Latency** — Total time to execute the query.
  - **CPU** — CPU time consumed by the query.
  - **Memory** — Heap memory used by the query.
- **Time window** — The rolling window for collecting top N queries (e.g., last 1 minute, 5 minutes, 1 hour). Configurable per metric type.
- **Window size (N)** — How many top queries to retain per window. Default is typically 3-10.
- **Query grouping** — Group similar queries together (by query shape/template) to identify patterns rather than individual query instances.
- **Exporters** — Send query insights data to external sinks (local index, debug log) for longer retention and analysis.
- **Dashboards integration** — View top N queries, query trends, and performance details in the OpenSearch Dashboards Query Insights UI.

## Common Use Cases

- Identifying slow queries that degrade cluster performance
- Finding resource-heavy queries that consume excessive CPU or memory
- Monitoring query performance trends over time
- Optimizing query patterns by analyzing grouped query shapes
- Capacity planning based on query resource consumption

## Guides

- [Query Insights dashboard](https://docs.opensearch.org/latest/observing-your-data/query-insights/query-insights-dashboard/) — Using the Dashboards UI to explore query performance
- [Live queries](https://docs.opensearch.org/latest/observing-your-data/query-insights/live-queries/) — Monitor currently running queries in real time
- [Query health](https://docs.opensearch.org/latest/observing-your-data/query-insights/health/) — Cluster query health monitoring

## Official Documentation

- [Query insights overview](https://docs.opensearch.org/latest/observing-your-data/query-insights/index/)
- [Top N queries](https://docs.opensearch.org/latest/observing-your-data/query-insights/top-n-queries/)
- [Query grouping](https://docs.opensearch.org/latest/observing-your-data/query-insights/grouping-top-n-queries/)
- [Query metrics](https://docs.opensearch.org/latest/observing-your-data/query-insights/query-metrics/)
- [Settings and API](https://docs.opensearch.org/latest/observing-your-data/query-insights/settings-api/)
