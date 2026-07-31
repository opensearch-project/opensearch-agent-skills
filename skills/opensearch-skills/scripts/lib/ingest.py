"""Local document processing: parse PDFs with Docling, chunk with HybridChunker.

Produces chunk JSONL under a named index directory (``.opensearch/chunks/<index>/``).
Does NOT index to OpenSearch — indexing is a separate step (local bulk-index or
cloud ingestion via OSIS).
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Page estimation
# ---------------------------------------------------------------------------

def estimate_pages(source_path: str) -> int:
    """Estimate page count for a file. Returns 0 if file doesn't exist."""
    path = Path(source_path)
    if not path.exists():
        return 0

    ext = path.suffix.lower()

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return len(reader.pages)
        except Exception:
            # Fallback: rough estimate from file size (~50KB per page)
            size_kb = path.stat().st_size / 1024
            return max(1, int(size_kb / 50))
    elif ext in (".docx", ".pptx"):
        # Rough estimate: 2KB per page for docx, 20KB per page for pptx
        size_kb = path.stat().st_size / 1024
        per_page = 2 if ext == ".docx" else 20
        return max(1, int(size_kb / per_page))
    else:
        return 1  # Treat as single-page for unsupported formats


# ---------------------------------------------------------------------------
# Processing profiles (strategy framework)
# ---------------------------------------------------------------------------

# Local default chunk size. Kept small (512) to keep local processing light and to
# match the existing local chunk sets, giving finer-grained retrieval during local
# validation. This is purely a local chunking default and is independent of any
# cloud-side index-time limits.
DEFAULT_MAX_TOKENS = 512

# Profile registry. Each profile describes how to build the Docling converter and
# chunker. Stage A ships `semantic` and `tables`; `scanned` and `multimodal` are
# added in Stage B.
PROFILES = {
    "semantic": {
        "description": "Hierarchy-aware semantic chunking (headings/sections), OCR off. Best for digital-text, prose-heavy docs.",
        "do_ocr": False,
        "do_table_structure": False,
        "table_mode": None,
        "max_tokens": DEFAULT_MAX_TOKENS,
    },
    "tables": {
        "description": "Semantic chunking + TableFormer ACCURATE table extraction (tables serialized to markdown). Best for table-heavy docs.",
        "do_ocr": False,
        "do_table_structure": True,
        "table_mode": "ACCURATE",
        "max_tokens": DEFAULT_MAX_TOKENS,
    },
    "scanned": {
        "description": "OCR (RapidOCR, PP-OCRv4) for scanned/image PDFs, then table extraction + semantic chunking. Best for documents with little or no extractable text.",
        "do_ocr": True,
        "do_table_structure": True,
        "table_mode": "ACCURATE",
        "max_tokens": DEFAULT_MAX_TOKENS,
    },
    "multimodal": {
        "description": "Generates approximate text descriptions of images via a light local VLM (SmolVLM-256M), then semantic chunking. For local SAMPLING/preview of figure-rich docs; descriptions are approximate (not for precise technical figures). Higher-fidelity image understanding is a cloud concern.",
        "do_ocr": False,
        "do_table_structure": False,
        "table_mode": None,
        "describe_pictures": True,
        "max_tokens": DEFAULT_MAX_TOKENS,
    },
}

DEFAULT_PROFILE = "semantic"


def get_profile(profile_name: str | None) -> dict:
    """Return the profile config for ``profile_name`` (defaults to ``semantic``)."""
    name = profile_name or DEFAULT_PROFILE
    if name not in PROFILES:
        raise ValueError(
            f"Unknown processing profile: {name!r}. Available: {sorted(PROFILES)}"
        )
    return {"name": name, **PROFILES[name]}


# Heuristic thresholds for auto-detection (deliberately conservative).
_SCANNED_TEXT_THRESHOLD = 50    # mean extractable chars/page below this => likely scanned
_MULTIMODAL_MIN_IMAGES = 3      # total sampled images at/above this => image-rich
_DETECT_SAMPLE_PAGES = 5        # number of pages to sample for the heuristic


