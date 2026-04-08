# Neural Search

Neural Search integrates ML models into the OpenSearch search pipeline. It provides ingest processors that generate embeddings at index time and query types that generate embeddings at search time, enabling semantic search without external preprocessing.

## Key Concepts

- **Text embedding processor** — An ingest pipeline processor that calls a deployed text embedding model to convert text fields into dense vector embeddings at index time.
- **Sparse encoding processor** — An ingest pipeline processor that calls a sparse encoding model (e.g., neural sparse) to generate sparse token-weight vectors at index time.
- **Neural query** — A query type that takes raw text, generates an embedding using a deployed model, and performs k-NN search. Replaces the need to pre-compute query vectors.
- **Neural sparse query** — A query type for sparse vector search. Sends query text through a sparse encoding model and matches against sparse vector fields.
- **Hybrid search** — Combines neural (semantic) and keyword (BM25) search using a search pipeline with a `normalization_processor` that merges scores.
- **Normalization processor** — A search pipeline processor that normalizes and combines scores from multiple query types (e.g., min-max normalization with arithmetic or harmonic mean combination).
- **Multimodal search** — Use a multimodal embedding model to search across text and images in the same vector space.
- **Conversational search** — Combine neural search with an LLM to generate natural-language answers from search results using a `retrieval_augmented_generation` processor.

## Common Use Cases

- Semantic search over documents using dense embeddings
- Sparse neural search for efficient token-level matching
- Hybrid search combining BM25 and neural relevance
- Multimodal search across text and images
- RAG (retrieval-augmented generation) with conversational search

## Tutorials

- [Getting started with semantic and hybrid search](https://docs.opensearch.org/latest/tutorials/vector-search/neural-search-tutorial/) — End-to-end walkthrough covering index setup, model deployment, and queries
- [Semantic search tutorials](https://docs.opensearch.org/latest/tutorials/vector-search/semantic-search/index/) — Provider-specific guides (OpenAI, Cohere, Bedrock Titan, SageMaker, and more)
- [Reranking tutorials](https://docs.opensearch.org/latest/tutorials/reranking/index/) — Cross-encoder, Bedrock, Cohere, and SageMaker reranking

## Official Documentation

- [Neural search overview](https://docs.opensearch.org/latest/search-plugins/neural-search/)
- [Text embedding processor](https://docs.opensearch.org/latest/ingest-pipelines/processors/text-embedding/)
- [Sparse encoding processor](https://docs.opensearch.org/latest/ingest-pipelines/processors/sparse-encoding/)
- [Neural query](https://docs.opensearch.org/latest/query-dsl/specialized/neural/)
- [Neural sparse query](https://docs.opensearch.org/latest/query-dsl/specialized/neural-sparse/)
- [Hybrid search](https://docs.opensearch.org/latest/search-plugins/hybrid-search/)
- [Conversational search](https://docs.opensearch.org/latest/search-plugins/conversational-search/)
- [Semantic search tutorial](https://docs.opensearch.org/latest/search-plugins/semantic-search/)
