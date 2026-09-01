"""Tests for skills/opensearch-skills/scripts/lib/ingest.py

These tests must not require a running OpenSearch cluster or the optional
``docling`` dependency. Document processing (``process_document``) is mocked so
the index-naming and file-output behavior can be tested in isolation.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib import ingest
from lib.ingest import (
    DEFAULT_MAX_TOKENS,
    PROFILES,
    STATUS_DIR,
    chunks_dir_for,
    derive_index_name,
    detect_document_profile,
    estimate_pages,
    get_profile,
    ingest_local,
    read_status,
    resolve_index_name,
    write_chunks,
    write_status,
)


SAMPLE_CHUNKS = [
    {"text": "hello world", "headings": [], "source_file": "doc.pdf", "chunk_id": 0, "page_number": 1},
    {"text": "second chunk", "headings": ["Intro"], "source_file": "doc.pdf", "chunk_id": 1, "page_number": 2},
]


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """Run each test in an isolated cwd so .opensearch artifacts don't leak."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# estimate_pages
# ---------------------------------------------------------------------------

def test_estimate_pages_missing_file_returns_zero(workdir):
    assert estimate_pages(str(workdir / "nope.pdf")) == 0


def test_estimate_pages_unknown_extension_returns_one(workdir):
    f = workdir / "notes.txt"
    f.write_text("some text")
    assert estimate_pages(str(f)) == 1


def test_estimate_pages_docx_uses_size_estimate(workdir):
    f = workdir / "doc.docx"
    f.write_bytes(b"x" * (10 * 1024))  # ~10 KB -> ~5 pages at 2KB/page
    assert estimate_pages(str(f)) == 5


def test_estimate_pages_pdf_fallback_on_bad_file(workdir):
    # Not a real PDF: pypdf fails, falls back to ~50KB/page estimate.
    f = workdir / "fake.pdf"
    f.write_bytes(b"x" * (100 * 1024))  # ~100 KB -> ~2 pages
    pages = estimate_pages(str(f))
    assert pages >= 1


# ---------------------------------------------------------------------------
# index name resolution / chunks_dir_for / write_chunks
# ---------------------------------------------------------------------------

def test_derive_index_name_sanitizes_filename():
    assert derive_index_name("/tmp/Attention Is All You Need.pdf") == "attention-is-all-you-need"
    assert derive_index_name("report_2024.Q1.pdf") == "report-2024-q1"


def test_derive_index_name_empty_fallback():
    assert derive_index_name("___.pdf") == "document"


def test_resolve_index_name_prefers_explicit():
    assert resolve_index_name("my-index", "/tmp/doc.pdf") == "my-index"


def test_resolve_index_name_derives_when_absent():
    assert resolve_index_name(None, "/tmp/Doc Name.pdf") == "doc-name"


def test_chunks_dir_for_index(workdir):
    assert chunks_dir_for("my-index") == Path(STATUS_DIR) / "chunks" / "my-index"


def test_write_chunks_with_index(workdir):
    out = write_chunks(SAMPLE_CHUNKS, "my-index", "/tmp/doc.pdf")
    assert out == Path(STATUS_DIR) / "chunks" / "my-index" / "doc.jsonl"
    lines = out.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["text"] == "hello world"


# ---------------------------------------------------------------------------
# processing profiles
# ---------------------------------------------------------------------------

def test_get_profile_default_is_semantic():
    prof = get_profile(None)
    assert prof["name"] == "semantic"
    assert prof["do_ocr"] is False
    assert prof["do_table_structure"] is False


def test_get_profile_default_max_tokens_is_512():
    # Local default stays light at 512 (not the ASE 8192 cloud ceiling).
    assert DEFAULT_MAX_TOKENS == 512
    assert get_profile("semantic")["max_tokens"] == 512
    assert get_profile("tables")["max_tokens"] == 512


def test_get_profile_tables_enables_table_structure():
    prof = get_profile("tables")
    assert prof["do_table_structure"] is True
    assert prof["table_mode"] == "ACCURATE"


def test_get_profile_unknown_raises():
    with pytest.raises(ValueError):
        get_profile("nonsense")


def test_profiles_registry_has_stage_a_profiles():
    assert "semantic" in PROFILES
    assert "tables" in PROFILES


