# OpenSearch Vector Quantization Techniques In-Depth

## Overview

Vector quantization is a lossy data compression technique that reduces memory usage and computational requirements by mapping high-precision numerical values to smaller discrete values. With the rise of generative AI applications, vector data volumes are growing exponentially, making quantization techniques a key approach for balancing performance and cost.

OpenSearch supports four main quantization techniques:
- **Binary Quantization**: 1-4 bit binary quantization, up to 32× compression
- **Byte Quantization**: 8-bit integer quantization, 4× compression
- **FP16 Quantization**: 16-bit floating-point quantization, 2× compression
- **Product Quantization**: Up to 64× compression

<!-- FALLBACK: opensearch, priority=1 -->

## Quantization Principles

### Scalar Quantization vs Product Quantization

**Scalar Quantization**:
- Quantizes each dimension of the vector independently
- Simple implementation with high computational efficiency
- Includes Binary, Byte, and FP16 quantization

**Product Quantization**:
- Splits the vector into multiple sub-vectors, quantizing each separately
- Higher compression ratio but increased computational complexity
- Requires a training process to build a codebook

### Memory Requirement Calculation Formula

**HNSW Standard Memory Formula** (published sizing heuristic; validate with your OpenSearch version and workload):
```
Memory = 1.1 × (4 × d + 8 × m) × num_vectors × (number_of_replicas + 1) bytes

Where:
- d: Vector dimension (e.g., 256, 768, 1536)
- m: HNSW connections per node (default 16)
- num_vectors: Total number of vectors in the index
- 4 × d: float32 storage per vector (bytes)
- 8 × m: Connection overhead per vector in the HNSW graph structure (bytes)
- 1.1: Additional overhead factor
```

**Quantization Scenario (FAISS engine, compressed vectors stored in memory)**:
```
Memory = 1.1 × (bytes_per_vector + 8 × m) × num_vectors × (number_of_replicas + 1)
```

**bytes_per_vector for different quantization methods**:
- No compression (float32): 4 × d
- FP16 (2x): 2 × d
- Byte/Int8 (4x): 1 × d
- Binary 4-bit (8x): d / 2
- Binary 2-bit (16x): d / 4
- Binary 1-bit (32x): d / 8

## Binary Quantization

### Technical Characteristics

**Compression Principle**:
Compresses 32-bit floating-point numbers into 1-4 bit binary representations, mapping continuous values to a discrete binary space through a threshold function.

**Supported Encoding Bit Widths**:
- 1-bit: 32× compression, value range {0, 1}
- 2-bit: 16× compression, value range {0, 1, 2, 3}
- 4-bit: 8× compression, value range {0, 1, ..., 15}

### Configuration Examples

**Basic Configuration**:
```json
{
  "mappings": {
    "properties": {
      "vector_field": {
        "type": "knn_vector",
        "dimension": 768,
        "method": {
          "name": "hnsw",
          "engine": "faiss",
          "space_type": "cosine",
          "parameters": {
            "m": 16,
            "ef_construction": 512,
            "encoder": {
              "name": "binary",
              "parameters": {
                "bits": 1
              }
            }
          }
        }
      }
    }
  }
}
```

**Advanced Configuration**:
```json
{
  "settings": {
    "index.knn": true,
    "index.knn.algo_param.ef_search": 100
  },
  "mappings": {
    "properties": {
      "title": {"type": "text"},
      "content": {"type": "text"},
      "vector_field": {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {
          "name": "hnsw",
          "engine": "faiss",
          "space_type": "cosine",
          "parameters": {
            "m": 32,                    // Increase connections to improve recall
            "ef_construction": 1000,    // Improve build quality
            "encoder": {
              "name": "binary",
              "parameters": {
                "bits": 2               // Use 2-bit to balance compression and accuracy
              }
            }
          }
        }
      }
    }
  }
}
```

### Performance Optimization

**Parameter Tuning Recommendations**:
```json
{
  "parameters": {
    "m": 32,                // Recommended to increase to 32 for high-dimensional vectors
    "ef_construction": 1000, // Improve build quality to compensate for quantization loss
    "encoder": {
      "name": "binary",
      "parameters": {
        "bits": 2           // 2-bit provides better accuracy balance
      }
    }
  }
}
```

**Query-Time Optimization**:
```json
{
  "query": {
    "knn": {
      "vector_field": {
        "vector": [...],
        "k": 10,
        "method_parameters": {
          "ef_search": 200    // Increase search depth
        }
      }
    }
  }
}
```

### Use Case Analysis

**Best Suited Scenarios**:
- High-dimensional vectors (≥ 768 dimensions)
- Extremely memory-constrained environments
- Acceptable 15-20% recall loss
- Batch processing and offline analytics

