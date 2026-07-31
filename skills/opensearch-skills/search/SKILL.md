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
| [opensearch-blueprint](opensearch-blueprint/SKILL.md) | Index design compiler — turns requirements into a linted, cluster-verified blueprint (analysis, mappings, k-NN, pipelines, ISM); also extracts a blueprint from an existing index |

## When to Use

Read [opensearch-launchpad/SKILL.md](opensearch-launchpad/SKILL.md) when the user wants to:
- Build a new search application
- Set up an OpenSearch index with a specific search strategy
- Deploy ML models for semantic or hybrid search
- Evaluate and tune search quality
- Process documents (PDF, DOCX) for search ingestion

Read [opensearch-blueprint/SKILL.md](opensearch-blueprint/SKILL.md) when the user wants to:
- Design or review an index mapping, analysis chain, or k-NN configuration
- Validate a design before loading data (`_analyze`, `_validate/query`)
- Debug an analyzer that tokenizes unexpectedly, or hybrid weights that misbehave
- Document, audit, or migrate an index that already exists

**Choosing between them:** launchpad is the guided build — sample data in,
running UI out. Blueprint is the design artifact — a reviewable, portable,
re-appliable spec. Users who already know what they want, or who need to review
someone else's index, want blueprint. Hand off to launchpad to load data.
