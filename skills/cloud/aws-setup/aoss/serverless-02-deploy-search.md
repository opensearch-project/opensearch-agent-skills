# Amazon OpenSearch Serverless — Step 2: Deploy Search Configuration

This guide covers creating indices, deploying ML models, and configuring pipelines on the serverless collection.

## State Input

From `.opensearch-deploy-state.json`:
- `resource_endpoint`: collection endpoint URL
- `search_strategy`: determines which path to follow
- `principal_arn`: for IAM role creation (dense vector path)

From `prepare_aws_deployment()` output:
- `local_config.text_fields`: fields to configure for search
- `plan_summary.solution`: full architecture plan

## Route by Strategy

- **Neural Sparse** — follow "Neural Sparse Path" below
- **Dense Vector or Hybrid** — follow "Dense Vector Path" below
- **BM25** — follow "BM25 Path" below

---

## Neural Sparse Path (Automatic Semantic Enrichment)

### Create Index with Semantic Enrichment

Use AWS API MCP to create the index with automatic enrichment:

```json
POST /opensearchserverless/CreateIndex
{
  "id": "<collection-id>",
  "indexName": "<index-name>",
  "indexSchema": {
    "mappings": {
      "properties": {
        "<text-field>": {
          "type": "text",
          "semantic_enrichment": {
            "status": "ENABLED",
            "language_options": "english"
          }
        }
      }
    }
  }
}
```

Key points:
- Set `semantic_enrichment.status` to "ENABLED" on text fields for neural sparse
- `language_options`: "english" or "multi-lingual"
- System automatically deploys sparse model, creates ingest/search pipelines
- Standard "match" queries are automatically rewritten to neural sparse queries
- No manual model or pipeline management required

Update state: `"index_name": "<index-name>"`, `"step_completed": "deploy-search"`

Skip to "Index Sample Documents" below.

---

## Dense Vector Path

### Step 1: Create IAM Role for Bedrock

```json
POST /iam/CreateRole
{
  "RoleName": "opensearch-bedrock-role",
  "AssumeRolePolicyDocument": {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Service": "ml.opensearchservice.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }]
  }
}
```

Attach Bedrock invoke permissions:

```json
POST /iam/PutRolePolicy
{
  "RoleName": "opensearch-bedrock-role",
  "PolicyName": "BedrockInvokePolicy",
  "PolicyDocument": {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:*::foundation-model/amazon.titan-embed-text-v2:0"
    }]
  }
}
```

Update state: `"iam_role_arn": "<role-arn>"`

### Step 2: Create ML Connector

Use opensearch-mcp-server to create a Bedrock Titan connector:

```
POST <collection-endpoint>/_plugins/_ml/connectors/_create
{
  "name": "Amazon Bedrock Titan Embedding V2",
  "description": "Connector to Bedrock Titan embedding model",
  "version": 1,
  "protocol": "aws_sigv4",
  "parameters": {
    "region": "<aws-region>",
    "service_name": "bedrock"
  },
  "credential": {
    "roleArn": "<iam_role_arn>"
  },
  "actions": [{
    "action_type": "predict",
    "method": "POST",
    "url": "https://bedrock-runtime.<aws-region>.amazonaws.com/model/amazon.titan-embed-text-v2:0/invoke",
    "headers": { "content-type": "application/json", "x-amz-content-sha256": "required" },
    "request_body": "{ \"inputText\": \"${parameters.inputText}\" }",
    "pre_process_function": "\n    StringBuilder builder = new StringBuilder();\n    builder.append(\"\\\"\");\n    String first = params.text_docs[0];\n    builder.append(first);\n    builder.append(\"\\\"\");\n    def parameters = \"{\" +\"\\\"inputText\\\":\" + builder + \"}\";\n    return  \"{\" +\"\\\"parameters\\\":\" + parameters + \"}\";",
    "post_process_function": "\n      def name = \"sentence_embedding\";\n      def dataType = \"FLOAT32\";\n      if (params.embedding == null || params.embedding.length == 0) {\n        return params.message;\n      }\n      def shape = [params.embedding.length];\n      def json = \"{\" +\n                 \"\\\"name\\\":\\\"\" + name + \"\\\",\" +\n                 \"\\\"data_type\\\":\\\"\" + dataType + \"\\\",\" +\n                 \"\\\"shape\\\":\" + shape + \",\" +\n                 \"\\\"data\\\":\" + params.embedding +\n                 \"}\";\n      return json;\n    "
  }]
}
```

