# Document Processing with Docling

This guide covers how to process PDF, DOCX, PPTX, XLSX, HTML, and other document formats for ingestion into OpenSearch using [Docling](https://docling.site/).

## Overview

Docling is an open-source Python library (MIT license) by IBM Research that converts unstructured documents into structured data. It detects page layout, reading order, table structure, code blocks, formulas, and images using AI models, and runs locally on commodity hardware.

## Supported Input Formats

PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, CSV, images (PNG, JPEG, TIFF, BMP, WEBP), audio (MP3, WAV).

## Installation

```bash
pip install docling
# or with uv
uv pip install docling
```

Docling requires Python 3.9–3.13. First run downloads AI models (~1.5 GB) automatically.

## Basic Usage — Convert a Document

```python
from docling.document_converter import DocumentConverter

converter = DocumentConverter()

# From local file
result = converter.convert("/path/to/document.pdf")
doc = result.document

# From URL
result = converter.convert("https://example.com/report.pdf")
doc = result.document

# Export as markdown
markdown_text = doc.export_to_markdown()

# Export as dict (JSON-serializable)
doc_dict = doc.export_to_dict()
```

## CLI Usage

```bash
# Convert a PDF to markdown
docling /path/to/document.pdf --output ./output_dir

# Convert with specific format
docling /path/to/document.pdf --to json --output ./output_dir

# Convert multiple files
docling ./input_dir --output ./output_dir
```

## Chunking for Search Ingestion

Docling provides two chunking strategies for breaking documents into search-ready pieces:

### HierarchicalChunker (structure-based)

Splits at every section/heading boundary. Produces many small chunks that respect document structure.

```python
from docling.chunking import HierarchicalChunker

chunker = HierarchicalChunker()
chunks = list(chunker.chunk(doc))
# Each chunk has: chunk.text, chunk.meta (headings, page numbers)
```

### HybridChunker (recommended for OpenSearch)

Combines structure-aware splitting with token limits. Preserves document hierarchy while ensuring chunks fit within embedding model constraints.

```python
from docling.chunking import HybridChunker

chunker = HybridChunker(max_tokens=512, overlap_tokens=50)
chunks = list(chunker.chunk(doc))
```

## Preparing Chunks for OpenSearch Bulk Indexing

Convert Docling chunks into JSON documents suitable for `opensearch_ops.py index-bulk` or direct OpenSearch indexing:

```python
import json
from pathlib import Path
from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker

converter = DocumentConverter()
result = converter.convert("/path/to/document.pdf")
doc = result.document

chunker = HybridChunker(max_tokens=512, overlap_tokens=50)
chunks = list(chunker.chunk(doc))

# Write as JSONL for bulk indexing
output_path = Path("chunks.jsonl")
with output_path.open("w") as f:
    for i, chunk in enumerate(chunks):
        record = {
            "text": chunk.text,
            "chunk_id": i,
            "source": "/path/to/document.pdf",
        }
        # Include heading metadata if available
        if hasattr(chunk, "meta") and chunk.meta:
            headings = chunk.meta.headings if hasattr(chunk.meta, "headings") else []
            if headings:
                record["section"] = " > ".join(headings)
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

print(f"Wrote {len(chunks)} chunks to {output_path}")
```

Then index into OpenSearch:

```bash
uv run python scripts/opensearch_ops.py index-bulk \
  --index my-docs-index \
  --source-file chunks.jsonl \
  --count 500
```

## Processing Pipeline for Document Search

The recommended end-to-end flow:

1. **Convert** — Use Docling to parse the document into structured form.
2. **Chunk** — Use `HybridChunker` with token limits matching your embedding model.
3. **Export** — Write chunks as JSONL with text + metadata fields.
4. **Index** — Use `opensearch_ops.py index-bulk` to load into OpenSearch.
5. **Search** — Use the search UI or `opensearch_ops.py search` to query.

## Performance Tips

- Use `PdfPipelineOptions(generate_page_images=False)` to skip page images and save memory.
- Use `max_num_pages` or `page_range` to limit processing for large documents.
- Use `enable_parallel_processing=True` for multi-core processing.
- For scanned PDFs, OCR is enabled by default. Use `do_ocr=False` to skip if not needed.

## Choosing Chunk Size

- For BM25 (keyword search): larger chunks (1000+ tokens) work well since BM25 benefits from more context.
- For dense vector / semantic search: 256–512 tokens is typical, matching embedding model input limits.
- For hybrid search: 512 tokens with 50-token overlap is a good default.
- For agentic search: larger chunks (512–1024 tokens) give the agent more context per retrieval.
