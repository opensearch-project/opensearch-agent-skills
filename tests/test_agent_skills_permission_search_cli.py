"""Focused validation tests for the permission-aware-search CLI."""

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from opensearchpy import exceptions

# Make the scripts dir importable (permission_search.py + lib/ package)
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import permission_search


def _profile(**overrides):
    profile = {
        "opensearch": {
            "url": "https://localhost:9200",
            "admin_username": "admin",
            "admin_password": "password",
            "index": "permission-aware-search",
        }
    }
    profile.update(overrides)
    return profile


@pytest.mark.parametrize(
    "name,value,message",
    [
        ("PERMISSION_SEARCH_CHUNK_SIZE", "0", "at least 1"),
        ("PERMISSION_SEARCH_CHUNK_OVERLAP", "-1", "at least 0"),
        ("PERMISSION_SEARCH_CHUNK_SIZE", "large", "integer"),
        ("PERMISSION_SEARCH_EMBEDDING_DIMENSION", "0", "at least 1"),
    ],
)
def test_runtime_config_rejects_invalid_numeric_environment(
    monkeypatch, name, value, message
):
    monkeypatch.setenv(name, value)

    with pytest.raises(permission_search.ConfigurationError, match=message):
        permission_search._runtime_config(SimpleNamespace(command="ingest"))


def test_runtime_config_accepts_command_overrides():
    config = permission_search._runtime_config(SimpleNamespace(
        command="ingest",
        chunk_size=128,
        chunk_overlap=32,
        embedding_mode="none",
        embedding_dimension=256,
    ))

    assert config["chunking"] == {
        "chunk_size": 128,
        "chunk_overlap": 32,
        "max_pages": 10,
    }
    assert config["embedding"]["mode"] == "none"
    assert config["embedding"]["dimension"] == 256


@pytest.mark.parametrize(
    "argv",
    [
        ["ingest", "--input", "documents.jsonl", "--batch-size", "0"],
        ["ingest", "--input", "documents.jsonl", "--batch-size", "-1"],
        [
            "query", "--question", "test", "--user", "alice",
            "--password", "password", "--top-k", "0",
        ],
        [
            "benchmark", "--user", "alice", "--password", "password",
            "--queries", "-1",
        ],
    ],
)
def test_parser_rejects_non_positive_numeric_options(argv):
    with pytest.raises(SystemExit) as exc:
        permission_search._build_parser().parse_args(argv)

    assert exc.value.code == 2


def _check_security(monkeypatch, response=None, error=None):
    client = MagicMock()
    if error:
        client.transport.perform_request.side_effect = error
    else:
        client.transport.perform_request.return_value = response
    monkeypatch.setattr(permission_search, "_runtime_config", lambda _args: _profile())
    monkeypatch.setitem(
        sys.modules,
        "lib.os_client",
        SimpleNamespace(build_admin_client=lambda _profile: client),
    )

    return client


def test_check_security_accepts_only_exact_up(monkeypatch, capsys):
    client = _check_security(monkeypatch, {"status": "UP"})

    permission_search.cmd_check_security(SimpleNamespace())

    assert json.loads(capsys.readouterr().out) == {
        "security": "enabled",
        "dls_supported": True,
    }
    client.transport.perform_request.assert_called_once_with(
        "GET", "/_plugins/_security/health"
    )