def _page_image_count(page) -> int:
    """Count page images, including resources pypdf cannot decode as images."""
    try:
        decoded_count = len(list(page.images))
        if decoded_count:
            return decoded_count
    except Exception:
        pass

    try:
        resources = page.get("/Resources") or {}
        if hasattr(resources, "get_object"):
            resources = resources.get_object()
        xobjects = resources.get("/XObject") or {}
        if hasattr(xobjects, "get_object"):
            xobjects = xobjects.get_object()
        return sum(
            1
            for value in xobjects.values()
            if value.get_object().get("/Subtype") == "/Image"
        )
    except Exception:
        return 0


def detect_document_profile(source_path: str) -> dict:
    """Recommend a processing profile for a PDF using cheap pypdf heuristics.

    Returns a dict: {"profile": <name>, "confidence": "low|medium|high",
    "reason": <str>, "signals": {...}}.

    Heuristics (no Docling, no rendering):
    - Low mean extractable text per page  -> ``scanned`` (image-only/scanned pages)
    - Adequate text but several images    -> ``multimodal``
    - Otherwise                           -> ``semantic`` (default)

    Note: table-heavy detection is not reliable from pypdf alone, so ``tables`` is
    never auto-selected — users choose it explicitly. Non-PDF inputs default to
    ``semantic``.
    """
    path = Path(source_path)
    signals = {"sampled_pages": 0, "mean_text_chars": 0, "image_count": 0}

    if path.suffix.lower() != ".pdf":
        return {
            "profile": "semantic",
            "confidence": "low",
            "reason": f"Non-PDF input ({path.suffix or 'no extension'}); defaulting to semantic.",
            "signals": signals,
        }

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = reader.pages[:_DETECT_SAMPLE_PAGES]
        n = len(pages)
        total_text = 0
        total_images = 0
        for pg in pages:
            try:
                total_text += len((pg.extract_text() or "").strip())
            except Exception:
                pass
            total_images += _page_image_count(pg)
        mean_text = int(total_text / n) if n else 0
        signals = {"sampled_pages": n, "mean_text_chars": mean_text, "image_count": total_images}
    except Exception as e:
        return {
            "profile": "semantic",
            "confidence": "low",
            "reason": f"Could not analyze PDF ({e}); defaulting to semantic.",
            "signals": signals,
        }

    if mean_text < _SCANNED_TEXT_THRESHOLD:
        return {
            "profile": "scanned",
            "confidence": "high" if mean_text < 10 else "medium",
            "reason": f"Low extractable text (~{mean_text} chars/page across {signals['sampled_pages']} pages) suggests a scanned/image PDF needing OCR.",
            "signals": signals,
        }
    if total_images >= _MULTIMODAL_MIN_IMAGES:
        return {
            "profile": "multimodal",
            "confidence": "medium",
            "reason": f"Has extractable text but {total_images} images in sampled pages; multimodal can describe visual content.",
            "signals": signals,
        }
    return {
        "profile": "semantic",
        "confidence": "medium",
        "reason": f"Text-rich (~{mean_text} chars/page) with few images; semantic chunking is appropriate.",
        "signals": signals,
    }


def _build_converter(profile: dict):
    """Build a Docling DocumentConverter configured for the given profile.

    Falls back to a default converter if the pipeline-options API is unavailable
    in the installed Docling version.
    """
    from docling.document_converter import DocumentConverter

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        from docling.document_converter import PdfFormatOption

        opts = PdfPipelineOptions()
        opts.do_ocr = bool(profile.get("do_ocr"))
        opts.do_table_structure = bool(profile.get("do_table_structure"))
        if profile.get("do_table_structure") and profile.get("table_mode"):
            opts.table_structure_options.mode = getattr(
                TableFormerMode, profile["table_mode"], TableFormerMode.ACCURATE
            )
        if opts.do_ocr:
            opts.ocr_options = _rapidocr_options()
        if profile.get("describe_pictures"):
            from docling.datamodel.pipeline_options import smolvlm_picture_description
            opts.do_picture_description = True
            opts.picture_description_options = smolvlm_picture_description
            opts.generate_picture_images = True
            opts.images_scale = 2
            # Describe smaller figures too (default ~5% of page area skips many figures).
            try:
                opts.picture_description_options.bitmap_area_threshold = 0.01
            except Exception:
                pass
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
    except Exception:
        return DocumentConverter()


