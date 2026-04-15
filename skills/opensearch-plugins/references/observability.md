# Observability

The Observability plugin provides tools for exploring, visualizing, and analyzing logs, traces, and metrics in OpenSearch. It includes trace analytics, metrics visualization, notebooks, and operational panels.

## Key Concepts

- **Trace analytics** — Visualize distributed traces (OpenTelemetry, Jaeger, Zipkin) stored in OpenSearch. View service maps, trace groups, latency histograms, and individual span waterfalls.
- **Service map** — A visual graph showing service dependencies and their health based on trace data.
- **Span** — A single unit of work in a distributed trace. Spans have a service name, operation, duration, status, and optional attributes.
- **Metrics** — Store and visualize time-series metrics using the Prometheus remote write integration or OpenTelemetry metrics.
- **Notebooks** — Interactive documents combining Markdown, SQL/PPL queries, and visualizations. Useful for runbooks, incident analysis, and reporting.
- **Operational panels** — Dashboards built from saved PPL visualizations for operational monitoring.
- **PPL (Piped Processing Language)** — A query language for exploring observability data. Supports commands like `stats`, `dedup`, `top`, `rare`, `eval`, `where`, and more.
- **Data Prepper** — A server-side data collector that ingests, transforms, and routes observability data (traces, logs, metrics) into OpenSearch. Supports OpenTelemetry, Fluent Bit, and other sources.

## Common Use Cases

- Investigating slow or failed requests using trace analytics
- Building service maps to understand microservice dependencies
- Creating operational dashboards from log and metric data
- Writing interactive runbooks as notebooks
- Ingesting OpenTelemetry traces and metrics via Data Prepper

## Guides

- [Agent tracing](https://docs.opensearch.org/latest/observing-your-data/agent-traces/index/) — Trace and debug ML agent executions (links to instrumentation guide)
- [Application map](https://docs.opensearch.org/latest/observing-your-data/apm/application-map/) — Visualize service dependencies and health

## Official Documentation

- [Observability overview](https://docs.opensearch.org/latest/observing-your-data/index/)
- [Trace analytics](https://docs.opensearch.org/latest/observing-your-data/trace/index/)
- [Metrics](https://docs.opensearch.org/latest/observing-your-data/prometheusmetrics/)
- [Notebooks](https://docs.opensearch.org/latest/observing-your-data/notebooks/)
- [Operational panels](https://docs.opensearch.org/latest/observing-your-data/operational-panels/)
- [Data Prepper](https://docs.opensearch.org/latest/data-prepper/index/)
- [PPL reference](https://docs.opensearch.org/latest/sql-and-ppl/ppl/index/)