**Not Suited For**:
- Low-dimensional vectors (< 384 dimensions)
- Applications requiring very high recall
- Real-time recommendation systems
- Exact matching requirements

## Byte Quantization

### Technical Characteristics

**Quantization Range**: -128 to +127
**Compression Ratio**: 4×
**Precision Loss**: Minimal (< 5%)

### Implementation Methods

**Method 1: Pre-processing Quantization**
```python
import numpy as np

def quantize_to_byte(vectors):
    """Quantize floating-point vectors to bytes"""
    # Find global maximum absolute value
    max_abs = np.max(np.abs(vectors))

    # Scale to [-127, 127] range
    scale_factor = 127.0 / max_abs
    quantized = np.round(vectors * scale_factor).astype(np.int8)

    return quantized, scale_factor

# Usage example
original_vectors = np.random.randn(1000, 768).astype(np.float32)
quantized_vectors, scale = quantize_to_byte(original_vectors)
```

**Method 2: Disk Mode Auto-Quantization**
```json
{
  "mappings": {
    "properties": {
      "vector_field": {
        "type": "knn_vector",
        "dimension": 768,
        "mode": "on_disk",
        "compression_level": "4x",
        "method": {
          "name": "hnsw",
          "engine": "faiss"
        }
      }
    }
  }
}
```

### Configuration Examples

**Direct Byte Vector Index**:
```json
{
  "mappings": {
    "properties": {
      "byte_vector": {
        "type": "knn_vector",
        "dimension": 768,
        "data_type": "byte",
        "space_type": "cosine",
        "method": {
          "name": "hnsw",
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

**Data Ingestion Example**:
```python
import requests
import json

def index_byte_vectors(vectors, index_name):
    """Ingest byte-quantized vectors"""
    for i, vector in enumerate(vectors):
        doc = {
            "byte_vector": vector.tolist(),  # Ensure int8 type
            "id": i
        }

        response = requests.post(
            f"http://localhost:9200/{index_name}/_doc/{i}",
            headers={"Content-Type": "application/json"},
            data=json.dumps(doc)
        )

        if response.status_code != 201:
            print(f"Error indexing document {i}: {response.text}")
```

### Quality Evaluation

**Quantization Quality Check**:
```python
def evaluate_quantization_quality(original, quantized, scale_factor):
    """Evaluate quantization quality"""
    # Dequantize
    dequantized = quantized.astype(np.float32) / scale_factor

    # Calculate similarity
    similarities = []
    for i in range(len(original)):
        sim = np.dot(original[i], dequantized[i]) / (
            np.linalg.norm(original[i]) * np.linalg.norm(dequantized[i])
        )
        similarities.append(sim)

    avg_similarity = np.mean(similarities)
    min_similarity = np.min(similarities)

    print(f"Average cosine similarity: {avg_similarity:.4f}")
    print(f"Minimum cosine similarity: {min_similarity:.4f}")

    if avg_similarity > 0.95:
        print("✓ Excellent quantization quality")
    elif avg_similarity > 0.90:
        print("⚠ Good quantization quality")
    else:
        print("✗ Poor quantization quality, consider other methods")

    return avg_similarity
```

## FP16 Quantization (Half-Precision Floating-Point Quantization)

### Technical Characteristics

**Numerical Range**: [-65504.0, 65504.0]
**Compression Ratio**: 2×
**Precision Loss**: Very small (< 2%)

### Configuration Examples

**Basic Configuration**:
```json
{
  "mappings": {
    "properties": {
      "fp16_vector": {
        "type": "knn_vector",
        "dimension": 768,
        "space_type": "cosine",
        "method": {
          "name": "hnsw",
          "engine": "faiss",
          "parameters": {
            "encoder": {
              "name": "sq",
              "parameters": {
                "type": "fp16",
                "clip": true
              }
            },
            "ef_construction": 256,
            "m": 8
          }
        }
      }
    }
  }
}
```

**clip Parameter Description**:
- `clip: true`: Automatically clips out-of-range values to [-65504.0, 65504.0]
- `clip: false`: Rejects vectors with out-of-range values (default)

### Data Preprocessing

**Range Check and Preprocessing**:
```python
def preprocess_for_fp16(vectors):
    """Preprocess vectors for FP16 quantization"""
    # Check value range
    min_val = np.min(vectors)
    max_val = np.max(vectors)

    print(f"Original value range: [{min_val:.4f}, {max_val:.4f}]")

    # Check if clipping is needed
    if min_val < -65504.0 or max_val > 65504.0:
        print("⚠ Clipping to FP16 range required")
        vectors = np.clip(vectors, -65504.0, 65504.0)
        print("✓ Clipped to FP16 range")
    else:
        print("✓ Value range compatible with FP16")

    return vectors