@pytest.mark.parametrize(
    "response,expected",
    [
        (
            {"status": "DOWN"},
            {"security": "unhealthy", "dls_supported": False, "error": "health"},
        ),
        (
            {"status": "STARTING"},
            {
                "security": "unknown",
                "dls_supported": False,
                "error": "malformed_response",
            },
        ),
        (
            [],
            {
                "security": "unknown",
                "dls_supported": False,
                "error": "malformed_response",
            },
        ),
    ],
)
def test_check_security_rejects_non_up_responses(monkeypatch, capsys, response, expected):
    _check_security(monkeypatch, response)

    with pytest.raises(SystemExit) as exc:
        permission_search.cmd_check_security(SimpleNamespace())

    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out) == expected


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            exceptions.NotFoundError(404, "Not Found"),
            {"security": "disabled", "dls_supported": False, "error": "plugin_not_found"},
        ),
        (
            exceptions.AuthenticationException(401, "Unauthorized"),
            {"security": "unknown", "dls_supported": False, "error": "authentication"},
        ),
        (
            exceptions.AuthorizationException(403, "Forbidden"),
            {"security": "unknown", "dls_supported": False, "error": "authorization"},
        ),
        (
            exceptions.ConnectionError("N/A", "connection failed", None),
            {"security": "unknown", "dls_supported": False, "error": "connection"},
        ),
        (
            exceptions.SerializationError("invalid JSON"),
            {
                "security": "unknown",
                "dls_supported": False,
                "error": "malformed_response",
            },
        ),
        (
            exceptions.TransportError(503, "Unavailable"),
            {
                "security": "unknown",
                "dls_supported": False,
                "error": "transport",
                "status_code": 503,
            },
        ),
    ],
)
def test_check_security_classifies_client_failures(monkeypatch, capsys, error, expected):
    _check_security(monkeypatch, error=error)

    with pytest.raises(SystemExit) as exc:
        permission_search.cmd_check_security(SimpleNamespace())

    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out) == expected


def test_extract_text_distinguishes_unsupported_files(tmp_path):
    text_file = tmp_path / "document.txt"
    text_file.write_text("plain text")

    assert permission_search._extract_text(str(text_file)) == "plain text"
    # None means "not plain text"; rich formats go through _extract_chunks.
    assert permission_search._extract_text(str(tmp_path / "document.csv")) is None
    assert permission_search._extract_text(str(tmp_path / "report.pdf")) is None


def test_extract_chunks_distinguishes_unsupported_files(tmp_path):
    assert permission_search._extract_chunks(str(tmp_path / "data.csv"), 10) is None
    assert permission_search._extract_chunks(str(tmp_path / "notes.txt"), 10) is None


def _install_fake_ingest(monkeypatch, process_document):
    """Install a stand-in lib.ingest whose process_document is controlled."""
    module = types.ModuleType("lib.ingest")
    module.process_document = process_document
    monkeypatch.setitem(sys.modules, "lib.ingest", module)


def test_extract_chunks_delegates_to_the_shared_ingest_pipeline(
    monkeypatch, tmp_path
):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"not a pdf")
    calls = []

    def fake_process_document(path, max_pages=10, **kwargs):
        calls.append((path, max_pages))
        return [{"text": "page one", "headings": ["Intro"], "page_number": 1}]

    _install_fake_ingest(monkeypatch, fake_process_document)

    chunks = permission_search._extract_chunks(str(pdf), 25)

    # The page cap must reach the shared pipeline: it bounds peak memory.
    assert calls == [(str(pdf), 25)]
    assert chunks[0]["headings"] == ["Intro"]
    assert chunks[0]["page_number"] == 1


def test_extract_chunks_explains_optional_docling_dependency(
    monkeypatch, tmp_path
):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"not a pdf")

    def missing_dependency(path, max_pages=10, **kwargs):
        raise ImportError("No module named 'docling'")

    _install_fake_ingest(monkeypatch, missing_dependency)

    with pytest.raises(permission_search.OptionalDependencyError) as exc:
        permission_search._extract_chunks(str(pdf), 10)

    assert "--group ingestion" in str(exc.value)


def test_extract_chunks_sanitizes_converter_failures(monkeypatch, tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"not a pdf")

    def failing(path, max_pages=10, **kwargs):
        raise ValueError("sensitive converter details")

    _install_fake_ingest(monkeypatch, failing)

    with pytest.raises(permission_search.ExtractionError) as exc:
        permission_search._extract_chunks(str(pdf), 10)

    assert exc.value.filename == "report.pdf"
    assert exc.value.error_type == "ValueError"
    # Converter messages can embed file paths and document content.
    assert "sensitive converter details" not in str(exc.value)


