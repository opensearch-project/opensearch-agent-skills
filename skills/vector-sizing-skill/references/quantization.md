# Quantization Trade-offs for OpenSearch k-NN

## Overview

Quantization reduces the memory footprint of vector indices by compressing floating-point
values into lower-precision representations. This trades recall accuracy for memory savings.

## Quantization Methods

| Method | Bits/Element | Memory vs FP32 | Typical Recall | Engine Support |
|--------|-------------|----------------|----------------|----------------|
| FP32 | 32 | 1.0x (baseline) | 100% | All |
| FP16 | 16 | 0.5x | ~99% | FAISS |
| SQ8 | 8 | 0.25x | 95-98% | FAISS, Lucene (OS 2.16+) |
| PQ | ~4 (configurable) | 0.125x | 85-95% | FAISS |

## Memory Savings Example (100M vectors, 1536 dimensions)

| Method | Memory per Replica Set | Savings |
|--------|----------------------|---------|
| FP32 | ~676 GB | — |
| FP16 | ~338 GB | 50% |
| SQ8 | ~169 GB | 75% |
| PQ (m=192) | ~85 GB | 87% |

## When to Use Each

### FP32 (No quantization)
- Highest accuracy requirements (medical, legal, financial)
- Dataset < 10M vectors (memory isn't a concern)
- Benchmarking baseline

### FP16 (Half precision)
- **Best default choice** when memory is a concern
- Negligible recall loss for most use cases
- Embedding models often trained in FP16 anyway
- No retraining/calibration needed

### SQ8 (Scalar quantization)
- Good balance of compression and recall
- Requires FAISS engine
- Calibration recommended (sample ~10K vectors)
- May need rescoring for top-k refinement

### PQ (Product quantization)
- Maximum compression for very large datasets (>500M vectors)
- Requires training phase on representative data
- Best combined with rescoring (2-pass: PQ coarse → FP32 fine)
- Parameters: `m` (subvectors) and `code_size` (bits per subvector)

## Rescoring Strategy

For SQ8/PQ, use a two-pass approach:
1. **Coarse search**: Retrieve top-100 candidates using quantized index
2. **Rescore**: Re-rank candidates using original FP32 vectors from disk

OpenSearch supports this via the `rescore` parameter in k-NN queries:
```json
{
  "query": {
    "knn": {
      "vector_field": {
        "vector": [...],
        "k": 10,
        "rescore": {
          "oversample_factor": 3.0
        }
      }
    }
  }
}
```

## Decision Framework

```
Memory budget tight?
├── No → FP32 (simplest, highest recall)
└── Yes
    ├── Can you tolerate 1-2% recall loss? → FP16
    ├── Can you tolerate 2-5% recall loss? → SQ8 + rescore
    └── Can you tolerate 5-15% recall loss? → PQ + rescore
```

## Testing Quantization Impact

Always measure recall on YOUR dataset before committing:

1. Index a representative sample (100K-1M vectors) at FP32
2. Generate ground-truth k-NN results
3. Re-index with quantization
4. Measure recall@k against ground truth
5. Accept if recall meets your threshold (typically >95%)