# Usage example
vectors = np.random.randn(1000, 768) * 1000  # May exceed range
processed_vectors = preprocess_for_fp16(vectors)
```

### Performance Benchmarks

**FP16 vs Original Precision Comparison**:
```python
def benchmark_fp16_performance():
    """FP16 performance benchmark"""
    results = {
        "compression_ratio": 2.0,
        "memory_reduction": "50%",
        "index_time_overhead": "< 5%",
        "query_latency_overhead": "< 10%",
        "recall_loss": "< 2%",
        "recommended_scenarios": [
            "Applications requiring very high precision",
            "Conservative cost optimization strategies",
            "Datasets with vector values within supported range"
        ]
    }
    return results
```

## Product Quantization

### Technical Principles

**Splitting Strategy**:
```
Original vector (d dimensions) → m sub-vectors (d/m dimensions)
Each sub-vector → code_size bit encoding
Total compression → m × code_size bits
```

**Compression Ratio Calculation**:
```
Compression ratio = (d × 32) / (m × code_size)

Example (d=1024, m=128, code_size=8):
Compression ratio = (1024 × 32) / (128 × 8) = 32×
```

### Implementation Steps

**Step 1: Create Training Index**
```json
PUT /pq-training-index
{
  "settings": {
    "number_of_shards": 1,
    "number_of_replicas": 0
  },
  "mappings": {
    "properties": {
      "training_vector": {
        "type": "knn_vector",
        "dimension": 1024
      }
    }
  }
}
```

**Step 2: Ingest Training Data**
```python
def prepare_training_data(vectors, sample_ratio=0.1):
    """Prepare PQ training data"""
    # Randomly sample training data
    n_samples = int(len(vectors) * sample_ratio)
    indices = np.random.choice(len(vectors), n_samples, replace=False)
    training_vectors = vectors[indices]

    # Ensure at least 256 samples (2^code_size)
    if len(training_vectors) < 256:
        print("⚠ Insufficient training data, recommend at least 256 samples")

    return training_vectors

# Ingest training data
training_data = prepare_training_data(all_vectors)
for i, vector in enumerate(training_data):
    doc = {"training_vector": vector.tolist()}
    # Ingest into training index...
