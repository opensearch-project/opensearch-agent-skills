# OpenSearch Semantic Search Methods Guide

---

## 1. BM25 (Lexical Search)

### 1.1 Overview

BM25 is the default ranking algorithm in OpenSearch. It calculates relevance based on term frequency (TF), inverse document frequency (IDF), and document length normalization.

### 1.2 Accuracy Characteristics

| Aspect | Rating | Notes |
|--------|--------|-------|
| Exact Match Precision | 5/5 | Excellent for exact keyword queries |
| Semantic Understanding | 2/5 | Cannot understand synonyms or paraphrases |
| Out-of-vocabulary Handling | 1/5 | Fails completely on unseen terms |
| Domain-specific Terms | 5/5 | Excellent for technical/domain vocabulary |

**Strengths:**
- Perfect for exact keyword matching
- Handles rare/domain-specific terminology well
- No vocabulary mismatch between query and index

**Weaknesses:**
- Cannot understand semantic meaning
- Fails on synonyms (e.g., "car" vs "automobile")
- Language-dependent (requires language-specific analyzers)

### 1.3 Cost Profile

| Resource | Cost Level | Details |
|----------|------------|---------|
| Storage | 1/5 (Low) | Only inverted index, typically 10-30% of raw text size |
| Memory | 1/5 (Low) | Field data cache only when needed |
| CPU (Indexing) | 1/5 (Low) | Simple tokenization and analysis |
| CPU (Query) | 1/5 (Low) | Efficient inverted index lookup |

**Storage Estimation:**
```
Index Size ≈ Raw Text Size × 0.1 to 0.3
Example: 1GB text → 100-300MB index
```

**Scaling Behavior:**
- Cost&Latency grows sub-linearly with data size
- Horizontal scaling is straightforward
- Query complexity significantly affects latency

### 1.5 Unique Features & Query Types

BM25 supports several special query types that vector search cannot:

| Query Type | Description | Use Case |
|------------|-------------|----------|
| `prefix` | Matches terms starting with specified prefix | Autocomplete, partial matching |
| `wildcard` | Pattern matching with * and ? | Flexible string matching |
| `regexp` | Regular expression matching | Complex pattern matching |
| `fuzzy` | Tolerates spelling mistakes | Typo tolerance |
| `ngram` | Matches character n-grams | Partial word matching |
| `phrase` | Matches exact phrase in order | Exact phrase search |
| `span` | Positional queries | Near queries, ordered matching |
| `term` | Exact term matching (no analysis) | Exact value matching |

### 1.6 Language Support

| Feature | Support Level | Notes |
|---------|---------------|-------|
| English | 5/5 | Excellent with standard analyzer |
| Other Languages | 4/5 | Requires language-specific analyzers |
| Cross-lingual | 0/5 | Not supported natively |
| CJK Languages | 3/5 | Requires specialized tokenizers (kuromoji, ik, etc.) |

### 1.7 When to Use BM25

**Recommended:**
- Exact keyword/phrase search requirements
- Autocomplete and typeahead features
- Domain-specific terminology search
- Regex or wildcard pattern matching
- Maximum cost efficiency required
- Low-latency requirements at any scale

**Not Recommended:**
- Semantic similarity search
- Cross-lingual search
- Synonym handling without manual configuration
- User queries differ significantly from document terminology

---

## 2. Dense Vector Search

### 2.1 Overview

Dense vector search uses neural network embeddings to represent text as dense floating-point vectors (typically 384-1536 dimensions). Similarity is computed using cosine similarity, dot product, or L2 distance.

### 2.2 Accuracy Characteristics

| Aspect | Rating | Notes |
|--------|--------|-------|
| Semantic Understanding | 5/5 | Captures meaning beyond keywords |
| Synonym Handling | 5/5 | Automatically handles synonyms |
| Cross-lingual | 5/5 | With multilingual models |
| Exact Match | 1/5 | Does not support exact keyword matches |
| Domain-specific | 3/5 | If your domain distribution differs greatly from general corpus, fine-tuning is required for good results |

**Strengths:**
- Understands semantic meaning
- Handles paraphrases and synonyms naturally
- Supports cross-lingual search with multilingual models
- Zero-shot transfer to new domains

**Weaknesses:**
- May miss exact keyword matches
- Requires embedding model
- Higher computational cost
- Quality depends heavily on embedding model choice

### 2.3 Index Algorithms (Core Structure)

These algorithms determine how vectors are organized and searched.

#### 2.3.1 HNSW (Hierarchical Navigable Small World)

**Overview:** Graph-based approximate nearest neighbor (ANN) algorithm. Default and most popular choice.

