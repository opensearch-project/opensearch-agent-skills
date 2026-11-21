# OpenSearch k-NN Index Mapping Templates

## Basic Vector Index (FAISS, FP32)

```json
{
  "settings": {
    "index": {
      "knn": true,
      "knn.algo_param.ef_search": 512,
      "number_of_shards": 10,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 1536,
        "method": {
          "name": "hnsw",
          "space_type": "l2",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16
          }
        }
      },
      "text": { "type": "text" },
      "metadata": { "type": "object" }
    }
  }
}
```

## FAISS with FP16 Quantization

```json
{
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 10,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 1536,
        "method": {
          "name": "hnsw",
          "space_type": "l2",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16,
            "encoder": {
              "name": "fp16"
            }
          }
        }
      }
    }
  }
}
```

## FAISS with SQ8 (Scalar Quantization)

```json
{
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 10,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 1536,
        "method": {
          "name": "hnsw",
          "space_type": "l2",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16,
            "encoder": {
              "name": "sq",
              "parameters": {
                "type": "fp16"
              }
            }
          }
        }
      }
    }
  }
}
```

## FAISS with Product Quantization (PQ)

```json
{
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 10,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 1536,
        "method": {
          "name": "hnsw",
          "space_type": "l2",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16,
            "encoder": {
              "name": "pq",
              "parameters": {
                "code_size": 8,
                "m": 192
              }
            }
          }
        }
      }
    }
  }
}
```

## Lucene Engine (Best for Filter-Heavy Queries)

```json
{
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 10,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 768,
        "method": {
          "name": "hnsw",
          "space_type": "cosinesimil",
          "engine": "lucene",
          "parameters": {
            "ef_construction": 512,
            "m": 16
          }
        }
      },
      "tenant_id": { "type": "keyword" },
      "category": { "type": "keyword" }
    }
  }
}
```

## Space Types

| Space Type | Use Case | Distance |
|-----------|----------|----------|
| `l2` | General purpose, normalized embeddings | Euclidean |
| `cosinesimil` | Text embeddings (most common) | Cosine similarity |
| `innerproduct` | Maximum inner product (some models) | Dot product |

## Common Embedding Dimensions

| Model | Dimensions | Recommended Space |
|-------|-----------|-------------------|
| OpenAI text-embedding-ada-002 | 1536 | cosinesimil |
| OpenAI text-embedding-3-small | 1536 | cosinesimil |
| OpenAI text-embedding-3-large | 3072 | cosinesimil |
| Cohere embed-v3 | 1024 | cosinesimil |
| Amazon Titan Embeddings V2 | 1024 | cosinesimil |
| Amazon Titan Embeddings V1 | 1536 | cosinesimil |
| Sentence-BERT (all-MiniLM) | 384 | cosinesimil |
| BGE-large | 1024 | cosinesimil |
| E5-large-v2 | 1024 | cosinesimil |

## Shard Sizing for k-NN

Rules of thumb:
- **Max vectors per shard**: 30M (performance degrades beyond this)
- **Max shard size**: 50 GB (for balanced recovery times)
- **Minimum shards**: number of data nodes (for parallel search)
- **Formula**: `max(vectors / 30M, storage_gb / 50, data_nodes)`
