---
name: search
description: >
  Build search applications with OpenSearch. Use this skill when the user
  mentions search app, index setup, search architecture, semantic search,
  vector search, hybrid search, BM25, dense vector, sparse vector, agentic
  search, RAG, embeddings, KNN, PDF ingestion, document processing, search
  quality evaluation, ECM, document
  permissions, permission-aware search, ACL-aware search, document-level
  security, DLS, permission-aware RAG, or any related search topic.
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
| [permission-aware-search](permission-aware-search/SKILL.md) | Permission-aware search over any content, enforcing document-level access control at the OpenSearch shard level (DLS) with no application-layer filtering. Optional RAG (LLM answer generation) mode. Works with files, APIs, or ECM systems. |

## When to Use

Read [opensearch-launchpad/SKILL.md](opensearch-launchpad/SKILL.md) when the user wants to:
- Build a new search application
- Set up an OpenSearch index with a specific search strategy
- Deploy ML models for semantic or hybrid search
- Evaluate and tune search quality
- Process documents (PDF, DOCX) for search ingestion

Read [permission-aware-search/SKILL.md](permission-aware-search/SKILL.md) when the user wants to:
- Enforce document-level permissions at search time (users see only what they can access)
- Set up ACL-aware or multi-tenant search where access is enforced by OpenSearch, not application code
- Build permission-aware RAG where the LLM only ever sees documents the caller may read
- Index content with per-document access lists from files, APIs, or an ECM system