def _rapidocr_options():
    """RapidOCR options pinned to PP-OCRv4 (English) on the onnxruntime engine.

    RapidOCR 3.9 defaults to PP-OCRv6, for which only PP-OCRv4 ONNX weights ship —
    causing an "Unsupported configuration" error. Pinning to PP-OCRv4 via
    ``rapidocr_params`` keeps the RapidOCR engine working. Requires the onnxruntime
    package (declared in the `ingestion` dependency group).
    """
    from docling.datamodel.pipeline_options import RapidOcrOptions
    from rapidocr.utils.parse_parameters import OCRVersion, ModelType, LangDet, LangRec

    params = {
        "Det.ocr_version": OCRVersion.PPOCRV4, "Det.model_type": ModelType.MOBILE, "Det.lang_type": LangDet.EN,
        "Rec.ocr_version": OCRVersion.PPOCRV4, "Rec.model_type": ModelType.MOBILE, "Rec.lang_type": LangRec.EN,
    }
    return RapidOcrOptions(lang=["english"], rapidocr_params=params)


def _table_markdown(doc) -> dict:
    """Map page_number -> list of markdown tables for that page (best-effort)."""
    page_tables: dict[int, list[str]] = {}
    try:
        from docling_core.types.doc import TableItem

        for item, _level in doc.iterate_items():
            if isinstance(item, TableItem):
                page_no = None
                if getattr(item, "prov", None):
                    page_no = item.prov[0].page_no
                try:
                    md = item.export_to_markdown(doc)
                except TypeError:
                    md = item.export_to_markdown()
                if md:
                    page_tables.setdefault(page_no or 1, []).append(md)
    except Exception:
        pass
    return page_tables


def _picture_descriptions(doc) -> dict:
    """Map page_number -> list of VLM image descriptions for that page (best-effort)."""
    page_desc: dict[int, list[str]] = {}
    try:
        from docling_core.types.doc import PictureItem

        for item, _level in doc.iterate_items():
            if isinstance(item, PictureItem):
                page_no = None
                if getattr(item, "prov", None):
                    page_no = item.prov[0].page_no
                for ann in (getattr(item, "annotations", None) or []):
                    text = getattr(ann, "text", None)
                    if text:
                        page_desc.setdefault(page_no or 1, []).append(text.strip())
    except Exception:
        pass
    return page_desc


# ---------------------------------------------------------------------------
# Memory estimation (pre-flight check)
# ---------------------------------------------------------------------------

# Conservative estimates (MB) for base model overhead + per-page processing cost.
# Base: one-time cost of loading the profile's models into RAM.
# Per-page: peak additional RAM per page during processing (layout, OCR, tables, etc.).
_MEMORY_ESTIMATES = {
    "semantic":   {"base_mb": 2500, "per_page_mb": 25},
    "tables":     {"base_mb": 3500, "per_page_mb": 50},
    "scanned":    {"base_mb": 4000, "per_page_mb": 60},
    "multimodal": {"base_mb": 3500, "per_page_mb": 40},
}

# Pages processed per batch. Keeps peak memory bounded regardless of total pages.
BATCH_SIZE = 10

# Headroom factor: require this much extra above the estimate to avoid swap pressure.
_MEMORY_HEADROOM = 1.2


