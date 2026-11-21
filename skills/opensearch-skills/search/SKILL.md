---
name: search
description: >
  Build search applications with OpenSearch. Use this skill when the user
  mentions search app, index setup, search architecture, semantic search,
  vector search, hybrid search, BM25, dense vector, sparse vector, agentic
  search, RAG, embeddings, KNN, PDF ingestion, document processing, search
  quality evaluation, relevance debugging, explain score, or any related
  search topic.
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
| [relevance-x-ray](relevance-x-ray/SKILL.md) | Collects rank, competitor, analyzer, and explain evidence for one query/document pair; reports a supported finding or explicitly abstains |

## When to Use

Read [opensearch-launchpad/SKILL.md](opensearch-launchpad/SKILL.md) when the user wants to:
- Build a new search application
- Set up an OpenSearch index with a specific search strategy
- Deploy ML models for semantic or hybrid search
- Evaluate and tune search quality across many queries
- Process documents (PDF, DOCX) for search ingestion

Read [relevance-x-ray/SKILL.md](relevance-x-ray/SKILL.md) when the user wants to:
- Understand why one specific document ranked too low or too high for a given query
- Interpret a confusing `_explain` output
- Inspect a hybrid query's raw BM25 and k-NN legs without conflating them with normalized pipeline contributions
- Get a synonym suggestion backed by a measured before/after rank delta
