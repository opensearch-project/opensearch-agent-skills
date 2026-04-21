# CLI Reference

All commands are run from the skill root directory.

```bash
uv run python scripts/opensearch_ops.py <command> [options]
```

## Start OpenSearch

```bash
bash scripts/start_opensearch.sh
```

## Check connectivity

```bash
uv run python scripts/opensearch_ops.py status
```

## Load sample data

```bash
# Built-in IMDB dataset
uv run python scripts/opensearch_ops.py load-sample --type builtin_imdb

# From a local file (JSON, JSONL, CSV, TSV, Parquet)
uv run python scripts/opensearch_ops.py load-sample --type local_file --value /path/to/data.json

# From a URL
uv run python scripts/opensearch_ops.py load-sample --type url --value https://example.com/data.json

# From an existing local index
uv run python scripts/opensearch_ops.py load-sample --type localhost_index --value my-index

# From pasted JSON
uv run python scripts/opensearch_ops.py load-sample --type paste --value '{"title": "Example", "description": "A sample doc"}'
```

## Deploy a model

```bash
# Local pretrained model (e.g. sentence-transformers)
uv run python scripts/opensearch_ops.py deploy-model --name "huggingface/sentence-transformers/all-mpnet-base-v2"

# Bedrock embedding model
uv run python scripts/opensearch_ops.py deploy-bedrock --name "amazon.titan-embed-text-v2:0"
```

## Create an index

```bash
uv run python scripts/opensearch_ops.py create-index --name my-index --body '{"settings": {"index": {"knn": true}}, "mappings": {"properties": {"title": {"type": "text"}, "embedding": {"type": "knn_vector", "dimension": 768, "method": {"engine": "faiss", "name": "hnsw"}}}}}'
```

Use `--replace` (default: true) to delete and recreate if the index already exists.

## Create and attach a pipeline

```bash
# Ingest pipeline
uv run python scripts/opensearch_ops.py create-pipeline --name my-pipeline --index my-index --type ingest --body '{"description": "Embedding pipeline", "processors": [{"text_embedding": {"model_id": "<MODEL_ID>", "field_map": {"title": "embedding"}}}]}'

# Search pipeline
uv run python scripts/opensearch_ops.py create-pipeline --name my-search-pipeline --index my-index --type search --body '{"request_processors": [{"neural_query_enricher": {"default_model_id": "<MODEL_ID>"}}]}'

# Hybrid pipeline with custom weights
uv run python scripts/opensearch_ops.py create-pipeline --name my-hybrid-pipeline --index my-index --type search --hybrid --weights '[0.3, 0.7]' --body '{"phase_results_processors": [{"normalization-processor": {"normalization": {"technique": "min_max"}, "combination": {"technique": "arithmetic_mean", "parameters": {"weights": [0.3, 0.7]}}}}]}'
```

## Index documents

```bash
# Single document
uv run python scripts/opensearch_ops.py index-doc --index my-index --id doc1 --doc '{"title": "Example", "description": "A sample document"}'

# Bulk index from file
uv run python scripts/opensearch_ops.py index-bulk --index my-index --source-file /path/to/data.tsv --count 50
```

## Search

```bash
# Simple match query
uv run python scripts/opensearch_ops.py search --index my-index --body '{"query": {"match": {"title": "search term"}}}' --size 10

# Neural (semantic) search
uv run python scripts/opensearch_ops.py search --index my-index --body '{"query": {"neural": {"embedding": {"query_text": "find similar documents", "model_id": "<MODEL_ID>", "k": 5}}}}'

# Hybrid search
uv run python scripts/opensearch_ops.py search --index my-index --body '{"query": {"hybrid": {"queries": [{"match": {"title": "search term"}}, {"neural": {"embedding": {"query_text": "search term", "model_id": "<MODEL_ID>", "k": 5}}}]}}}'
```

## Launch Search Builder UI

```bash
uv run python scripts/opensearch_ops.py launch-ui --index my-index
```

## Launch Comparison View

After evaluation and restart, compare the baseline and improved indices side by side:

```bash
uv run python scripts/opensearch_ops.py compare-ui \
  --baseline my-index-v1 \
  --improved my-index-v2
```

## Connect UI to remote endpoint

```bash
# Amazon OpenSearch Service
uv run python scripts/opensearch_ops.py connect-ui --endpoint search-my-domain.us-east-1.es.amazonaws.com --aws-region us-east-1 --aws-service es --index my-index

# Amazon OpenSearch Serverless
uv run python scripts/opensearch_ops.py connect-ui --endpoint abc123.us-east-1.aoss.amazonaws.com --aws-region us-east-1 --aws-service aoss --index my-index

# Basic auth
uv run python scripts/opensearch_ops.py connect-ui --endpoint my-opensearch.example.com --port 443 --username admin --password admin --index my-index
```

## Agentic search setup

```bash
# 1. Deploy Bedrock Claude model for agent reasoning
# Method A: Using environment variables (recommended for manual use)
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_REGION="us-east-1"
uv run python scripts/opensearch_ops.py deploy-agentic-model --region us-east-1

# Method B: Passing credentials as arguments (for automation, delete from chat history after use)
uv run python scripts/opensearch_ops.py deploy-agentic-model \
  --access-key "your-access-key" \
  --secret-key "your-secret-key" \
  --region us-east-1

# 2a. For stateless searches (REST APIs, search apps):
# Create a flow agent
uv run python scripts/opensearch_ops.py create-flow-agent --name my-flow-agent --model-id <CONNECTOR_MODEL_ID>
# Create flow agent pipeline
uv run python scripts/opensearch_ops.py create-flow-agentic-pipeline --name my-flow-pipeline --agent-id <AGENT_ID> --index my-index

# 2b. For multi-turn conversations (chatbots):
# Create a conversational agent
uv run python scripts/opensearch_ops.py create-conversational-agent --name my-conv-agent --model-id <CONNECTOR_MODEL_ID>
# Deploy a separate RAG model (uses /invoke API, different from agent's /converse API)
uv run python scripts/opensearch_ops.py deploy-rag-model --region us-east-1
# Create conversational agent pipeline with RAG
uv run python scripts/opensearch_ops.py create-conversational-agent-pipeline --name my-conv-pipeline --agent-id <AGENT_ID> --index my-index --model-id <RAG_MODEL_ID>
```

## Read knowledge base files

```bash
uv run python scripts/opensearch_ops.py read-knowledge --file dense_vector_models.md
uv run python scripts/opensearch_ops.py read-knowledge --file sparse_vector_models.md
uv run python scripts/opensearch_ops.py read-knowledge --file opensearch_semantic_search_guide.md
uv run python scripts/opensearch_ops.py read-knowledge --file agentic_search_guide.md
uv run python scripts/opensearch_ops.py read-knowledge --file evaluation_guide.md
```

## Cleanup

```bash
uv run python scripts/opensearch_ops.py cleanup
```
