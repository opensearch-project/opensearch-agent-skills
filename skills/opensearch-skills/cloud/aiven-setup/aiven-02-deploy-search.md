# Aiven for OpenSearch — Step 2: Deploy Search Configuration

This guide covers the **Aiven-specific** part: pointing `opensearch-mcp-server` at the Aiven cluster. The actual search build (index, mappings, ML models, pipelines, sample docs) is not Aiven-specific — delegate it to the [opensearch-launchpad](../../search/opensearch-launchpad/SKILL.md) skill rather than duplicating it here.

## State Input

From `.opensearch-deploy-state.json`:
- `resource_host`, `resource_port`, `resource_endpoint` — from provisioning
- `os_username` — the OpenSearch admin user (typically `avnadmin`)
- `search_strategy` — determines which components launchpad deploys

The password is **not** in the state file — retrieve it from the provisioning step (or re-read via `aiven_service_get`).

## Step 0: Point opensearch-mcp-server at Aiven

Aiven OpenSearch uses **basic authentication** over HTTPS. Configure the `opensearch-mcp-server` env block with the connection details:

```json
{
  "opensearch-mcp-server": {
    "command": "uvx",
    "args": ["opensearch-mcp-server-py@latest"],
    "env": {
      "OPENSEARCH_URL": "https://<resource_host>:<resource_port>",
      "OPENSEARCH_USERNAME": "<os_username>",
      "OPENSEARCH_PASSWORD": "<password>",
      "OPENSEARCH_SSL_VERIFY": "false",
      "FASTMCP_LOG_LEVEL": "ERROR"
    }
  }
}
```

- `OPENSEARCH_SSL_VERIFY=false` is acceptable for development. For verified TLS, supply the Aiven project CA instead — see [reference.md](reference.md).
- If you set the env block, ask the user to reconnect MCP servers so it picks up the endpoint. Alternatively, `opensearch-mcp-server` accepts the connection details per call — pass them each request and skip the reconnect.

Verify connectivity before proceeding — list indices via `opensearch-mcp-server` (`ListIndexTool`).

## Step 1: Deploy the Search Configuration (delegate to opensearch-launchpad)

With `opensearch-mcp-server` pointed at Aiven, hand off to [opensearch-launchpad](../../search/opensearch-launchpad/SKILL.md) for the build. It already owns index creation, ML model deployment, ingest/search pipelines, and sample indexing for every strategy (BM25, dense vector, neural sparse, hybrid, agentic). Run that flow against the Aiven endpoint exactly as against any other cluster — nothing about the build differs on Aiven.

### Aiven-specific notes for the launchpad flow

- **Replicas / HA** — Aiven distributes replicas across nodes automatically on multi-node plans. On a single-node plan, replicas stay unassigned (yellow health is expected) — use `number_of_replicas: 0` for dev.
- **ML on single-node plans** — a single node has no dedicated ML role, so model deploy fails until you set `ml_commons_only_run_on_ml_node: false`. Aiven blocks the direct `PUT /_cluster/settings`, so set it via `aiven_service_update` (`user_config.opensearch.ml_commons_only_run_on_ml_node = false`). This also means the `opensearch_ops.py deploy-model` helper 403s — register the model directly through `opensearch-mcp-server` instead.
- **Model format** — prefer `ONNX`; the `TORCH_SCRIPT` format of some pretrained models fails to load on OpenSearch 2.17.
- **Remote ML connectors (Bedrock/OpenAI/etc.)** — no IAM role as on AWS. Allowlist the endpoint via `trusted_connector_endpoints_regex` in the service's OpenSearch user configuration; otherwise fall back to a local pretrained model.
- **Plugins** — ML Commons, k-NN, and SQL/PPL are available out of the box.

Update state as launchpad completes: `"index_name"`, and (if created) `"model_id"`, `"ingest_pipeline_name"`, `"search_pipeline_name"`.

## State Output

Update `.opensearch-deploy-state.json`:
```json
{
  "step_completed": "deploy-search",
  "index_name": "<index-name>",
  "model_id": "<if created>",
  "ingest_pipeline_name": "<if created>",
  "search_pipeline_name": "<if created>"
}
```

## Next Step

Deployment is complete. Continue with the [aiven-setup SKILL.md](SKILL.md): launch the Search UI (Step 3), verify health via Aiven metrics/logs (Step 4), and provide access information (Step 5).
