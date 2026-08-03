# Vector Search and k-NN Optimization

## Core Concepts

OpenSearch's k-NN (k-Nearest Neighbors) plugin supports efficient vector similarity search, using the HNSW (Hierarchical Navigable Small World) algorithm to build graph indices. Vector search performance depends on index configuration, caching strategy, and query parameters.

OpenSearch supports two vector index modes:
- **Memory Mode**: Vector index is stored in memory, providing optimal performance (< 10ms latency)
- **Disk Mode**: Vector index is stored on disk, significantly reducing memory requirements and cost, but with higher latency (100-200ms)

**Portable Default Configuration**:
- **Vector Engine**: FAISS for most production workloads; verify version support before using newer options.
- **Similarity Algorithm**: cosine for normalized embeddings and broad semantic-search use cases; use L2 or inner product when the embedding model requires it.
- **Capacity Shape**: Choose memory-optimized nodes for low-latency in-memory k-NN, storage/IO-optimized nodes for disk mode, and enough data nodes to keep shard sizes and k-NN cache pressure manageable.
- **Provider-Specific Mapping**: If the target is Amazon OpenSearch Service, current-generation memory-optimized families such as r7g/r8g/r8gd are common vector-search examples; optimized families such as OR2/OM2/OI2 have workload-specific tradeoffs. For self-managed OpenSearch, map the same CPU, memory, and IO requirements to your available instance or Kubernetes node classes.

## Common Issues

### Issue 1: First Vector Query Is Very Slow (Cold Start Problem)

**Symptoms**:
- First vector query takes several seconds or longer
- Subsequent queries perform normally
- Problem recurs after cluster restart

**Cause**:
Vector indices are not loaded into memory by default; the first query needs to read from disk and build the cache.

**Solution**:
1. Use the warmup API to preload the index:
```bash
POST /my-vector-index/_warmup
```

2. Enable automatic caching in index settings:
```json
{
  "settings": {
    "index.knn.cache.enabled": true
  }
}
```

3. Monitor cache hit rate:
```bash
GET /_plugins/_knn/stats
```

**Best Practices**:
- Execute warmup immediately after index creation or data import
- Reserve sufficient off-heap memory for k-NN cache (circuit_breaker.parent.limit)
- Regularly monitor cache eviction rate to avoid frequent cache invalidation

### Issue 2: How to Tune HNSW Parameters

**Symptoms**:
- Slow query speed or low recall rate
- Index build time is too long
- Memory usage is too high

**Cause**:
HNSW parameters (ef_construction, m) directly affect index quality and performance.

**Solution**:

Adjust HNSW parameters:
```json
{
  "mappings": {
    "properties": {
      "my_vector": {
        "type": "knn_vector",
        "dimension": 768,
        "method": {
          "name": "hnsw",
          "space_type": "cosine",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16
          }
        }
      }
    }
  }
}
```

**Parameter Details**:
- `ef_construction`: Search depth during index construction (default 512)
  - Higher = better recall, but slower construction
  - Recommended range: 100-1000
- `m`: Maximum number of connections per node (default 16)
  - Higher = better recall, but higher memory usage
  - Recommended range: 8-48

**Best Practices**:
- Production: ef_construction=512, m=16 (balance between performance and quality)
- High recall scenarios: ef_construction=1000, m=32
- Fast indexing scenarios: ef_construction=128, m=8
- Adjust the ef parameter (ef_search) at query time to balance speed and recall

### Issue 3: Vector Dimension Selection and Performance Impact

**Symptoms**:
- Query latency increases significantly with higher dimensions
- Memory usage is too high

**Cause**:
Vector dimensions directly affect computational complexity and storage space.

**Solution**:

1. Choose appropriate vector dimensions:
```json
{
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 384,
        "method": {
          "name": "hnsw",
          "space_type": "cosine"
        }
      }
    }
  }
}
```

2. Consider dimensionality reduction techniques:
- PCA (Principal Component Analysis)
- Quantization

**Best Practices**:
- Use the model's native dimensions; avoid unnecessary padding
- Common dimensions: 384 (MiniLM), 768 (BERT), 1536 (OpenAI)
- Lower dimensions yield better performance but may lose precision
- Test the impact of different dimensions on recall rate

### Issue 4: How to Use Disk Mode to Reduce Costs

**Symptoms**:
- Memory costs are too high
- Large-scale vector datasets (> 50M vectors)
- Higher latency is acceptable (100-200ms)

**Cause**:
Memory mode requires loading the entire vector index into memory, which is costly for large-scale datasets.

**Solution**:

Use disk mode configuration:
```json
{
  "settings": {
    "index": {
      "knn": true
    }
  },
  "mappings": {
    "properties": {
      "my_vector": {
        "type": "knn_vector",
        "dimension": 768,
        "space_type": "cosine",
        "data_type": "float",
        "mode": "on_disk",
        "compression_level": "32x"
      }
    }
  }
}
```

**Parameter Details**:
- `mode: "on_disk"`: Enable disk mode
- `data_type: "float"`: Disk mode only supports float data type
- `compression_level`: Compression level
  - `"4x"`: Uses Lucene engine, minimal recall loss
  - `"16x"`: Uses FAISS engine, balances performance and memory
  - `"32x"`: Default value, maximum memory savings, 15-20% recall loss

**Performance Impact**:
- QPS: Reduced by ~98% (from 2000+ down to 30-70)
- Latency: Increased by ~20x (from 10ms to 100-200ms)
- Memory usage: Reduced by 32x
- Cost: Reduced by 50-80%

