# Embedding Options

## Mode: `local` (recommended)

Deploys `sentence-transformers/all-MiniLM-L6-v2` via ml-commons. No external API
calls. Runs on the local Docker container.

**Requirements:** ml-commons plugin enabled (included in the standard Docker image).

The setup script deploys the model and attaches an ingest pipeline:

```json
{
  "processors": [{
    "text_embedding": {
      "model_id": "<deployed-model-id>",
      "field_map": { "content": "content_vector" }
    }
  }]
}
```

Vectors are generated at index time. The DLS role excludes `content_vector` from
search responses via FLS (`~content_vector`) - the field is used for kNN ranking
only, never returned to the caller.

At query time, the skill requests the named `sentence_embedding` output and
requires its vector length to match `embedding.dimension`. A missing, malformed,
or mismatched model response fails the query instead of using another tensor.

**Combined BM25 and kNN query:**

```json
{
  "query": {
    "bool": {
      "should": [
        { "multi_match": { "query": "...", "fields": ["title^2", "content"] } },
        { "knn": { "content_vector": { "vector": ["..."], "k": 5 } } }
      ],
      "minimum_should_match": 1
    }
  }
}
```

OpenSearch combines these clauses using standard Boolean score summation. There
is no normalization processor and no 0.3/0.7 weighting. A top-level OpenSearch
`hybrid` query cannot be used here because TLQ DLS runs at filter level and wraps
the request query; OpenSearch rejects a wrapped `hybrid` query. This Boolean form
keeps both lexical and vector recall under DLS.

## Mode: `none` (BM25-only)

No embedding model. Fastest setup, no ML dependencies or reader-role ML cluster
permissions.

Use when:
- ml-commons is unavailable or disabled
- Hardware cannot support a local model
- A quick proof-of-concept is the goal

Queries use `multi_match` across `title` and `content`. No vector clause is used.
