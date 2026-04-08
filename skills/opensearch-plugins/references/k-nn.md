# k-NN (k-Nearest Neighbors)

The k-NN plugin enables vector search in OpenSearch. It supports approximate nearest neighbor (ANN) search using multiple engines and algorithms, as well as exact brute-force search. This is the foundation for semantic search, image similarity, recommendation systems, and other vector-based use cases.

## Key Concepts

- **Vector field** — A `knn_vector` field type in the index mapping that stores dense vectors.
- **Engines** — Three ANN engines are supported:
  - **Faiss** — Meta's library. Supports HNSW and IVF algorithms. Best for large-scale workloads.
  - **nmslib** — Supports HNSW only. Lightweight and fast for pure ANN.
  - **Lucene** — Native Lucene HNSW implementation. No native library dependency. Good default choice.
- **HNSW (Hierarchical Navigable Small World)** — A graph-based ANN algorithm. Good recall, tunable via `ef_construction` and `m` parameters.
- **IVF (Inverted File Index)** — A partition-based ANN algorithm (Faiss only). Splits vectors into clusters for faster search.
- **Space type** — The distance metric: `l2` (Euclidean), `cosinesimil` (cosine similarity), `innerproduct` (dot product), and others.
- **Model-based indices** — Train an IVF model on sample data, then create an index that uses the trained model.
- **Exact search** — Brute-force k-NN using a script score query. No ANN index needed. Guaranteed perfect recall but slower at scale.
- **Radial search** — Search for all vectors within a distance threshold or above a similarity score.

## Common Use Cases

- Semantic search (pair with text embedding models)
- Image or multimedia similarity search
- Recommendation engines
- Hybrid search combining k-NN with BM25 keyword scores

## Tutorials

- [Getting started with semantic and hybrid search](https://docs.opensearch.org/latest/tutorials/vector-search/neural-search-tutorial/) — Covers k-NN index setup end-to-end
- [Vector search tutorials](https://docs.opensearch.org/latest/tutorials/vector-search/) — All vector search tutorials

## Official Documentation

- [k-NN overview](https://docs.opensearch.org/latest/search-plugins/knn/index/)
- [k-NN index](https://docs.opensearch.org/latest/search-plugins/knn/knn-index/)
- [Approximate search](https://docs.opensearch.org/latest/search-plugins/knn/approximate-knn/)
- [Engine comparison](https://docs.opensearch.org/latest/search-plugins/knn/knn-index/#method-definitions)
- [Performance tuning](https://docs.opensearch.org/latest/search-plugins/knn/performance-tuning/)
- [Settings reference](https://docs.opensearch.org/latest/search-plugins/knn/settings/)
- [API reference](https://docs.opensearch.org/latest/search-plugins/knn/api/)