def test_scanned_profile_enables_ocr():
    prof = get_profile("scanned")
    assert prof["do_ocr"] is True
    assert prof["do_table_structure"] is True


def test_multimodal_profile_describes_pictures():
    prof = get_profile("multimodal")
    assert prof["describe_pictures"] is True
    assert prof["do_ocr"] is False


def test_ingest_local_records_profile_in_result(workdir):
    pdf = _make_pdf(workdir)
    with (
        patch.object(
            ingest,
            "check_memory_available",
            return_value={"sufficient": True},
        ),
        patch.object(
            ingest,
            "process_document",
            return_value=SAMPLE_CHUNKS,
        ) as mock_pd,
    ):
        result = ingest_local(str(pdf), profile="tables")
    assert result["profile"] == "tables"
    # process_document must be invoked with the selected profile
    assert mock_pd.call_args.kwargs.get("profile") == "tables"
    # status file records the profile too
    assert read_status()["profile"] == "tables"


# ---------------------------------------------------------------------------
# detect_document_profile  (auto-detection heuristic)
# ---------------------------------------------------------------------------

class _FakePage:
    def __init__(self, text="", n_images=0):
        self._text = text
        self.images = [object()] * n_images

    def extract_text(self):
        return self._text


class _FakeReader:
    def __init__(self, pages):
        self.pages = pages


def _patch_reader(pages):
    """Patch pypdf.PdfReader to return a fake reader with the given pages."""
    import pypdf
    return patch.object(pypdf, "PdfReader", lambda *a, **k: _FakeReader(pages))


def test_detect_non_pdf_defaults_semantic(workdir):
    f = workdir / "notes.txt"
    f.write_text("hello")
    result = detect_document_profile(str(f))
    assert result["profile"] == "semantic"
    assert result["confidence"] == "low"


def test_detect_scanned_when_low_text(workdir):
    f = workdir / "scanned.pdf"
    f.write_bytes(b"%PDF-1.4")
    with _patch_reader([_FakePage(text="", n_images=1) for _ in range(3)]):
        result = detect_document_profile(str(f))
    assert result["profile"] == "scanned"


def test_detect_multimodal_when_text_and_images(workdir):
    f = workdir / "figs.pdf"
    f.write_bytes(b"%PDF-1.4")
    pages = [_FakePage(text="x" * 500, n_images=2) for _ in range(3)]  # 6 images total
    with _patch_reader(pages):
        result = detect_document_profile(str(f))
    assert result["profile"] == "multimodal"


def test_detect_semantic_when_text_few_images(workdir):
    f = workdir / "prose.pdf"
    f.write_bytes(b"%PDF-1.4")
    pages = [_FakePage(text="x" * 800, n_images=0) for _ in range(3)]
    with _patch_reader(pages):
        result = detect_document_profile(str(f))
    assert result["profile"] == "semantic"
    assert result["confidence"] == "medium"


def test_detect_handles_reader_error_gracefully(workdir):
    f = workdir / "broken.pdf"
    f.write_bytes(b"not a real pdf")
    import pypdf
    with patch.object(pypdf, "PdfReader", side_effect=RuntimeError("bad pdf")):
        result = detect_document_profile(str(f))
    assert result["profile"] == "semantic"
    assert result["confidence"] == "low"


# Real public-domain fixtures: validate auto-detect on actual PDFs (pypdf only,
# no Docling). Skips if fixtures are not present.
_FIXTURES_DIR = Path(__file__).resolve().parent / "evals" / "fixtures" / "pdfs"
_MANIFEST = _FIXTURES_DIR / "manifest.json"


@pytest.mark.skipif(not _MANIFEST.exists(), reason="PDF fixtures/manifest not present")
def test_detect_matches_manifest_expectations():
    manifest = json.loads(_MANIFEST.read_text())
    checked = 0
    for fx in manifest["fixtures"]:
        pdf = _FIXTURES_DIR / fx["file"]
        if not pdf.exists():
            continue
        result = detect_document_profile(str(pdf))
        assert result["profile"] == fx["expected_detection"], (
            f"{fx['file']}: detected {result['profile']!r}, "
            f"manifest expects {fx['expected_detection']!r} ({result['reason']})"
        )
        checked += 1
    assert checked > 0, "No fixture PDFs found to check"


