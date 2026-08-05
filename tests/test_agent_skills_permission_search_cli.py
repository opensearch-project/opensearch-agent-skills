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

    assert config["chunking"] == {"chunk_size": 128, "chunk_overlap": 32}
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
    assert permission_search._extract_text(str(tmp_path / "document.csv")) is None


def test_extract_text_explains_optional_docling_dependency(
    monkeypatch, tmp_path
):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"not a pdf")
    monkeypatch.setitem(sys.modules, "docling", None)
    monkeypatch.delitem(sys.modules, "docling.document_converter", raising=False)

    with pytest.raises(permission_search.OptionalDependencyError) as exc:
        permission_search._extract_text(str(pdf))

    assert "--group ingestion" in str(exc.value)


def test_extract_text_sanitizes_converter_failures(monkeypatch, tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"not a pdf")
    converter_module = types.ModuleType("docling.document_converter")

    class FailingConverter:
        def convert(self, _path):
            raise ValueError("sensitive converter details")

    converter_module.DocumentConverter = FailingConverter
    docling_module = types.ModuleType("docling")
    docling_module.__path__ = []
    monkeypatch.setitem(sys.modules, "docling", docling_module)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)

    with pytest.raises(permission_search.ExtractionError) as exc:
        permission_search._extract_text(str(pdf))

    assert exc.value.filename == "report.pdf"
    assert exc.value.error_type == "ValueError"
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
        "_extract_text",
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
