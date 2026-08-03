---
name: search
description: >
  Build search applications with OpenSearch. Use this skill when the user
  mentions search app, index setup, search architecture, semantic search,
  vector search, hybrid search, BM25, dense vector, sparse vector, agentic
  search, RAG, embeddings, KNN, PDF ingestion, document processing, search
  quality evaluation, or any related search topic.
compatibility: Requires Docker and uv.
metadata:
  author: opensearch-project
  version: "2.0"
---

# Search

Category skill for building search applications with OpenSearch.

## Skills

| Skill | Description |
|---|---|
| [opensearch-launchpad](opensearch-launchpad/SKILL.md) | End-to-end search application builder — from sample data to a running search UI with BM25, semantic, hybrid, or agentic search |
| [opensearch-vector-search](opensearch-vector-search/SKILL.md) | Vector search tuning and operations — k-NN, HNSW, quantization, disk mode, sizing, cost, and read-only cluster analysis |

## When to Use

Read [opensearch-launchpad/SKILL.md](opensearch-launchpad/SKILL.md) when the user wants to:
- Build a new search application
- Set up an OpenSearch index with a specific search strategy
- Deploy ML models for semantic or hybrid search
- Evaluate and tune search quality
- Process documents (PDF, DOCX) for search ingestion

Read [opensearch-vector-search/SKILL.md](opensearch-vector-search/SKILL.md) when the user wants to:
- Tune an existing vector search or k-NN workload
- Size vector memory, shards, replicas, or instances
- Choose HNSW parameters, quantization, or disk mode
- Optimize vector queries, filters, recall, latency, or cost
- Analyze an existing vector search cluster in read-only mode