```

**Step 3: Train Quantizer Model**
```json
POST /_plugins/_knn/models/pq-model-1024/_train
{
  "training_index": "pq-training-index",
  "training_field": "training_vector",
  "dimension": 1024,
  "description": "PQ model for 1024-dim vectors",
  "method": {
    "name": "hnsw",
    "engine": "faiss",
    "parameters": {
      "encoder": {
        "name": "pq",
        "parameters": {
          "code_size": 8,
          "m": 128
        }
      },
      "ef_construction": 256,
      "m": 8
    }
  }
}
```

**Step 4: Create Production Index**
```json
PUT /pq-production-index
{
  "settings": {
    "number_of_shards": 5,
    "number_of_replicas": 1,
    "index.knn": true
  },
  "mappings": {
    "properties": {
      "title": {"type": "text"},
      "content": {"type": "text"},
      "pq_vector": {
        "type": "knn_vector",
        "model_id": "pq-model-1024"
      }
    }
  }
}
```

### Parameter Optimization

**Key Parameter Descriptions**:
- `m`: Number of sub-vectors, typically dimension/8
- `code_size`: Encoding bits per sub-vector, typically 8
- Training data volume: At least 2^code_size samples

**Parameter Selection Guide**:
```python
def calculate_pq_parameters(dimension):
    """Calculate PQ parameters"""
    # Recommended m values
    m_options = []
    for m in [8, 16, 32, 64, 128]:
        if dimension % m == 0:
            m_options.append(m)

    recommended_m = dimension // 8  # Typically choose d/8
    if recommended_m not in m_options:
        recommended_m = min(m_options, key=lambda x: abs(x - dimension//8))

    # code_size is typically fixed at 8
    code_size = 8

    # Calculate compression ratio
    compression_ratio = (dimension * 32) // (recommended_m * code_size)

    return {
        "dimension": dimension,
        "recommended_m": recommended_m,
        "code_size": code_size,
        "compression_ratio": compression_ratio,
        "min_training_samples": 2 ** code_size
    }

# Example
params = calculate_pq_parameters(1024)
print(f"Recommended config: m={params['recommended_m']}, compression ratio={params['compression_ratio']}×")
```

### Quality Evaluation

**PQ Model Quality Check**:
```python
def evaluate_pq_model(model_id, test_vectors):
    """Evaluate PQ model quality"""
    # Quantize using the model
    quantized_results = []

    for vector in test_vectors:
        # Get quantized results via API
        response = requests.post(
            f"http://localhost:9200/_plugins/_knn/models/{model_id}/_search",
            json={"vector": vector.tolist(), "k": 1}
        )
        quantized_results.append(response.json())

    # Calculate reconstruction error
    reconstruction_errors = []
    for original, quantized in zip(test_vectors, quantized_results):
        error = np.linalg.norm(original - quantized["reconstructed"])
        reconstruction_errors.append(error)

    avg_error = np.mean(reconstruction_errors)
    print(f"Average reconstruction error: {avg_error:.4f}")

    if avg_error < 0.1:
        print("✓ Excellent PQ model quality")
    elif avg_error < 0.2:
        print("⚠ Good PQ model quality")
    else:
        print("✗ Poor PQ model quality, consider increasing training data or adjusting parameters")
```

## Disk Mode Quantization

### Built-in Quantization Support

Disk mode supports built-in scalar quantization without preprocessing:

```json
{
  "mappings": {
    "properties": {
      "disk_vector": {
        "type": "knn_vector",
        "dimension": 768,
        "mode": "on_disk",
        "compression_level": "8x",
        "method": {
          "name": "hnsw",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512
          }
        }
      }
    }
  }
}
```

### Compression Level Mapping

| Compression Level | Quantization Method | Bits | Memory Savings |
|----------|----------|------|----------|
| 2x | FP16 | 16-bit | 50% |
| 4x | Byte/Int8 | 8-bit | 75% |
| 8x | 4-bit | 4-bit | 87.5% |
| 16x | 2-bit | 2-bit | 93.75% |
| 32x | Binary | 1-bit | 96.875% |

### Rescoring Mechanism

**Two-Stage Search Configuration**:
```json
{
  "query": {
    "knn": {
      "disk_vector": {
        "vector": [...],
        "k": 10,
        "method_parameters": {
          "ef_search": 512
        },
        "rescore": {
          "oversample_factor": 5.0
        }
      }
    }
  }
}
```

**oversample_factor Tuning**:
```python
def tune_oversample_factor(compression_level, target_recall=0.90):
    """Tune oversample_factor based on compression level"""
    factor_map = {
        "2x": 1.0,    # FP16 typically doesn't need rescoring
        "4x": 1.0,    # Byte quantization has high precision
        "8x": 2.0,    # 4-bit needs moderate rescoring
        "16x": 3.0,   # 2-bit needs more rescoring
        "32x": 5.0    # 1-bit needs extensive rescoring
    }

    base_factor = factor_map.get(compression_level, 3.0)

    # Adjust based on target recall
    if target_recall > 0.95:
        return base_factor * 1.5
    elif target_recall < 0.85:
        return base_factor * 0.7
    else:
        return base_factor
```

## Quantization Method Selection Decision Tree

### Decision Flow

```python
def choose_quantization_method(requirements):
    """Quantization method selection decision tree"""

    # 1. Cost priority assessment
    if requirements["cost_priority"] == "extreme":
        if requirements["has_training_data"]:
            return "Product Quantization (64x)"
        else:
            return "Binary Quantization (32x)"

    # 2. Performance requirements assessment
    if requirements["latency_requirement"] < 20:  # ms
        if requirements["recall_tolerance"] < 0.02:
            return "FP16 Quantization (2x)"
        elif requirements["recall_tolerance"] < 0.05:
            return "Byte Quantization (4x)"
        else:
            return "Binary Quantization (8x-16x)"

    # 3. Data characteristics assessment
    if requirements["vector_dimension"] < 384:
        return "FP16 Quantization (2x)"  # Low-dimensional vectors not suited for high compression
    elif requirements["vector_dimension"] >= 768:
        return "Binary Quantization (32x)"  # High-dimensional vectors suited for binary quantization

    # 4. Default recommendation
    return "Byte Quantization (4x)"  # Balanced choice

# Usage example
requirements = {
    "cost_priority": "high",
    "latency_requirement": 50,  # ms
    "recall_tolerance": 0.05,
    "vector_dimension": 768,
    "has_training_data": False
}

recommended = choose_quantization_method(requirements)
print(f"Recommended quantization method: {recommended}")
```

### Scenario-Based Recommendations

**Real-Time Recommendation System**:
```json
{
  "scenario": "real_time_recommendation",
  "requirements": {
    "latency": "< 10ms",
    "qps": "> 1000",
    "recall": "> 0.95"
  },
  "recommended": "FP16 Quantization + Memory Mode",
  "configuration": {
    "compression_level": "2x",
    "mode": "in_memory",
    "instance_type": "r8g.xlarge+"
  }
}
```

**Batch Processing Analytics**:
```json
{
  "scenario": "batch_processing",
  "requirements": {
    "latency": "< 200ms",
    "qps": "< 100",
    "cost": "minimize"
  },
  "recommended": "Binary Quantization + Disk Mode",
  "configuration": {
    "compression_level": "32x",
    "mode": "on_disk",
    "instance_type": "r8g.large"
  }
}
```

**General Production Environment**:
```json
{
  "scenario": "general_production",
  "requirements": {
    "latency": "< 50ms",
    "qps": "100-1000",
    "balance": "cost_performance"
  },
  "recommended": "Byte Quantization + Memory Mode",
  "configuration": {
    "compression_level": "4x",
    "mode": "in_memory",
    "instance_type": "r8g.xlarge"
  }
}
```

## Monitoring and Maintenance

### Key Monitoring Metrics

**Quantization Quality Metrics**:
```python
def monitor_quantization_quality():
    """Monitor quantization quality"""
    metrics = {
        "recall_at_k": {
            "target": "> 0.90",
            "alert_threshold": "< 0.85",
            "measurement": "Periodic recall testing"
        },
        "precision_at_k": {
            "target": "> 0.85",
            "alert_threshold": "< 0.80",
            "measurement": "Precision evaluation"
        },
        "query_latency": {
            "target": "< target latency",
            "alert_threshold": "> target latency × 1.5",
            "measurement": "P95 latency monitoring"
        }
    }
    return metrics
```

**Resource Usage Monitoring**:
```python
def monitor_resource_usage():
    """Monitor resource usage"""
    return {
        "memory_usage": "< 85%",
        "cpu_usage": "< 80%",
        "disk_iops": "< 80%",
        "cache_hit_rate": "> 95%"
    }
```

### Automated Testing

**Recall Regression Testing**:
```python
import schedule
import time

def automated_recall_test():
    """Automated recall regression test"""
    # 1. Prepare test queries
    test_queries = load_test_queries()

    # 2. Execute searches
    results = []
    for query in test_queries:
        result = search_with_quantized_index(query)
        results.append(result)

    # 3. Calculate recall
    recall = calculate_recall(results, ground_truth)

    # 4. Check threshold
    if recall < RECALL_THRESHOLD:
        send_alert(f"Recall degraded: {recall:.3f}")

    # 5. Log history
    log_metric("recall_at_k", recall)

# Run recall test daily
schedule.every().day.at("02:00").do(automated_recall_test)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### Failure Recovery

**Quantization Failure Recovery Process**:
```python
def quantization_failure_recovery():
    """Quantization failure recovery process"""

    # 1. Detect failure type
    failure_type = detect_failure_type()

    if failure_type == "recall_degradation":
        # Recall degraded - reduce compression level
        return "reduce_compression_level"

    elif failure_type == "performance_degradation":
        # Performance degraded - optimize parameters
        return "optimize_parameters"

    elif failure_type == "index_corruption":
        # Index corrupted - rebuild index
        return "rebuild_index"

    else:
        # Unknown issue - rollback to original configuration
        return "rollback_to_original"

def execute_recovery_plan(plan):
    """Execute recovery plan"""
    if plan == "reduce_compression_level":
        # Create new index with lower compression level
        create_index_with_lower_compression()

    elif plan == "optimize_parameters":
        # Adjust HNSW parameters
        update_hnsw_parameters()

    elif plan == "rebuild_index":
        # Rebuild index from backup
        rebuild_from_backup()

    elif plan == "rollback_to_original":
        # Switch back to original index
        switch_to_backup_index()
```

## Best Practices Summary

### Implementation Recommendations

1. **Phased Deployment**:
   - Start with conservative FP16 quantization
   - Gradually try methods with higher compression ratios
   - Thoroughly test the results at each stage

2. **Thorough Testing**:
   - Establish a complete recall test dataset
   - Conduct A/B testing to validate business impact
   - Monitor key performance metrics

3. **Monitoring System**:
   - Establish automated quality monitoring
   - Set reasonable alert thresholds
   - Prepare rapid rollback mechanisms

4. **Parameter Tuning**:
   - Choose appropriate quantization methods based on data characteristics
   - Optimize HNSW parameters for specific scenarios
   - Continuously monitor and adjust configurations

By systematically applying these quantization techniques, you can achieve significant cost savings while maintaining search quality, providing sustainable solutions for large-scale vector search applications.