def estimate_memory_required(profile: str, page_count: int) -> dict:
    """Estimate peak RAM needed (MB) for a given profile.

    Uses batch_size (not total page_count) since processing runs in batches.
    Returns {"base_mb", "per_page_mb", "total_mb"}.
    """
    est = _MEMORY_ESTIMATES.get(profile, _MEMORY_ESTIMATES["semantic"])
    batch = min(page_count, BATCH_SIZE)
    total = est["base_mb"] + est["per_page_mb"] * batch
    return {
        "base_mb": est["base_mb"],
        "per_page_mb": est["per_page_mb"],
        "total_mb": total,
    }


def check_memory_available(profile: str, page_count: int) -> dict:
    """Pre-flight memory check: can this machine handle the requested processing?

    Checks against batch-sized peak (base + BATCH_SIZE pages), not total pages.
    Returns {"available_mb", "required_mb", "sufficient"}.
    Falls back to sufficient=True if psutil is unavailable (non-blocking).
    """
    est = estimate_memory_required(profile, page_count)
    required_mb = int(est["total_mb"] * _MEMORY_HEADROOM)

    try:
        import psutil
        available_mb = int(psutil.virtual_memory().available / (1024 * 1024))
    except Exception:
        # If psutil is not installed or fails, skip the check — don't block.
        return {
            "available_mb": None,
            "required_mb": required_mb,
            "sufficient": True,
            "skipped": True,
        }

    return {
        "available_mb": available_mb,
        "required_mb": required_mb,
        "sufficient": available_mb >= required_mb,
    }


def _build_memory_recommendations(profile: str) -> list[dict]:
    """Build graduated recommendations when memory is insufficient."""
    recs = []

    # 1. Suggest lighter profile if current one is heavy.
    if profile in ("tables", "scanned", "multimodal"):
        recs.append({
            "action": "lighter_profile",
            "description": "Switch to --profile semantic (lowest memory, ~2.5 GB base)",
            "profile": "semantic",
        })

    # 2. Always offer cloud path.
    recs.append({
        "action": "cloud_ingestion",
        "description": (
            "Use cloud ingestion (OSIS) to process at scale without local memory constraints. "
            "Upload to S3 and let the managed pipeline handle processing."
        ),
    })

    return recs


# ---------------------------------------------------------------------------
# Docling processing
# ---------------------------------------------------------------------------

