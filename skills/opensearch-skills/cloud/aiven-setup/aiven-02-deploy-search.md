# Aiven for OpenSearch — Step 2: Deploy Search Configuration

This guide covers pointing `opensearch-mcp-server` at the Aiven cluster, then creating the index, deploying ML models (if needed), configuring pipelines, and indexing sample documents.

## State Input

From `.opensearch-deploy-state.json`:
- `resource_host`, `resource_port`, `resource_endpoint` — from provisioning
- `os_username` — the OpenSearch admin user (typically `avnadmin`)
- `search_strategy` — determines which components to deploy

From `opensearch-launchpad` (if a local setup was built):
- `local_config.text_fields` — fields to configure
- `plan_summary.solution` — full architecture plan

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
- After editing the config, ask the user to reconnect MCP servers so `opensearch-mcp-server` picks up the endpoint.

Verify connectivity before proceeding — list indices via `opensearch-mcp-server` (`ListIndexTool`) or:

```bash
uv run python scripts/opensearch_ops.py status \
  --endpoint <resource_host> --port <resource_port> --use-ssl \
  --username <os_username> --password <password>
```

## Step 1: Create the Index

Using `opensearch-mcp-server`, create the index on the Aiven endpoint with mappings from the local setup. Include field mappings, settings, and analyzers. Configure 1 replica for HA (Aiven distributes replicas across nodes automatically on multi-node plans).

```
PUT /<index-name>
{
  "settings": { "index": { "number_of_replicas": 1 } },
  "mappings": { ... from local config ... }
}
```

For dense-vector / hybrid strategies, enable k-NN and add the vector field:

```
PUT /<index-name>
{
  "settings": { "index": { "knn": true, "number_of_replicas": 1 } },
  "mappings": {
    "properties": {
      "<text-field>": { "type": "text" },
      "<vector-field>": {
        "type": "knn_vector",
        "dimension": 768,
        "method": { "engine": "faiss", "name": "hnsw", "space_type": "l2" }
      }
    }
  }
}
```

Update state: `"index_name": "<index-name>"`.

## Step 2: Deploy ML Models (if semantic/hybrid/neural-sparse search)

Aiven OpenSearch ships the ML Commons plugin. Register and deploy a pretrained model:

```
POST /_plugins/_ml/models/_register?deploy=true
{
  "name": "huggingface/sentence-transformers/all-MiniLM-L12-v2",
  "version": "1.0.1",
  "model_format": "TORCH_SCRIPT"
}
```

Test inference once deployed:

```
POST /_plugins/_ml/models/<model-id>/_predict
{ "text_docs": ["hello world"] }
```

> **Remote model connectors (Bedrock/OpenAI/etc.):** Aiven manages the cluster settings and trusted-endpoint allowlist required for ML connectors differently from AWS — there is no IAM role to attach. If the user wants a remote connector, confirm the connector/endpoint is permitted on their plan and configure `trusted_connector_endpoints_regex` via Aiven's OpenSearch user configuration. If it's not available, fall back to a local pretrained model above.

Update state: `"model_id": "<model_id>"`.

## Step 3: Create Ingest Pipelines

```
PUT /_ingest/pipeline/<pipeline-name>
{
  "description": "Embedding pipeline",
  "processors": [{
    "text_embedding": {
      "model_id": "<model_id>",
      "field_map": { "<text-field>": "<vector-field>" }
    }
  }]
}
```

Attach it to the index:

```
PUT /<index-name>/_settings
{ "index.default_pipeline": "<pipeline-name>" }
```

Update state: `"ingest_pipeline_name": "<pipeline-name>"`.

## Step 4: Create Search Pipelines (hybrid search)

```
PUT /_search/pipeline/<search-pipeline-name>
{
  "phase_results_processors": [{
    "normalization-processor": {
      "normalization": { "technique": "min_max" },
      "combination": { "technique": "arithmetic_mean", "parameters": { "weights": [0.3, 0.7] } }
    }
  }]
}
```

Update state: `"search_pipeline_name": "<search-pipeline-name>"`.

## Step 5: Index Sample Documents

1. Use the same sample documents from the local setup.
2. Index test documents to verify mappings and pipeline processing.
3. Run a search query appropriate to the strategy (match / neural / hybrid) and confirm results and embeddings.

You can bulk-load with the shared helper:

```bash
uv run python scripts/opensearch_ops.py index-bulk \
  --index <index-name> --source-file /path/to/data.tsv --count 50 \
  --endpoint <resource_host> --port <resource_port> --use-ssl \
  --username <os_username> --password <password>
```

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
