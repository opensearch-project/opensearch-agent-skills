---
name: document-processing
description: >
  Process unstructured documents (PDF, DOCX, PPTX, XLSX) into search-ready JSONL
  chunks using Docling. Runs locally — no AWS or cloud services needed. Use this
  skill when the user wants to prepare documents for indexing, chunk documents,
  evaluate chunk quality, or convert PDFs to searchable text. Activate even if the
  user says process documents, chunk my files, prepare for search, or Docling.
compatibility: Requires uv.
metadata:
  author: opensearch-project
  version: "1.0"
---

# Document Processing

Process unstructured documents into search-ready JSONL chunks using [Docling](https://docling.site/) (open-source, runs locally). No AWS credentials or cloud services needed.

## Prerequisites

- `uv` installed (for running Python scripts)

## When to Use

- User has unstructured documents (PDF, DOCX, PPTX, XLSX)
- User wants to prepare documents for OpenSearch indexing
- User wants to inspect or evaluate chunk quality

## Output

JSONL files at `.opensearch/chunks/<index>/<filename>.jsonl`. Each line:
```json
{"text": "...", "headings": ["Section Title"], "source_file": "doc.pdf", "chunk_id": 0, "page_number": 1}
```

The JSONL output can be ingested into any OpenSearch target:
- **Local cluster** — bulk-index directly
- **AOS domain / AOSS collection** — via [managed-ingestion-service](../../cloud/managed-ingestion-service/SKILL.md) (OSIS pipeline)

## Reference

See [document_processing_guide.md](document_processing_guide.md) for the full workflow:
processing profiles, quality evaluation, and chunking adjustments.