**Automatic Rescoring Mechanism**:
- Disk mode enables rescoring by default to maintain recall
- Search is performed in two phases: first search the compressed index, then rescore with full-precision vectors
- Default `oversample_factor` is 3.0, adjustable as needed

**Best Practices**:
- Use high-performance EBS volumes (gp3, 9000+ IOPS)
- Configure sufficient EBS throughput (500+ MB/s)
- Monitor IOPS utilization to avoid bottlenecks
- Suitable for batch processing or offline analytics scenarios
- Not suitable for real-time low-latency applications
- Only supports `float` data type
- Consider adjusting `oversample_factor` to balance performance and recall

**EBS Configuration Recommendations**:
```json
{
  "ebs_options": {
    "ebs_enabled": true,
    "volume_type": "gp3",
    "volume_size": 500,
    "iops": 9000,
    "throughput": 500
  }
}
```

### Issue 5: Hybrid Query (Vector + Keyword) Optimization

**Symptoms**:
- Performance degrades when using both vector search and keyword search simultaneously
- Result ranking does not match expectations

**Cause**:
Vector similarity scores and text relevance scores need to be combined properly.

**Solution**:

Use script_score or hybrid query:
```json
{
  "query": {
    "script_score": {
      "query": {
        "bool": {
          "must": [
            {
              "match": {
                "title": "machine learning"
              }
            }
          ],
          "filter": {
            "term": {
              "status": "published"
            }
          }
        }
      },
      "script": {
        "source": "knn_score",
        "lang": "knn",
        "params": {
          "field": "embedding",
          "query_value": [0.1, 0.2, ...],
          "space_type": "cosine"
        }
      }
    }
  }
}
```

**Best Practices**:
- Use filter context for exact matching (does not affect scoring)
- Adjust the weight between vector and text scores
- Consider using rescore for secondary ranking
- Test different score combination strategies

## Configuration Examples

### Complete Vector Index Configuration (Memory Mode)

```json
{
  "settings": {
    "index": {
      "knn": true,
      "knn.cache.enabled": true,
      "number_of_shards": 3,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "title": {
        "type": "text"
      },
      "content": {
        "type": "text"
      },
      "embedding": {
        "type": "knn_vector",
        "dimension": 768,
        "method": {
          "name": "hnsw",
          "space_type": "cosine",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16
          }
        }
      },
      "timestamp": {
        "type": "date"
      }
    }
  }
}
```

### Disk Mode Configuration (Cost Optimized)

```json
{
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 6,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "title": {
        "type": "text"
      },
      "content": {
        "type": "text"
      },
      "embedding": {
        "type": "knn_vector",
        "dimension": 768,
        "space_type": "cosine",
        "data_type": "float",
        "mode": "on_disk",
        "compression_level": "16x",
        "method": {
          "params": {
            "ef_construction": 512
          }
        }
      },
      "timestamp": {
        "type": "date"
      }
    }
  }
}
```

**Disk Mode Configuration Notes**:
- Uses `faiss` engine and `hnsw` method by default
- `compression_level: "16x"` provides the best cost-performance ratio
- `data_type: "float"` is a required parameter for disk mode
- Increase shard count to improve concurrent performance
- Requires high-performance EBS volumes

### Advanced Disk Mode Configuration (Custom Parameters)

```json
{
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 6,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "embedding": {
        "type": "knn_vector",
        "dimension": 768,
        "space_type": "cosine",
        "data_type": "float",
        "mode": "on_disk",
        "compression_level": "16x",
        "method": {
          "name": "hnsw",
          "engine": "faiss",
          "params": {
            "ef_construction": 512,
            "m": 16
          }
        }
      }
    }
  }
}
```

### Vector Query Example

```json
{
  "size": 10,
  "query": {
    "knn": {
      "embedding": {
        "vector": [0.1, 0.2, 0.3, ...],
        "k": 10
      }
    }
  }
}
```

### Vector Query with Filters

```json
{
  "size": 10,
  "query": {
    "bool": {
      "must": [
        {
          "knn": {
            "embedding": {
              "vector": [0.1, 0.2, 0.3, ...],
              "k": 50
            }
          }
        }
      ],
      "filter": [
        {
          "range": {
            "timestamp": {
              "gte": "2024-01-01"
            }
          }
        }
      ]
    }
  }
}
```

### Disk Mode Vector Query (with Rescoring)

```json
{
  "size": 10,
  "query": {
    "knn": {
      "embedding": {
        "vector": [0.1, 0.2, 0.3, ...],
        "k": 10,
        "method_parameters": {
          "ef_search": 512
        },
        "rescore": {
          "oversample_factor": 10.0
        }
      }
    }
  }
}
```

## Performance Monitoring

### Key Metrics

1. **Cache Hit Rate**:
```bash
GET /_plugins/_knn/stats
```
Check `cache_capacity_reached` and `eviction_count`

2. **Query Latency**:
```bash
GET /_nodes/stats/indices/search
```

3. **Memory Usage**:
```bash
GET /_cat/nodes?v&h=name,heap.percent,ram.percent
```

### Performance Benchmarks

- Single vector query: < 100ms (warm cache)
- First query (cold start): < 2s (after warmup)
- Cache hit rate: > 95%
- Recall rate: > 90% (depends on HNSW parameters)

## Reference Resources

- [OpenSearch k-NN Official Documentation](https://opensearch.org/docs/latest/search-plugins/knn/)
- [HNSW Algorithm Paper](https://arxiv.org/abs/1603.09320)
- [Vector Search Best Practices](https://opensearch.org/docs/latest/search-plugins/knn/performance-tuning/)