def process_document(
    source_path: str,
    max_pages: int = 10,
    max_tokens: int | None = None,
    profile: str | None = None,
) -> list[dict]:
    """Parse and chunk a document using Docling, driven by a processing profile.

    Returns a list of chunk dicts ready for indexing:
        {"text": "...", "headings": [...], "source_file": "...", "chunk_id": N, "page_number": N}

    ``profile`` selects the strategy (see ``PROFILES``). ``max_tokens`` overrides the
    profile's default chunk size when provided. Processing runs in batches of
    ``BATCH_SIZE`` pages to keep peak memory bounded regardless of total pages.
    """
    from docling_core.transforms.chunker.hybrid_chunker import HybridChunker

    # Resolve profile via detection heuristic if not specified.
    if not profile:
        detection = detect_document_profile(source_path)
        profile = detection["profile"] if detection["profile"] in PROFILES else "semantic"

    prof = get_profile(profile)
    effective_max_tokens = max_tokens if max_tokens else prof["max_tokens"]

    path = Path(source_path)

    # Build converter and chunker once (models stay loaded across batches).
    converter = _build_converter(prof)
    chunker = HybridChunker(max_tokens=effective_max_tokens)

    # Process in batches of BATCH_SIZE pages to keep peak memory bounded.
    records = []
    for batch_start in range(1, max_pages + 1, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE - 1, max_pages)
        result = converter.convert(str(path), page_range=(batch_start, batch_end))
        doc = result.document

        # For table profiles, collect per-page markdown tables
        page_tables = _table_markdown(doc) if prof.get("do_table_structure") else {}
        # For multimodal, collect per-page image descriptions
        page_pics = _picture_descriptions(doc) if prof.get("describe_pictures") else {}

        # Chunk this batch
        chunks = list(chunker.chunk(doc))

        # Convert to indexable format (chunk_id continues from previous batches)
        chunk_id_offset = len(records)
        batch_records = []
        for i, chunk in enumerate(chunks):
            record = {
                "text": chunk.text,
                "headings": chunk.meta.headings if chunk.meta and chunk.meta.headings else [],
                "source_file": path.name,
                "chunk_id": chunk_id_offset + i,
            }
            # Add page number and bounding box from provenance
            if chunk.meta and hasattr(chunk.meta, "doc_items") and chunk.meta.doc_items:
                try:
                    bboxes = []
                    for item in chunk.meta.doc_items:
                        if hasattr(item, "prov") and item.prov:
                            for prov in item.prov:
                                if not record.get("page_number"):
                                    record["page_number"] = prov.page_no
                                if hasattr(prov, "bbox") and prov.bbox:
                                    bboxes.append({
                                        "l": prov.bbox.l,
                                        "t": prov.bbox.t,
                                        "r": prov.bbox.r,
                                        "b": prov.bbox.b,
                                        "page": prov.page_no,
                                        "coord_origin": str(prov.bbox.coord_origin.value) if hasattr(prov.bbox, "coord_origin") else "BOTTOMLEFT",
                                    })
                    if bboxes:
                        record["bboxes"] = bboxes
                except (IndexError, AttributeError):
                    pass
            batch_records.append(record)

        # For table profiles, attach page-level markdown tables to the first chunk on
        # each page so structured table content is searchable in the chunk text.
        if page_tables:
            seen_pages: set[int] = set()
            for record in batch_records:
                pg = record.get("page_number", 1)
                if pg in page_tables and pg not in seen_pages:
                    tables_md = "\n\n".join(page_tables[pg])
                    record["text"] = f"{record['text']}\n\n{tables_md}".strip()
                    record["has_tables"] = True
                    seen_pages.add(pg)

        # For multimodal, attach page-level image descriptions to the first chunk on
        # each page so visual content is searchable in the chunk text.
        if page_pics:
            seen_pic_pages: set[int] = set()
            for record in batch_records:
                pg = record.get("page_number", 1)
                if pg in page_pics and pg not in seen_pic_pages:
                    desc = "\n".join(f"[Image] {d}" for d in page_pics[pg])
                    record["text"] = f"{record['text']}\n\n{desc}".strip()
                    record["has_image_descriptions"] = True
                    seen_pic_pages.add(pg)

        records.extend(batch_records)

    # Safety net: filter chunks beyond max_pages in case page_range was not
    # honoured (e.g., older Docling versions or page-numbering quirks).
    # The primary truncation happens at conversion time via page_range above.
    if max_pages and len(records) > 0:
        truncated = [r for r in records if r.get("page_number", 1) <= max_pages]
        if len(truncated) < len(records):
            records = truncated

    return records


# ---------------------------------------------------------------------------
# Status file management
# ---------------------------------------------------------------------------

STATUS_DIR = ".opensearch"
STATUS_FILE = "ingestion-status.json"
PID_FILE = os.path.join(STATUS_DIR, "ingestion.pid")
LOG_FILE = os.path.join(STATUS_DIR, "ingestion.log")


def _status_path() -> Path:
    """Get the status file path, creating directory if needed."""
    status_dir = Path(STATUS_DIR)
    status_dir.mkdir(exist_ok=True)
    return status_dir / STATUS_FILE


def write_status(data: dict):
    """Write ingestion status for UI polling. Uses atomic write (temp + replace)."""
    path = _status_path()
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    tmp_path.replace(path)


def read_status() -> dict:
    """Read current ingestion status."""
    path = _status_path()
    if path.exists():
        return json.loads(path.read_text())
    return {"active": False}