Update state: `"connector_id": "<connector_id>"`

### Step 3: Register and Deploy Model

```
POST <collection-endpoint>/_plugins/_ml/model_groups/_register
{ "name": "bedrock_embedding_models", "description": "Bedrock embedding model group" }
```

Update state: `"model_group_id": "<model_group_id>"`

```
POST <collection-endpoint>/_plugins/_ml/models/_register
{
  "name": "bedrock-titan-embed-v2",
  "function_name": "remote",
  "description": "Bedrock Titan Text Embeddings V2",
  "model_group_id": "<model_group_id>",
  "connector_id": "<connector_id>"
}
```

```
POST <collection-endpoint>/_plugins/_ml/models/<model-id>/_deploy
```

Test: `POST <collection-endpoint>/_plugins/_ml/models/<model-id>/_predict` with `{"parameters": {"inputText": "hello world"}}`. Verify 1024-dimensional embeddings.

Update state: `"model_id": "<model_id>"`

### Step 4: Create Ingest Pipeline

```
PUT <collection-endpoint>/_ingest/pipeline/bedrock-embedding-pipeline
{
  "description": "Bedrock Titan embedding pipeline",
  "processors": [{
    "text_embedding": {
      "model_id": "<model_id>",
      "field_map": { "<text-field>": "<vector-field>" }
    }
  }]
}
```

Update state: `"ingest_pipeline_name": "bedrock-embedding-pipeline"`

### Step 5: Create Index

```
PUT <collection-endpoint>/<index-name>
{
  "settings": {
    "index": { "knn": true, "knn.space_type": "cosinesimil", "default_pipeline": "bedrock-embedding-pipeline" }
  },
  "mappings": {
    "properties": {
      "<text-field>": { "type": "text" },
      "<vector-field>": {
        "type": "knn_vector",
        "dimension": 1024,
        "method": { "name": "hnsw", "space_type": "cosinesimil", "engine": "faiss" }
      }
    }
  }
}
```

Update state: `"index_name": "<index-name>"`

### Step 6: Create Search Pipeline (hybrid search only)

If search strategy is "hybrid":

```
PUT <collection-endpoint>/_search/pipeline/hybrid-search-pipeline
{
  "description": "Hybrid search with normalization",
  "phase_results_processors": [{
    "normalization-processor": {
      "normalization": { "technique": "min_max" },
      "combination": { "technique": "arithmetic_mean", "parameters": { "weights": [0.3, 0.7] } }
    }
  }]
}
```

Update state: `"search_pipeline_name": "hybrid-search-pipeline"`, `"step_completed": "deploy-search"`

---

## BM25 Path

### Create Index

Use opensearch-mcp-server to create the index with text mappings from local config:

```
PUT <collection-endpoint>/<index-name>
{
  "mappings": {
    "properties": {
      "<text-field>": { "type": "text" }
    }
  }
}
```

Include all field mappings from the local setup.

Update state: `"index_name": "<index-name>"`, `"step_completed": "deploy-search"`

---

## Index Sample Documents

After index creation (all paths):
1. Use the same sample documents from Phase 1
2. Index a few test documents to verify the setup
3. Test search queries:
   - Neural Sparse: use standard `match` queries (automatically rewritten)
   - Dense Vector: use `neural` query with `model_id`
   - BM25: use standard `match` queries

## Connect Search UI to AWS Endpoint

After deployment is complete, switch the local Search Builder UI to query the AWS collection:

```
Call connect_search_ui_to_endpoint(
  endpoint="<collection-endpoint>",
  port=443,
  use_ssl=true,
  index_name="<index-name>"
)
```

The UI header badge will change from "Local" to "AWS Cloud" with a green connection indicator.

## Provide Access Information

Give the user:
- Collection endpoint URL
- Collection ARN
- Dashboard URL (if applicable)
- Sample search queries to test
- Search Builder UI URL (already connected to AWS endpoint)

## State Output

Final state update:
```json
{
  "step_completed": "deploy-search",
  "index_name": "<index-name>",
  "iam_role_arn": "<if created>",
  "connector_id": "<if created>",
  "model_id": "<if created>",
  "ingest_pipeline_name": "<if created>",
  "search_pipeline_name": "<if created>"
}
```
