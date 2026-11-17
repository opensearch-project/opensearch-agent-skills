# Document Processing Guide

> **Scope:** this guide covers **local document processing** — turning source files
> (PDF/DOCX/PPTX/XLSX) into search-ready JSONL chunks. It ends at the chunk artifact
> (`.opensearch/chunks/<index>/<file>.jsonl`). The next stage — indexing those chunks into
> OpenSearch with embeddings — is handled either locally or via cloud ingestion
> ([managed-ingestion-service](../../cloud/managed-ingestion-service/SKILL.md)).

## Overview

Process PDF, DOCX, PPTX, XLSX, HTML, and other unstructured documents into search-ready chunks using [Docling](https://docling-project.github.io/docling/) (open-source, runs locally). The `ingest` command handles convert → chunk → export in one step.

## When to Use

- User has unstructured documents (PDF, DOCX, PPTX, XLSX, images, audio)
- User wants to prepare documents for OpenSearch indexing
- User wants to inspect or evaluate chunk quality before cloud ingestion

## Trigger Phrases

Any of these user intents should start document processing. The user does **not** need to mention "Docling", "eval-document", or internal command names:

- "Process these PDFs / documents / files"
- "Ingest these for search"
- "Chunk these documents"
- "I have files to index"
- "Prepare these for OpenSearch"

## Key Constraints

- Default to auto-detection — never ask "which profile?" unless detection returns low confidence
- Do **NOT** auto re-ingest. Always explain the issue and ask the user first.
- First run downloads AI models (~1.5 GB) automatically
- Default processes first 10 pages (`--max-pages`); prompts for truncation if exceeded

## Quick Reference

| Profile | Best for | What it enables |
|---------|----------|-----------------|
| `semantic` | Digital-text, prose-heavy (papers, reports, contracts) | Hierarchy-aware chunking respecting headings/sections |
| `tables` | Table-heavy (financial reports, spec sheets) | TableFormer table extraction; tables serialized to markdown |
| `scanned` | Scanned / image-only pages | OCR (RapidOCR, PP-OCRv4) before chunking |
| `multimodal` | Figure/diagram-rich documents | VLM image descriptions (SmolVLM-256M) |

Auto-detect does **not** reliably pick `tables` — if the user mentions important tables, use `--profile tables` explicitly.

---

## Processing Flow

### Step 1: Process documents

```bash
uv run python scripts/opensearch_ops.py ingest \
  --source <file> \
  --index <index>
```

Options:
- `--source` — Path to source file (required)
- `--index` — Target index name (auto-derived from filename if omitted)
- `--profile` — `semantic`, `tables`, `scanned`, `multimodal` (omit for auto-detection)
- `--max-pages` — Max pages to process (default: 10)
- `--max-tokens` — Override the profile's chunk-size default (default: profile-specific, typically 512)

Output: `.opensearch/chunks/<index>/<filename>.jsonl`

### Step 2: Report results

Present a summary table to the user:

| File | Profile | Pages | Chunks |
|------|---------|-------|--------|
| ... | ... | ... | ... |

### Step 3: Offer quality evaluation (optional)

Ask: "Would you like me to evaluate the chunk quality?"

If yes, follow the [Quality Evaluation](#quality-evaluation-agent-as-judge) section below.

---

## Quality Evaluation (agent-as-judge)

Quality is judged semantically by the agent, not by hard-coded rules. The verdict is cached for later use.

### Get material to judge

```bash
uv run python scripts/opensearch_ops.py eval-document --index <index> --samples 8
```

Emits: profile, metrics, judging dimensions, and a representative chunk sample.

### Judge and save verdict

Assess each dimension as `good | fair | poor`, then give an overall verdict:

Per-profile dimensions:
- **semantic:** text_fidelity, reading_order, chunk_boundaries, heading_structure
- **tables:** table_structure, table_content_fidelity, text_fidelity, completeness
- **scanned:** ocr_text_fidelity, reading_order, completeness
- **multimodal:** image_descriptions, text_fidelity, reading_order, completeness

Save via stdin or file:

```bash
uv run python scripts/opensearch_ops.py save-quality --index <index> --verdict-file verdict.json
```

Schema:
```json
{
  "overall": "good",
  "dimensions": [{"name": "text_fidelity", "rating": "good", "note": "..."}],
  "summary": "one or two sentences",
  "recommendations": ["concrete next step"]
}
```

### When verdict is `needs_attention`

Do **NOT** automatically re-ingest. Instead:
- Explain what went wrong and why
- Recommend a specific fix (e.g., "re-process with `--profile tables`")
- **Ask the user** if they want to re-ingest

---

## Adjusting Chunking

Re-ingest is expensive — only do this when a quality check provides evidence.

| Signal | Likely cause | Fix |
|--------|--------------|-----|
| Results lack context | Chunks too small | Increase `--max-tokens` |
| Results contain irrelevant noise | Chunks too large | Decrease `--max-tokens` |
| Tables not found | Table extraction not run | `--profile tables` |
| Scanned pages empty/garbled | Needs OCR | `--profile scanned` |
| Figures/diagrams missing | Visual content not described | `--profile multimodal` |

---

## JSONL Chunk Format

Each line in the output `.jsonl` file is a JSON object with these fields:

```json
{"text": "...", "headings": ["Section Title"], "source_file": "doc.pdf", "chunk_id": 0, "page_number": 1}
```

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | The chunk content (required) |
| `headings` | array | Section headings this chunk belongs to |
| `source_file` | string | Original source filename |
| `chunk_id` | int | Sequential chunk index within the file |
| `page_number` | int | Source page number |

Before uploading to S3, validate that each line is valid JSON with at minimum a `text` field.

---

## Next Stage: Indexing the Chunks

This guide stops at the chunk artifact (`.opensearch/chunks/<index>/<file>.jsonl`).

The JSONL output can be ingested into any OpenSearch target:
- **Local cluster** — bulk-index directly via `index-bulk`
- **AOS domain / AOSS collection** — upload to S3 and ingest via OSIS

For cloud-scale ingestion via OSIS, see [managed-ingestion-service](../../cloud/managed-ingestion-service/SKILL.md).

---

## Performance Tips

- Default `semantic` profile keeps OCR **off** for speed on digital-text documents
- Use `--max-pages` to limit processing for large documents
- Use `--background` for large files — poll progress with `ingest-status`
- For full document processing at scale, use cloud ingestion (private beta — contact opensearch-agent-skills-interests@amazon.com)