def test_ingest_reports_supported_file_conversion_failures(
    monkeypatch, tmp_path, capsys
):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "report.pdf").write_bytes(b"not a pdf")
    acl_path = tmp_path / "acl.json"
    acl_path.write_text(json.dumps({"report.pdf": ["alice"]}))
    writer = MagicMock()
    monkeypatch.setattr(
        permission_search,
        "_extract_chunks",
        MagicMock(side_effect=permission_search.ExtractionError(
            "report.pdf", "ValueError"
        )),
    )

    with pytest.raises(SystemExit) as exc:
        permission_search.cmd_ingest(
            SimpleNamespace(
                command="ingest",
                input=str(documents),
                acl_file=str(acl_path),
                batch_size=50,
            ),
            writer_factory=lambda _profile: writer,
            chunk_text_fn=lambda text, chunk_size, chunk_overlap: [text],
        )

    assert exc.value.code == 1
    writer.bulk_index.assert_not_called()
    assert json.loads(capsys.readouterr().out) == {
        "indexed": 0,
        "skipped": 1,
        "errors": [{
            "file": "report.pdf",
            "reason": "conversion_failed",
            "error_type": "ValueError",
        }],
    }


def test_ingest_indexes_converter_chunks_with_structure(monkeypatch, tmp_path, capsys):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "report.pdf").write_bytes(b"not a pdf")
    acl_path = tmp_path / "acl.json"
    acl_path.write_text(json.dumps({"report.pdf": ["alice", "GROUP_Finance"]}))
    indexed = []
    writer = MagicMock()
    writer.bulk_index.side_effect = lambda docs: (
        indexed.extend(docs) or {"indexed": len(docs), "errors": []}
    )
    monkeypatch.setattr(
        permission_search,
        "_extract_chunks",
        lambda path, max_pages: [
            {"text": "budget overview", "headings": ["Q3"], "page_number": 1},
            {"text": "detail table", "headings": ["Q3", "Detail"], "page_number": 2},
            {"text": "   "},  # whitespace-only chunks are dropped
        ],
    )

    permission_search.cmd_ingest(
        SimpleNamespace(
            command="ingest",
            input=str(documents),
            acl_file=str(acl_path),
            batch_size=50,
        ),
        writer_factory=lambda _profile: writer,
        chunk_text_fn=lambda text, chunk_size, chunk_overlap: [text],
    )

    result = json.loads(capsys.readouterr().out)
    assert result == {"indexed": 2, "skipped": 0}
    # The converter's own chunking is preserved rather than re-split, and its
    # structure is carried through so an answer can cite a page.
    assert [d["content"] for d in indexed] == ["budget overview", "detail table"]
    assert indexed[1]["headings"] == ["Q3", "Detail"]
    assert indexed[1]["page_number"] == 2
    assert indexed[0]["allowed_users"] == ["alice", "GROUP_Finance"]
    # Stable ids keep a re-run idempotent.
    assert [d["_id"] for d in indexed] == ["report.pdf#0", "report.pdf#1"]


def test_ingest_skips_a_document_that_converts_to_nothing(monkeypatch, tmp_path, capsys):
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "scan.pdf").write_bytes(b"not a pdf")
    acl_path = tmp_path / "acl.json"
    acl_path.write_text(json.dumps({"scan.pdf": ["alice"]}))
    writer = MagicMock()
    monkeypatch.setattr(permission_search, "_extract_chunks", lambda path, max_pages: [])

    permission_search.cmd_ingest(
        SimpleNamespace(
            command="ingest",
            input=str(documents),
            acl_file=str(acl_path),
            batch_size=50,
        ),
        writer_factory=lambda _profile: writer,
        chunk_text_fn=lambda text, chunk_size, chunk_overlap: [text],
    )

    result = json.loads(capsys.readouterr().out)
    assert result == {"indexed": 0, "skipped": 1}
    writer.bulk_index.assert_not_called()
