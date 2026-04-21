# Amazon OpenSearch Service Domain — Step 2: Deploy Search Configuration

This guide covers migrating index configuration, deploying ML models, and creating pipelines on the OpenSearch domain.

## State Input

From `.opensearch-deploy-state.json`:
- `resource_endpoint`: domain endpoint URL
- `search_strategy`: determines which components to deploy

From `prepare_aws_deployment()` output:
- `local_config.text_fields`: fields to configure
- `plan_summary.solution`: full architecture plan

## Step 1: Migrate Index Configuration

Using opensearch-mcp-server:

1. Create the index on the domain endpoint with mappings from the local setup
2. Include all field mappings, settings, and analyzers
3. Configure replicas for high availability (1-2 replicas)

```
PUT <domain-endpoint>/<index-name>
{
  "settings": { ... from local config ... },
  "mappings": { ... from local config ... }
}
```

Update state: `"index_name": "<index-name>"`

## Step 2: Deploy ML Models (if semantic/hybrid search)

For search strategies that use embeddings (dense vector, hybrid, neural sparse):

### Deploy pretrained models from OpenSearch model repository:

```
POST <domain-endpoint>/_plugins/_ml/models/_register?deploy=true
{
  "name": "huggingface/sentence-transformers/all-MiniLM-L12-v2",
  "version": "1.0.1",
  "model_format": "TORCH_SCRIPT"
}
```

Or deploy remote Bedrock models (see [Domain Agentic Setup](domain-03-agentic-setup.md) Step 1-2 for IAM role and connector setup pattern).

Test model inference:
```
POST <domain-endpoint>/_plugins/_ml/models/<model-id>/_predict
{
  "parameters": { "inputText": "hello world" }
}
```

Update state: `"model_id": "<model_id>"`

## Step 3: Create Ingest Pipelines

Recreate ingest pipelines from local setup:

```
PUT <domain-endpoint>/_ingest/pipeline/<pipeline-name>
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

Attach pipeline to index:
```
PUT <domain-endpoint>/<index-name>/_settings
{ "index.default_pipeline": "<pipeline-name>" }
```

Update state: `"ingest_pipeline_name": "<pipeline-name>"`

## Step 4: Create Search Pipelines (if applicable)

For hybrid search, create normalization pipeline:

```
PUT <domain-endpoint>/_search/pipeline/<search-pipeline-name>
{
  "phase_results_processors": [{
    "normalization-processor": {
      "normalization": { "technique": "min_max" },
      "combination": { "technique": "arithmetic_mean", "parameters": { "weights": [0.3, 0.7] } }
    }
  }]
}
```

Update state: `"search_pipeline_name": "<search-pipeline-name>"`

## Step 5: Index Sample Documents

1. Use the same sample documents from Phase 1
2. Index test documents to verify the setup
3. Test search queries appropriate to the strategy
4. Verify embeddings and pipeline processing

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

- **For agentic search**: Proceed to [Domain Agentic Setup](domain-03-agentic-setup.md)
- **For all other strategies**: Deployment complete. Connect the Search UI and provide access information.

### Connect Search UI to AWS Endpoint

```
Call connect_search_ui_to_endpoint(
  endpoint="<domain-endpoint>",
  port=443,
  use_ssl=true,
  username="<master-user>",
  password="<master-password>",
  index_name="<index-name>"
)
```

The UI header badge will change from "Local" to "AWS Cloud" with a green connection indicator.

### Access Information (non-agentic)

Give the user:
- Domain endpoint URL
- Domain ARN
- OpenSearch Dashboards URL
- Master user credentials (securely)
- Sample search queries
- Search Builder UI URL (already connected to AWS endpoint)