# ---------------------------------------------------------------------------
# status file read/write
# ---------------------------------------------------------------------------

def test_read_status_default_when_missing(workdir):
    assert read_status() == {"active": False}


def test_write_then_read_status_roundtrip(workdir):
    write_status({"active": True, "stage": "processing"})
    status = read_status()
    assert status["active"] is True
    assert status["stage"] == "processing"


def test_write_status_replaces_existing_file_on_windows(workdir, monkeypatch):
    write_status({"active": True, "stage": "processing"})
    original_rename = Path.rename

    def windows_rename(source, target):
        if Path(target).exists():
            raise FileExistsError(target)
        return original_rename(source, target)

    monkeypatch.setattr(Path, "rename", windows_rename)

    write_status({"active": False, "stage": "complete"})

    assert read_status() == {"active": False, "stage": "complete"}


# ---------------------------------------------------------------------------
# ingest_local  (named index, auto-derived when absent)
# ---------------------------------------------------------------------------

def _make_pdf(workdir):
    f = workdir / "doc.pdf"
    f.write_bytes(b"x" * (60 * 1024))
    return f


def test_ingest_local_missing_source_returns_error(workdir):
    result = ingest_local(str(workdir / "missing.pdf"))
    assert "error" in result
    assert "File not found" in result["error"]


def test_ingest_local_without_index_derives_name(workdir):
    pdf = _make_pdf(workdir)
    with (
        patch.object(
            ingest,
            "check_memory_available",
            return_value={"sufficient": True},
        ),
        patch.object(ingest, "process_document", return_value=SAMPLE_CHUNKS),
    ):
        result = ingest_local(str(pdf))  # no index -> derived from filename "doc.pdf"

    assert result["status"] == "chunks_ready"
    assert result["index"] == "doc"
    assert result["chunks_produced"] == 2
    expected = Path(STATUS_DIR) / "chunks" / "doc" / "doc.jsonl"
    assert result["chunks_file"] == str(expected)
    assert expected.exists()
    # next_step references the resolved index, never implies moving files
    assert "doc" in result["next_step"]
    # visualize key tells the agent how to launch the chunk inspector
    assert result["visualize"] == "launch-ui --mode ingestion --index doc"
    # metadata written alongside chunks under the named index
    assert (Path(STATUS_DIR) / "chunks" / "doc" / "_metadata.json").exists()


def test_ingest_local_with_index_writes_to_index_dir(workdir):
    pdf = _make_pdf(workdir)
    with (
        patch.object(
            ingest,
            "check_memory_available",
            return_value={"sufficient": True},
        ),
        patch.object(ingest, "process_document", return_value=SAMPLE_CHUNKS),
    ):
        result = ingest_local(str(pdf), index_name="attention-paper")

    assert result["index"] == "attention-paper"
    expected = Path(STATUS_DIR) / "chunks" / "attention-paper" / "doc.jsonl"
    assert result["chunks_file"] == str(expected)
    assert expected.exists()
    assert "--index attention-paper" in result["next_step"]


def test_ingest_local_processing_error_is_reported(workdir):
    pdf = _make_pdf(workdir)
    with (
        patch.object(
            ingest,
            "check_memory_available",
            return_value={"sufficient": True},
        ),
        patch.object(
            ingest,
            "process_document",
            side_effect=RuntimeError("boom"),
        ),
    ):
        result = ingest_local(str(pdf))
    assert "error" in result
    assert "boom" in result["error"]
    # status file should reflect the error stage
    assert read_status()["stage"] == "error"


# ---------------------------------------------------------------------------
# page_range passed to converter (A1 fix)
# ---------------------------------------------------------------------------

def test_process_document_passes_page_range_to_converter(workdir):
    """Verify that process_document passes page_range=(1, max_pages) to Docling."""
    pdf = workdir / "big.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake content")

    mock_doc = type("Doc", (), {
        "iterate_items": lambda self: iter([]),
    })()
    mock_result = type("Result", (), {"document": mock_doc})()
    mock_converter_instance = type("Converter", (), {
        "convert": lambda self, path, **kwargs: mock_result,
    })()

    # Track what arguments convert() receives
    convert_calls = []
    original_convert = mock_converter_instance.convert

    def tracking_convert(path, **kwargs):
        convert_calls.append(kwargs)
        return original_convert(path, **kwargs)

    mock_converter_instance.convert = tracking_convert

    with patch("lib.ingest._build_converter", return_value=mock_converter_instance), \
         patch("docling_core.transforms.chunker.hybrid_chunker.HybridChunker") as mock_chunker_cls:
        mock_chunker_cls.return_value.chunk.return_value = []
        from lib.ingest import process_document
        process_document(str(pdf), max_pages=7, profile="semantic")

    assert len(convert_calls) == 1
    assert convert_calls[0].get("page_range") == (1, 7)