| Aspect | Details |
|--------|---------|
| **Accuracy** | 95-99%+ recall achievable with proper tuning |
| **Build Time** | Moderate to slow |
| **Query Latency** | Fast (1-50ms typically) |
| **Memory Requirement** | High - entire graph in memory (unless using quantization) |
| **Scalability** | Good, but memory-bound |

**Key Trade-off:**
Higher accuracy configurations require significantly more memory and result in slower build times.

**Memory Estimation (Raw):**
```
Memory = num_vectors × (dimensions × 4 bytes + m × 8 bytes + overhead)
Example: 10M vectors × 768 dims, m=16
Memory ≈ 10M × (768 × 4 + 16 × 8) ≈ 32GB
```

**Cost Profile:**
| Resource | Cost Level |
|----------|------------|
| Storage | 3/5 (Medium-High) |
| Memory | 5/5 (Very High) |
| CPU (Build) | 3/5 (Medium) |
| CPU (Query) | 2/5 (Low-Medium) |

**Best For:**
- Small to medium datasets that fit in memory
- Low-latency requirements
- High accuracy requirements

#### 2.3.2 IVF (Inverted File Index)

**Overview:** Clustering-based approach that partitions vectors into clusters (buckets).

| Aspect | Details |
|--------|---------|
| **Accuracy** | 85-95% recall typical |
| **Build Time** | Slow (requires training) |
| **Query Latency** | Medium (5-100ms) |
| **Memory Requirement** | Lower than HNSW (especially with PQ) |
| **Scalability** | Better for large datasets |

**Parameters:**
- `nlist`: Number of clusters. Typically sqrt(n) to n/1000
- `nprobe`: Clusters to search at query time. Higher = better recall, slower

**Memory Estimation:**
```
Memory = num_vectors × dimensions × 4 bytes + cluster_centroids
Much lower than HNSW as no graph structure overhead
```

**Best For:**
- Larger datasets where memory is constrained
- Can tolerate slightly lower accuracy
- Batch search workloads

#### 2.3.3 Disk-based Vector Search (mode: on_disk)

**Overview:** OpenSearch's solution for billion-scale vector search with limited memory (introduced in 2.17). It uses **Binary Quantization (BQ)** to keep a compressed index in memory while storing full-precision vectors on disk.

| Aspect | Details |
|--------|---------|
| **Accuracy** | Good recall (uses re-ranking from disk) |
| **Build Time** | Fast (BQ training is automatic) |
| **Query Latency** | Medium (10-100ms), depends on SSD speed |
| **Memory Requirement** | Very Low (uses 1-bit BQ compressed vectors in RAM) |
| **Scalability** | Excellent for billion-scale datasets |

**Configuration (`mode: on_disk`):**
- **Engine:** Uses `faiss` with `hnsw` method.
- **Quantization:** Automatically uses **Binary Quantization (BQ)** for the in-memory index.
  - *Note:* You cannot combine this with PQ (`encoder: pq`).
  - *Note:* BQ training is automatic during indexing (unlike PQ which often needs training data).
- **Process:**
  1. Searches in-memory BQ index (very fast, low precision).
  2. Fetches full vectors from disk for re-ranking to improve precision.

**Memory Estimation:**
```
Memory = num_vectors × dimensions / 8 (bits to bytes) + HNSW graph overhead
Example: 1B vectors × 768 dims (using BQ)
Memory ≈ 1B × 96 bytes ≈ 96 GB (manageable on a cluster)
vs. ~3TB for float32 vectors
```

**Cost Profile:**
| Resource | Cost Level |
|----------|------------|
| Storage | 4/5 (High - raw vectors + index) |
| Memory | 2/5 (Low) |
| CPU (Query) | 3/5 (Medium - BQ distance is fast, IO overhead exists) |
| SSD IOPS | 4/5 (High - fast NVMe required for re-ranking) |

**Best For:**
- Billion-scale datasets
- Cost-efficiency (trading RAM for SSD)
- High-throughput scenarios where RAM is the bottleneck

### 2.4 Compression & Quantization (For In-Memory Algorithms)

These techniques are explicit configurations for in-memory indices (HNSW/IVF).

*Decision Matrix:*
- If using `mode: on_disk` → You are using **BQ** (Disk-based).
- If using standard HNSW/IVF → You can optionally add **PQ** (`encoder: pq`) or **BQ** (via specific config) for memory reduction.

#### 2.4.1 Product Quantization (PQ)

**Overview:** Compression technique that breaks vectors into sub-vectors and encodes them. Used with `method: hnsw` or `method: ivf`.

| Aspect | Details |
|--------|---------|
| **Accuracy** | 80-90% recall (lossy) |
| **Training** | Requires a training step (often handled automatically or via API) |
| **Memory Reduction** | 10-50x compression |

**Memory Estimation:**
```
Compressed Memory = num_vectors × m × code_size / 8
Example: 10M vectors, m=64, code_size=8
Memory ≈ 10M × 64 × 1 byte = 640MB
```

