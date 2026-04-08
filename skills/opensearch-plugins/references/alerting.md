# Alerting

The Alerting plugin lets you define monitors that periodically check your data against conditions and trigger notifications when those conditions are met. It supports per-query, per-bucket, per-cluster-metrics, and per-document monitors.

## Key Concepts

- **Monitor** — A scheduled job that runs a query or checks cluster metrics. Four types:
  - **Per-query monitor** — Runs a single query and evaluates the results against triggers.
  - **Per-bucket monitor** — Runs an aggregation query and evaluates each bucket independently.
  - **Per-document monitor** — Evaluates conditions per document using document-level queries.
  - **Per-cluster-metrics monitor** — Checks cluster health, node stats, or other cluster-level metrics.
- **Trigger** — A condition attached to a monitor (e.g., "count > 100" or "avg(cpu) > 90"). When the condition is met, the trigger fires.
- **Action** — What to do when a trigger fires — send a message to a notification channel.
- **Notification channel** — The destination for alert messages (Slack, email, webhook, SNS, etc.). Configured via the Notifications plugin.
- **Alert** — A record created when a trigger fires. Alerts have states: Active, Acknowledged, Completed, Error, Deleted.
- **Composite monitor** — Chains multiple monitors with AND/OR logic using a workflow.

## Common Use Cases

- Alerting on error log spikes (per-query or per-document)
- Monitoring application latency thresholds per service (per-bucket)
- Cluster health checks (per-cluster-metrics)
- Composite alerts that combine multiple conditions

## Guides

- [Dashboards alerting](https://docs.opensearch.org/latest/observing-your-data/alerting/dashboards-alerting/) — Create and manage monitors through the Dashboards UI
- [Per-document monitors](https://docs.opensearch.org/latest/observing-your-data/alerting/per-document-monitors/) — Document-level alerting walkthrough
- [Per-cluster-metrics monitors](https://docs.opensearch.org/latest/observing-your-data/alerting/per-cluster-metrics-monitors/) — Cluster health monitoring

## Official Documentation

- [Alerting overview](https://docs.opensearch.org/latest/observing-your-data/alerting/index/)
- [Monitors](https://docs.opensearch.org/latest/observing-your-data/alerting/monitors/)
- [Triggers](https://docs.opensearch.org/latest/observing-your-data/alerting/triggers/)
- [Actions](https://docs.opensearch.org/latest/observing-your-data/alerting/actions/)
- [Composite monitors](https://docs.opensearch.org/latest/observing-your-data/alerting/composite-monitors/)
- [API reference](https://docs.opensearch.org/latest/observing-your-data/alerting/api/)
- [Security configuration](https://docs.opensearch.org/latest/observing-your-data/alerting/security/)