# ---------------------------------------------------------------------------
# Background ingestion
# ---------------------------------------------------------------------------


def _pid_is_alive(pid: int) -> bool:
    """Return whether a process exists without signaling or mutating it."""
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
            return True
        # Access denied still proves that the process exists.
        return ctypes.get_last_error() == 5

    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def is_ingestion_running() -> bool:
    """Check if a background ingestion process is alive by reading PID file.

    Returns True only if the PID file exists and the process is still running.
    Cleans up stale PID files for dead processes.
    """
    pid_path = Path(PID_FILE)
    if not pid_path.exists():
        return False

    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False

    # Check if process is alive (signal 0 doesn't kill, just checks existence).
    try:
        if not _pid_is_alive(pid):
            raise ProcessLookupError(pid)
        return True
    except (ProcessLookupError, OSError):
        # Process is dead — clean up stale PID file.
        try:
            pid_path.unlink()
        except OSError:
            pass
        return False


def ingest_background(
    source: str,
    index: str,
    max_pages: int = 10,
    max_tokens: int | None = None,
    profile: str | None = None,
) -> dict:
    """Spawn ``opensearch_ops.py ingest`` as a detached background subprocess.

    Writes the child PID to ``.opensearch/ingestion.pid`` and redirects
    stdout/stderr to ``.opensearch/ingestion.log``. The caller should poll
    with ``ingest-status`` or ``is_ingestion_running()`` to check progress.

    Returns a summary dict immediately (does not wait for processing).
    """
    if is_ingestion_running():
        return {
            "error": "ingestion_already_running",
            "detail": "A background ingestion process is already active. Use ingest-status to check progress.",
        }

    # Build the command — run the same CLI in foreground mode (no --background)
    # so the subprocess does the actual work and writes status files.
    scripts_dir = Path(__file__).resolve().parent.parent
    cmd = [
        sys.executable, str(scripts_dir / "opensearch_ops.py"),
        "ingest",
        "--source", source,
        "--index", index,
        "--max-pages", str(max_pages),
        "--confirm",  # Already confirmed by the parent invocation
    ]
    if max_tokens is not None:
        cmd.extend(["--max-tokens", str(max_tokens)])
    if profile:
        cmd.extend(["--profile", profile])

    # Ensure status directory exists.
    Path(STATUS_DIR).mkdir(exist_ok=True)

    # Open log file for subprocess output.
    log_path = Path(LOG_FILE)
    log_fh = open(log_path, "w")

    # Spawn detached subprocess.
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    # Close file handle in parent — child owns it now.
    log_fh.close()

    # Write PID file.
    Path(PID_FILE).write_text(str(proc.pid))

    return {
        "status": "background_started",
        "pid": proc.pid,
        "log_file": str(log_path),
        "index": index,
        "detail": "Ingestion running in background. Use ingest-status to check progress.",
    }


# ---------------------------------------------------------------------------
# Chunks output
# ---------------------------------------------------------------------------

# Document processing always produces chunks under a named index directory so
# consumers (UI, cloud ingestion) have a stable key to look up. When the caller
# does not supply an index name, one is derived from the document filename.
# Processing never talks to OpenSearch — the named index is only a label / output
# location here; the actual OpenSearch index is created later (bulk-index or OSIS).


def derive_index_name(source_file: str) -> str:
    """Derive a safe OpenSearch-style index name from a document filename.

    Lowercases the file stem, replaces non-alphanumeric runs with single hyphens,
    and trims leading/trailing hyphens. Falls back to ``document`` if empty.
    """
    import re

    stem = Path(source_file).stem.lower()
    name = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return name or "document"


def resolve_index_name(index_name: str | None, source_file: str) -> str:
    """Return the explicit index name, or derive one from the document filename."""
    return index_name if index_name else derive_index_name(source_file)


def chunks_dir_for(index_name: str) -> Path:
    """Return the chunks output directory for an index: ``.opensearch/chunks/<index>/``."""
    return Path(STATUS_DIR) / "chunks" / index_name


