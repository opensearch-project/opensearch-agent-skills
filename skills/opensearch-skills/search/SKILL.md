---
name: search
description: >
  Build search applications with OpenSearch. Use this skill when the user
  mentions search app, index setup, search architecture, semantic search,
  vector search, hybrid search, BM25, dense vector, sparse vector, agentic
  search, RAG, embeddings, KNN, PDF ingestion, document processing, search
  quality evaluation, or any related search topic. Also covers capturing
  user behavior from a search application — User Behavior Insights (UBI),
  click tracking, clickstream, impressions, search analytics.
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
| [ubi](ubi/SKILL.md) | Instrument an existing search application with User Behavior Insights — one guided session from no behavioral data to verified joinable events, then the return visits that review the metrics, extend capture to new features, turn accumulated clicks into a relevance judgment list, and put the metrics on a dashboard |

## When to Use

Read [opensearch-launchpad/SKILL.md](opensearch-launchpad/SKILL.md) when the user wants to:
- Build a new search application
- Set up an OpenSearch index with a specific search strategy
- Deploy ML models for semantic or hybrid search
- Evaluate and tune search quality
- Process documents (PDF, DOCX) for search ingestion

Read [ubi/SKILL.md](ubi/SKILL.md) when the user wants to:
- Capture user behavior from an existing search application
- Set up User Behavior Insights (UBI), click tracking, or clickstream data
- Record impressions and user events that join back to their queries
- Add search analytics instrumentation to an app
- Verify or debug an existing UBI setup — events missing, not joining, or broken
- Review how the captured metrics are doing against the targets the team agreed
- Extend an existing capture to a newly shipped feature
- Turn accumulated clicks and impressions into a relevance judgment list — judging search from their own users' behavior, not a public benchmark (tuning a ranker with that list stays with opensearch-launchpad)
- Build the OpenSearch Dashboards panels for metrics already being captured
- Do any of the above on Amazon OpenSearch Service — ubi carries the plugin-less managed path
