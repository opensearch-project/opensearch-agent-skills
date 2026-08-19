# OpenSearch k-NN Engine Comparison

## Engine Overview

| Engine | Algorithm | Best For | Memory Model |
|--------|-----------|----------|-------------|
| FAISS | HNSW, IVF | Large-scale production, quantization support | Native (off-heap) |
| nmslib | HNSW | Low-latency, read-heavy workloads | Native (off-heap) |
| Lucene | HNSW | Smaller datasets, filter-heavy queries | On-heap + mmap |

## Detailed Comparison

### FAISS (Recommended for most production workloads)

- **Quantization support**: FP16, SQ8, PQ, OPQ, IVFPQ
- **Memory efficiency**: Best with quantization; 4-8x reduction possible
- **Filter support**: Post-filter (efficient filtering applied after ANN)
- **Training required**: Only for IVF/PQ methods
- **Index build speed**: Moderate
- **Recall at scale**: Excellent with proper HNSW parameters

### nmslib

- **Quantization support**: None (FP32 only)
- **Memory efficiency**: Lowest (full precision only)
- **Filter support**: Post-filter
- **Training required**: No
- **Index build speed**: Fast
- **Recall at scale**: Excellent
- **Note**: Being deprecated in favor of FAISS in newer OpenSearch versions

### Lucene

- **Quantization support**: SQ (scalar quantization in OS 2.16+)
- **Memory efficiency**: Good for smaller datasets; uses mmap
- **Filter support**: Pre-filter (exact filtering before ANN — best for selective filters)
- **Training required**: No
- **Index build speed**: Fast
- **Recall at scale**: Good for <10M vectors per shard
- **Note**: Best when queries heavily use filters (e.g., multi-tenant)

## Engine Selection Guide

```
Is quantization required?
├── Yes → FAISS (only engine with full quantization support)
└── No
    ├── Heavy filtering (>50% selectivity)? → Lucene (pre-filter)
    ├── Dataset > 50M vectors? → FAISS (proven at scale)
    └── Simple k-NN, low latency priority? → FAISS or nmslib
```

## HNSW Parameters

| Parameter | Default | Range | Impact |
|-----------|---------|-------|--------|
| ef_construction | 512 | 100-1000 | Build quality (higher = better recall, slower build) |
| m | 16 | 4-64 | Connections per node (higher = more memory, better recall) |
| ef_search | 512 | 100-1000 | Search quality (higher = better recall, slower search) |

### Memory Impact of `m` Parameter

Each vector stores `m` connections (bidirectional), adding:
- Additional memory per vector: `m * 2 * 4 bytes` (neighbor IDs)
- At m=16: +128 bytes per vector
- At m=32: +256 bytes per vector

For 100M vectors: m=16 adds ~12 GB, m=32 adds ~24 GB overhead.