# ---------------------------------------------------------------------------
# memory estimation (B1)
# ---------------------------------------------------------------------------

def test_estimate_memory_required_semantic():
    from lib.ingest import estimate_memory_required
    est = estimate_memory_required("semantic", 10)
    assert est["base_mb"] == 2500
    assert est["per_page_mb"] == 25
    assert est["total_mb"] == 2500 + 25 * 10


def test_estimate_memory_required_tables():
    from lib.ingest import estimate_memory_required
    est = estimate_memory_required("tables", 5)
    assert est["total_mb"] == 3500 + 50 * 5


def test_estimate_memory_required_unknown_profile_falls_back():
    from lib.ingest import estimate_memory_required
    est = estimate_memory_required("unknown_profile", 10)
    # Falls back to semantic estimates
    assert est["base_mb"] == 2500


# ---------------------------------------------------------------------------
# memory availability check (B2)
# ---------------------------------------------------------------------------

def test_check_memory_available_sufficient(workdir):
    from lib.ingest import check_memory_available
    # Mock psutil to report 16 GB available
    mock_vmem = type("svmem", (), {"available": 16 * 1024 * 1024 * 1024})()
    with patch("psutil.virtual_memory", return_value=mock_vmem):
        result = check_memory_available("semantic", 10)
    assert result["sufficient"] is True
    assert result["available_mb"] > 10000


def test_check_memory_available_insufficient(workdir):
    from lib.ingest import check_memory_available
    # Mock psutil to report only 1 GB available
    mock_vmem = type("svmem", (), {"available": 1 * 1024 * 1024 * 1024})()
    with patch("psutil.virtual_memory", return_value=mock_vmem):
        result = check_memory_available("scanned", 10)
    assert result["sufficient"] is False
    assert result["required_mb"] > result["available_mb"]


def test_check_memory_available_skips_when_psutil_missing(workdir):
    from lib.ingest import check_memory_available
    with patch.dict("sys.modules", {"psutil": None}):
        # Force ImportError by patching the import
        with patch("builtins.__import__", side_effect=ImportError("no psutil")):
            result = check_memory_available("semantic", 10)
    # Should not block — reports sufficient with skipped flag
    assert result["sufficient"] is True
    assert result.get("skipped") is True


# ---------------------------------------------------------------------------
# ingest_local memory pre-flight (B3)
# ---------------------------------------------------------------------------

def test_ingest_local_returns_error_when_memory_insufficient(workdir):
    pdf = _make_pdf(workdir)
    mock_vmem = type("svmem", (), {"available": 500 * 1024 * 1024})()  # 500 MB
    with patch("psutil.virtual_memory", return_value=mock_vmem):
        result = ingest_local(str(pdf), profile="scanned")
    assert result.get("error") == "insufficient_memory"
    assert "recommendations" in result
    assert len(result["recommendations"]) >= 1
    # Should include cloud_ingestion as an option
    actions = [r["action"] for r in result["recommendations"]]
    assert "cloud_ingestion" in actions


def test_ingest_local_proceeds_when_memory_sufficient(workdir):
    pdf = _make_pdf(workdir)
    mock_vmem = type("svmem", (), {"available": 16 * 1024 * 1024 * 1024})()  # 16 GB
    with patch("psutil.virtual_memory", return_value=mock_vmem), \
         patch.object(ingest, "process_document", return_value=SAMPLE_CHUNKS):
        result = ingest_local(str(pdf), profile="semantic")
    assert result["status"] == "chunks_ready"


# ---------------------------------------------------------------------------
# ingest_local MemoryError catch (B5)
# ---------------------------------------------------------------------------