#### 2.4.2 Binary Quantization (BQ) - In-Memory

**Overview:** Using BQ with in-memory HNSW (without offloading full vectors to disk) for extreme speed and compression.

| Aspect | Details |
|--------|---------|
| **Accuracy** | Lower than PQ generally, but faster |
| **Memory Reduction** | 32x compression (float32 -> 1 bit) |
| **Query Latency** | Ultra-fast (Hamming distance) |

### 2.5 Latency Scaling by Configuration

Scales with doc size O(log n)

### 2.6 Language Support

| Feature | Support Level | Notes |
|---------|---------------|-------|
| English | 5/5 | Excellent with most models |
| Multilingual | 5/5 | With multilingual models (mE5, multilingual-e5, etc.) |
| Cross-lingual | 5/5 | Query in one language, retrieve in another |
| Low-resource Languages | 3/5 | Depends on model training data |

### 2.7 Model Deployment Options

#### 2.7.1 Supported Modes
Dense vector search in OpenSearch supports three main deployment modes for embedding models:

1.  **API Services**: (e.g., Amazon Bedrock, OpenAI) - Best for ease of use and access to SOTA models.
2.  **OpenSearch Node (CPU)**: Best for self-contained deployments and moderate latency/throughput.
3.  **SageMaker GPU Endpoint**: Best for high-performance, low-latency production workloads with custom or open-source models.



### 2.8 Total Latency Composition

For Dense Vector Search, the total end-to-end latency is the sum of two distinct phases:

```
Total Latency = Embedding Inference Time + Vector Search Time (KNN)
```

1.  **Embedding Inference (CPU/GPU/API):** Time to convert the query text into a vector.
    *   *External API:* 50-200ms (network + inference)
    *   *Local CPU:* 10-100ms (depends on model size)
    *   *SageMaker/GPU:* 5-20ms
2.  **Vector Search (KNN):** Time to find nearest neighbors in the index.
    *   *HNSW:* 1-20ms (typically very fast)
    *   *IVF:* 10-100ms
    *   *Disk-based:* 20-100ms

**Critical Note:** Often, **inference time dominates** the total latency. Optimizing the index (HNSW vs IVF) yields diminishing returns if your embedding model takes 100ms to run.

### 2.9 When to Use Dense Vector

**Recommended:**
- Semantic similarity search
- Cross-lingual search requirements
- Synonym and paraphrase handling needed
- Natural language queries from users
- Question-answering systems
- RAG (Retrieval Augmented Generation) applications

**Not Recommended:**
- Exact keyword matching is critical
- Highly specialized domain vocabulary not covered by model
- Extremely cost-sensitive deployments
- Real-time autocomplete/typeahead
- Sub-millisecond latency requirements

---

## 3. Sparse Vector Search

### 3.1 Overview

Sparse vector search uses learned sparse representations where most dimensions are zero. Unlike dense vectors with 384-1536 dimensions all populated, sparse vectors may have 30,000+ dimensions but only 100-500 non-zero values.

### 3.2 How Neural Sparse Works

**Overview:** Uses neural networks to learn sparse representations with semantic meaning.

**How it works:**
1. Documents and queries are encoded into sparse vectors
2. Each dimension corresponds to a vocabulary token
3. Weights indicate semantic importance (not just term frequency)

**Advantages over BM25:**
- Learns semantic term expansion (e.g., "dog" activates "puppy", "canine")
- Trained on relevance signals
- Better zero-shot domain transfer

### 3.3 Search Modes: Doc-only (Recommended) vs Bi-encoder

OpenSearch Neural Sparse supports two modes. We **strongly recommend Doc-only mode** for most production use cases due to its superior performance-cost ratio.

#### 3.3.1 Doc-only Mode (Recommended)
In this mode, the heavy lifting is done during ingestion.
- **Ingestion**: Documents are encoded using a specialized "doc-only" model (e.g., `opensearch-neural-sparse-encoding-doc-v3-gte`).
- **Search**: The query is processed using a simple **tokenizer** (not a full model inference). 

**Why it is recommended:**
- **Zero Query Inference**: No heavy model inference is required at query time, only tokenization.
- **Low Latency**: Query latency is significantly lower (often 10x+ faster) than bi-encoder mode.
- **Lower Cost**: Reduces CPU/GPU requirements for search nodes.

**Model Combination Example:**
- Ingestion: `amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v3-gte`
- Search: `amazon/neural-sparse/opensearch-neural-sparse-tokenizer-v1`

#### 3.3.2 Bi-encoder Mode
In this mode, both documents and queries are processed by the same deep neural network.
- **Ingestion & Search**: Use the same model (e.g., `opensearch-neural-sparse-encoding-v2-distill`).

