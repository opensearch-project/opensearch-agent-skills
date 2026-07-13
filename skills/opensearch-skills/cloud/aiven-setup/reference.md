# Aiven for OpenSearch Deployment Reference

Reference material for plan sizing, cost, TLS, HA, and operations. Load only when the user asks about these topics.

## Plans and Sizing

Aiven OpenSearch is billed per **plan** (a fixed bundle of nodes + CPU + RAM + disk), not per compute unit. Plan families:

- **Hobbyist / Startup** — single node, dev/test and small workloads.
- **Business** — multi-node with high availability (replicas across nodes).
- **Premium** — larger multi-node clusters for production scale.

Always call `aiven_service_type_plans` (`service_type="opensearch"`) for the live list, exact sizes, and per-plan pricing/regions — do not hardcode. Let the user choose.

## Cost

- Billed hourly at the plan's rate for as long as the service exists (not per-query).
- Larger plans = more nodes/CPU/RAM/disk = higher hourly cost.
- Cost levers: right-size the plan, power the service off when idle (dev), and use the `aiven_service_plan_pricing` tool to compare before committing.
- New Aiven accounts typically include trial credits — a small plan can run for evaluation at no cost until credits are exhausted.

## TLS / CA Handling

Aiven fronts services with a **project-level self-signed CA**. Two options for `opensearch-mcp-server`:

1. **Dev / quick start** — `OPENSEARCH_SSL_VERIFY=false`. Skips verification; acceptable for local experimentation only.
2. **Verified TLS (recommended for anything real)** — download the project CA and point the client at it:
   - Aiven Console: **Project → Settings → CA certificate**, or
   - Aiven CLI: `avn project ca-get --project <project>`
   
   Then supply it to the client (e.g. `OPENSEARCH_SSL_VERIFY=true` with the CA on the trust path, or the client's CA-cert setting). Never disable verification in production.

## High Availability

- Choose a **multi-node Business/Premium plan** so shards and replicas spread across nodes.
- Set `number_of_replicas >= 1` on indices.
- Aiven runs automated backups; enable and verify per the service's backup settings.
- For network isolation, deploy the service into an **Aiven Project VPC** and peer it with your cloud VPC (`project_vpc_id` on the service).

## Monitoring

- Metrics: `aiven_service_metrics_fetch` (CPU, memory, disk, JVM) for the OpenSearch service.
- Logs: `aiven_project_get_service_logs` for cluster logs (retained ~4 days by default; ship to a log integration for longer retention).
- Integrations: Aiven can push metrics/logs to a Grafana/Prometheus or another OpenSearch service via service integrations.

## Troubleshooting

| Issue | Check |
|---|---|
| `aiven_service_create` not available | Connection is read-only — reconnect `aiven-mcp` with full access (or `write_allowlist=aiven_service_create`) |
| `aiven_service_metrics_fetch` / logs not available | Monitoring needs full access — a provisioning-only (`write_allowlist`) connection excludes them |
| `service_uri` / password shows `[REDACTED]` | Reconnect `aiven-mcp` with `allow_secrets=true` |
| Service stuck in `BUILDING` | Normal for a few minutes; re-check with a single `aiven_service_get` — do not loop |
| TLS handshake / cert errors | Use the project CA, or `OPENSEARCH_SSL_VERIFY=false` for dev |
| 401 / auth failed to the cluster | Confirm username (`avnadmin`) and password from `aiven_service_get`; password may have rotated |
| Cluster health yellow | Unassigned replicas — expected on single-node plans; use a multi-node plan or set `number_of_replicas: 0` for dev |
| Remote ML connector rejected | Endpoint not in the trusted allowlist — configure `trusted_connector_endpoints_regex` in the service's OpenSearch user config, or use a local pretrained model |
| Model deployment fails | Confirm ML Commons is enabled and the plan has enough heap; smaller plans may not fit larger models |