# --- Index -> chunk-source provenance -------------------------------------
# A single chunk set (e.g. ".opensearch/chunks/docs/") can be indexed into
# multiple cluster indices under different names (docs-v1, docs-v2, ...). This
# records which chunk set each cluster index was built from, so the ingestion
# (Chunk Inspector) view can be offered for an index whose name differs from
# the chunk set. Stored in a sidecar so it also works for remote/cloud
# endpoints where cluster metadata is not reliable.

PROVENANCE_FILE = Path(STATUS_DIR) / "index_provenance.json"


def chunk_source_from_path(source_file: str) -> str:
    """If ``source_file`` lives under ``.opensearch/chunks/<name>/``, return
    ``<name>``; else "". This is the chunk set a bulk-index was built from."""
    try:
        p = Path(source_file).resolve()
        chunks_root = (Path(STATUS_DIR) / "chunks").resolve()
        if chunks_root in p.parents:
            rel = p.relative_to(chunks_root)
            return rel.parts[0] if rel.parts else ""
    except Exception:
        pass
    return ""


def record_index_provenance(index_name: str, chunk_source: str) -> None:
    """Record that cluster index ``index_name`` was built from chunk set
    ``chunk_source``. No-op if either is empty."""
    if not index_name or not chunk_source:
        return
    try:
        data = read_index_provenance()
        data[index_name] = chunk_source
        PROVENANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROVENANCE_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def read_index_provenance() -> dict:
    """Return the {cluster_index: chunk_source} provenance map (may be empty)."""
    try:
        if PROVENANCE_FILE.exists():
            return json.loads(PROVENANCE_FILE.read_text()) or {}
    except Exception:
        pass
    return {}


def resolve_chunk_source(index_name: str) -> str:
    """Return the chunk set to inspect for ``index_name``: the same name if
    chunks exist under it, else the recorded provenance parent, else ""."""
    if not index_name:
        return ""
    same = chunks_dir_for(index_name)
    if same.is_dir() and any(same.glob("*.jsonl")):
        return index_name
    parent = read_index_provenance().get(index_name, "")
    if parent:
        pdir = chunks_dir_for(parent)
        if pdir.is_dir() and any(pdir.glob("*.jsonl")):
            return parent
    return ""