**Characteristics:**
- **Higher Relevance**: Generally achieves slightly better BEIR scores.
- **Higher Latency**: Requires running model inference for every query.

### 3.4 Index Backends

#### 3.4.1 rank_features Field (Inverted Index Based)

**Overview:** Uses OpenSearch's native inverted index structure optimized for sparse features.

| Aspect | Details |
|--------|---------|
| **Accuracy** | Exact (no approximation) |
| **Query Latency** | Scales with vocabulary overlap |
| **Memory** | Moderate |
| **Index Size** | Similar to text fields |

**Best For:**
- Exact sparse vector search
- Smaller datasets (< 50M documents)
- When accuracy is paramount

#### 3.4.2 SEISMIC (ANN-based Sparse Search)

**Overview:** Approximate nearest neighbor algorithm specifically designed for sparse vectors.

| Aspect | Details |
|--------|---------|
| **Accuracy** | 90%+ recall achievable |
| **Query Latency** | Much faster than rank_features for large data |
| **Memory** | Moderate |
| **Build Time** | Slower than rank_features |

**When to Use SEISMIC:**
- Large-scale datasets (> 10M documents), and latency-sensitive applications
- Can tolerate slight approximation

### 3.5 Accuracy Characteristics

| Aspect | Rating | Notes |
|--------|--------|-------|
| Semantic Understanding | 4/5 | Good, but generally slightly below dense |
| Exact Match | 4/5 | Better than dense vectors |
| Term Expansion | 5/5 | Learns relevant term expansion |
| Interpretability | 5/5 | Can see which terms matched |

### 3.6 Language Support

| Feature | Support Level | Notes |
|---------|---------------|-------|
| English | 5/5 | Excellent |
| Other Languages | 3/5 | Model-dependent |
| Cross-lingual | 1/5 | Limited, not effective |

### 3.7 Model Deployment Options

Sparse vector search (Neural Sparse) supports the following deployment modes:

1.  **OpenSearch Node (CPU)**: Generally only recommended for the **Tokenizer** in Doc-Only mode.
2.  **SageMaker GPU Endpoint**: Strongly recommended for Ingestion (Encoding) and Search (Bi-encoder mode).

For most use case, OpenSearch Node is only recommended for sparse tokenizer deployment. And sparse encoding model should be deployed on SageMaker GPU endpoint. The only exception is cost. i.e. user don't want to spend money on a SageMaker GPU instance.

### 3.8 When to Use Sparse Vector

**Recommended:**
- Balance between lexical and semantic search
- Users want semantic search, but don't want query-time model inference
- Users want extreme fast semantic search. use doc-only + seismic (for dense, the model inference takes tens of milliseconds)
- Interpretability is important (can see which terms matched)
- Lower memory budget than dense vectors (rank features)

**Not Recommended:**
- Cross-lingual search
- Maximum semantic understanding needed

---

## 4. Hybrid Search

### 4.1 Overview

Hybrid search combines multiple retrieval methods (BM25, dense vector, sparse vector) to leverage the strengths of each. OpenSearch supports hybrid search through the hybrid query type and score normalization.

### 4.2 Score Normalization
To combine scores from different methods (e.g., BM25 scores are unbounded, while vector cosine similarity is 0-1), OpenSearch provides several normalization techniques (Min-Max, L2, Harmonic Mean, etc.) to ensure scores are comparable before combination.

### 4.3 Cost
- **CPU Load**: The CPU load for a hybrid query is approximately the **sum of the loads** of its sub-queries.

### 4.4 Combination Strategy for Relevance
When maximum relevance is the primary goal, Hybrid Search is the recommended approach.

- **Hybrid Scope Rule**:
  - Use at most **two retrieval methods** per hybrid query.
  - Do **not** combine dense + sparse + BM25 in a single hybrid plan.

- **Recommended Combinations**:
  - **Dense + Sparse**: Have best search relevance. Provides two layers of semantic understanding (dense for context, sparse for learned expansion).
  - **Dense + BM25**: A robust baseline to combine semantic understanding with exact keyword precision.
  
- **Not Recommended**:
  - **Sparse + BM25**: Generally redundant. Sparse vectors already capture keyword information (lexical match) along with expansion, making the addition of BM25 less impactful for the cost.

### 4.5 When to Use Hybrid Search

**Recommended:**
- **Maximum Relevance**: When accuracy and recall are the top priorities.
- Mixed query types (some exact, some semantic).
- Unknown query distribution.
- Can afford additional infrastructure cost (higher CPU load).

**Not Recommended:**
- Strict cost constraints
- Simple use cases where one method suffices
- Sub-10ms latency requirements
- Development/prototype phase (start simple)

---

*Document Version: 1.0*
*Last Updated: January 2025*
*Applicable OpenSearch Versions: 2.9+*
