---
name: search
description: >
  Build search applications with OpenSearch. Use this skill when the user
  mentions search app, index setup, search architecture, semantic search,
  vector search, hybrid search, BM25, dense vector, sparse vector, agentic
  search, RAG, embeddings, KNN, PDF ingestion, document processing, search
  quality evaluation, RAG poisoning, indirect prompt injection, retrieval
  security, corpus provenance, or any related search topic.
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
| [rag-integrity-sentinel](rag-integrity-sentinel/SKILL.md) | Read-only investigation of indirect prompt injection, provenance drift, Unicode concealment, and semantic duplicate poisoning in RAG corpora |

## When to Use

Read [opensearch-launchpad/SKILL.md](opensearch-launchpad/SKILL.md) when the user wants to:
- Build a new search application
- Set up an OpenSearch index with a specific search strategy
- Deploy ML models for semantic or hybrid search
- Evaluate and tune search quality
- Process documents (PDF, DOCX) for search ingestion

Read [rag-integrity-sentinel/SKILL.md](rag-integrity-sentinel/SKILL.md) when
the user wants to:
- Investigate indirect prompt injection in retrieved documents
- Detect poisoned, concealed, or semantically replicated chunks
- Verify source metadata and content checksums
- Produce a human-approved RAG containment and verification plan