def write_chunks(chunks: list[dict], index_name: str, source_file: str) -> Path:
    """Write chunks to ``.opensearch/chunks/<index>/<filename>.jsonl``."""
    chunks_dir = chunks_dir_for(index_name)
    chunks_dir.mkdir(parents=True, exist_ok=True)

    output_path = chunks_dir / f"{Path(source_file).stem}.jsonl"
    with open(output_path, "w") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")

    return output_path


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest_local(
    source_path: str,
    index_name: str | None = None,
    max_pages: int = 10,
    max_tokens: int | None = None,
    profile: str | None = None,
) -> dict:
    """Local document processing: parse → chunk → write jsonl. Does NOT index to OpenSearch.

    Always produces chunks under a named index directory (``.opensearch/chunks/<index>/``)
    so consumers have a stable key to look up. If ``index_name`` is
    not supplied, one is derived from the document filename. ``profile`` selects the
    processing strategy (see ``PROFILES``). Processing never contacts OpenSearch — the
    actual index is created later (bulk-index or cloud ingestion via OSIS).

    Returns summary dict with results.
    """
    path = Path(source_path)
    if not path.exists():
        return {"error": f"File not found: {source_path}"}

    # Document processing always has a named index (derived if not provided).
    index_name = resolve_index_name(index_name, source_path)

    # Resolve profile via detection heuristic if not specified.
    if not profile:
        detection = detect_document_profile(source_path)
        profile = detection["profile"] if detection["profile"] in PROFILES else "semantic"

    prof = get_profile(profile)

    total_pages = estimate_pages(source_path)
    truncated = total_pages > max_pages
    pages_to_process = min(total_pages, max_pages)

    # Pre-flight memory check
    mem_check = check_memory_available(prof["name"], pages_to_process)
    if not mem_check.get("sufficient", True):
        recommendations = _build_memory_recommendations(
            prof["name"]
        )
        return {
            "error": "insufficient_memory",
            "detail": (
                f"Profile '{prof['name']}' processing {pages_to_process} pages "
                f"needs ~{mem_check['required_mb']} MB; "
                f"only {mem_check['available_mb']} MB available."
            ),
            "memory": mem_check,
            "recommendations": recommendations,
        }

    # Write initial status
    write_status({
        "active": True,
        "stage": "processing",
        "mode": "local",
        "profile": prof["name"],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "index": index_name,
        "files": [{
            "name": path.name,
            "pages": pages_to_process,
            "status": "processing",
            "chunks": 0,
        }],
        "totals": {"files": 1, "pages": pages_to_process, "chunks_produced": 0, "errors": 0},
    })

    # Process document
    try:
        chunks = process_document(
            source_path, max_pages=max_pages, max_tokens=max_tokens, profile=prof["name"]
        )
    except MemoryError:
        recommendations = _build_memory_recommendations(
            prof["name"]
        )
        write_status({
            "active": False,
            "stage": "error",
            "files": [{"name": path.name, "pages": pages_to_process, "status": "error", "error": "Out of memory"}],
            "totals": {"files": 1, "errors": 1},
        })
        return {
            "error": "out_of_memory",
            "detail": f"Ran out of memory processing '{path.name}' with profile '{prof['name']}'.",
            "memory": mem_check,
            "recommendations": recommendations,
        }
    except Exception as e:
        write_status({
            "active": False,
            "stage": "error",
            "files": [{"name": path.name, "pages": total_pages, "status": "error", "error": str(e)}],
            "totals": {"files": 1, "errors": 1},
        })
        return {"error": f"Processing failed: {e}"}

    # Write chunks.jsonl under the named index directory
    chunks_path = write_chunks(chunks, index_name, source_path)

    # Write metadata alongside the chunks (so the UI can find the source doc)
    meta_dir = chunks_dir_for(index_name)
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "_metadata.json").write_text(json.dumps({
        "source_path": str(path.resolve()),
        "pages_processed": pages_to_process,
        "total_pages": total_pages,
        "max_tokens": max_tokens if max_tokens else prof["max_tokens"],
        "profile": prof["name"],
    }))

    # Final status: chunks ready (not indexed yet)
    write_status({
        "active": False,
        "stage": "chunks_ready",
        "mode": "local",
        "profile": prof["name"],
        "index": index_name,
        "source_path": str(path.resolve()),
        "files": [{
            "name": path.name,
            "pages": pages_to_process,
            "status": "chunks_ready",
            "chunks": len(chunks),
        }],
        "totals": {"files": 1, "pages": pages_to_process, "chunks_produced": len(chunks), "errors": 0},
        "chunks_file": str(chunks_path),
    })

    # Next-step hint. Document processing is self-contained: chunks always stay at
    # `chunks_path` under the named index. Indexing into OpenSearch is a separate
    # step (bulk-index locally, or upload to S3 for cloud ingestion via OSIS).
    next_step = (
        "Document processing complete. Chunks are ready under index "
        f"'{index_name}'. To index into OpenSearch: "
        f"index-bulk --source-file {chunks_path} --index {index_name}"
    )

    return {
        "status": "chunks_ready",
        "source": source_path,
        "profile": prof["name"],
        "pages_processed": pages_to_process,
        "total_pages": total_pages,
        "truncated": truncated,
        "chunks_produced": len(chunks),
        "chunks_file": str(chunks_path),
        "index": index_name,
        "next_step": next_step,
        "visualize": f"launch-ui --mode ingestion --index {index_name}",
    }