def test_ingest_local_catches_memory_error(workdir):
    pdf = _make_pdf(workdir)
    mock_vmem = type("svmem", (), {"available": 16 * 1024 * 1024 * 1024})()  # passes pre-flight
    with patch("psutil.virtual_memory", return_value=mock_vmem), \
         patch.object(ingest, "process_document", side_effect=MemoryError("OOM")):
        result = ingest_local(str(pdf), profile="semantic")
    assert result.get("error") == "out_of_memory"
    assert "recommendations" in result
    assert read_status()["stage"] == "error"


# ---------------------------------------------------------------------------
# Index -> chunk-source provenance (versioned indices reach their chunks)
# ---------------------------------------------------------------------------

def _make_chunks(name):
    d = chunks_dir_for(name)
    d.mkdir(parents=True, exist_ok=True)
    (d / "doc.jsonl").write_text('{"text": "hi"}\n')
    return d / "doc.jsonl"


def test_chunk_source_from_path_under_chunks(workdir):
    src = _make_chunks("docs")
    assert ingest.chunk_source_from_path(str(src)) == "docs"


def test_chunk_source_from_path_outside_chunks(workdir):
    other = workdir / "somewhere" / "data.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text("{}\n")
    assert ingest.chunk_source_from_path(str(other)) == ""


def test_record_and_read_provenance(workdir):
    ingest.record_index_provenance("docs-v1", "docs")
    ingest.record_index_provenance("docs-v2", "docs")
    prov = ingest.read_index_provenance()
    assert prov == {"docs-v1": "docs", "docs-v2": "docs"}


def test_record_provenance_ignores_empty(workdir):
    ingest.record_index_provenance("", "docs")
    ingest.record_index_provenance("docs-v1", "")
    assert ingest.read_index_provenance() == {}


def test_resolve_chunk_source_same_name(workdir):
    _make_chunks("docs")
    assert ingest.resolve_chunk_source("docs") == "docs"


def test_resolve_chunk_source_via_provenance(workdir):
    # Chunks live under 'docs'; cluster index is 'docs-v1' (different name).
    _make_chunks("docs")
    ingest.record_index_provenance("docs-v1", "docs")
    assert ingest.resolve_chunk_source("docs-v1") == "docs"


def test_resolve_chunk_source_none(workdir):
    # No chunks, no provenance -> structured/search-only index.
    assert ingest.resolve_chunk_source("ecommerce") == ""


def test_resolve_chunk_source_stale_provenance(workdir):
    # Provenance points to a chunk set that no longer exists -> "".
    ingest.record_index_provenance("docs-v1", "docs")
    assert ingest.resolve_chunk_source("docs-v1") == ""


# ---------------------------------------------------------------------------
# is_ingestion_running (background PID check)
# ---------------------------------------------------------------------------

def test_is_ingestion_running_no_pid_file(workdir):
    """When no PID file exists, is_ingestion_running returns False."""
    from lib.ingest import is_ingestion_running
    assert is_ingestion_running() is False


def test_is_ingestion_running_current_process(workdir):
    """When PID file contains the current process PID, returns True."""
    from lib.ingest import is_ingestion_running, PID_FILE
    pid_path = Path(PID_FILE)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))
    assert is_ingestion_running() is True


def test_is_ingestion_running_uses_psutil_on_windows(workdir, monkeypatch):
    pid_path = Path(ingest.PID_FILE)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("4194304")
    fake_psutil = type("Psutil", (), {"pid_exists": staticmethod(lambda pid: False)})

    monkeypatch.setattr(ingest, "_IS_WINDOWS", True, raising=False)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(
        ingest.os,
        "kill",
        lambda *args: pytest.fail("Windows PID checks must not call os.kill"),
    )

    assert ingest.is_ingestion_running() is False
    assert not pid_path.exists()


def test_is_ingestion_running_dead_pid(workdir):
    """When PID file contains a dead PID, returns False and cleans up the file."""
    from lib.ingest import is_ingestion_running, PID_FILE
    pid_path = Path(PID_FILE)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    # Use a PID that is almost certainly not running (max PID value).
    dead_pid = 4194304  # Typical max PID on Linux
    pid_path.write_text(str(dead_pid))
    assert is_ingestion_running() is False
    # Should have cleaned up the stale PID file.
    assert not pid_path.exists()
