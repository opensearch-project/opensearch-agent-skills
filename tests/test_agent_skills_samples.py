"""Tests for skills/opensearch-skills/scripts/lib/samples.py"""

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.samples import (
    _load_records_from_file,
    _infer_text_fields,
    load_sample_from_file,
    load_sample_from_paste,
)


# ---------------------------------------------------------------------------
# _infer_text_fields
# ---------------------------------------------------------------------------
def test_infer_text_fields_detects_multiword_strings():
    doc = {
        "id": "1",
        "title": "The quick brown fox jumps",
        "count": 42,
    }
    result = _infer_text_fields(doc)

    assert "title" in result
    assert "id" not in result
    assert "count" not in result


def test_infer_text_fields_ignores_short_strings():
    doc = {"code": "AB", "name": "ok then"}

    result = _infer_text_fields(doc)

    assert "code" not in result


def test_infer_text_fields_empty_doc():
    assert _infer_text_fields({}) == []


def test_infer_text_fields_non_string_values():
    doc = {"count": 100, "flag": True, "tags": ["a", "b"]}

    assert _infer_text_fields(doc) == []


# ---------------------------------------------------------------------------
# _load_records_from_file — JSON
# ---------------------------------------------------------------------------
def test_load_records_json_array(tmp_path):
    f = tmp_path / "data.json"
    f.write_text(json.dumps([{"a": 1}, {"a": 2}, {"a": 3}]))

    records, error = _load_records_from_file(f, limit=2)

    assert error is None
    assert len(records) == 2
    assert records[0]["a"] == 1


def test_load_records_jsonl(tmp_path):
    f = tmp_path / "data.jsonl"
    f.write_text('{"x":1}\n{"x":2}\n{"x":3}\n')

    records, error = _load_records_from_file(f, limit=10)

    assert error is None
    assert len(records) == 3


def test_load_records_json_empty_lines_skipped(tmp_path):
    f = tmp_path / "data.ndjson"
    f.write_text('{"x":1}\n\n{"x":2}\n\n')

    records, error = _load_records_from_file(f, limit=10)

    assert error is None
    assert len(records) == 2


# ---------------------------------------------------------------------------
# _load_records_from_file — CSV/TSV
# ---------------------------------------------------------------------------
def test_load_records_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("id,name,score\n1,Alice,95\n2,Bob,87\n3,Carol,91\n")

    records, error = _load_records_from_file(f, limit=2)

    assert error is None
    assert len(records) == 2
    assert records[0]["name"] == "Alice"


def test_load_records_tsv(tmp_path):
    f = tmp_path / "data.tsv"
    f.write_text("tconst\tprimaryTitle\n" "tt001\tCarmencita\n" "tt002\tClown\n")

    records, error = _load_records_from_file(f, limit=10)

    assert error is None
    assert len(records) == 2
    assert records[0]["tconst"] == "tt001"


# ---------------------------------------------------------------------------
# _load_records_from_file — unsupported
# ---------------------------------------------------------------------------
def test_load_records_unsupported_format(tmp_path):
    f = tmp_path / "data.xml"
    f.write_text("<root/>")

    records, error = _load_records_from_file(f, limit=10)

    assert records == []
    assert "Unsupported file format" in error


# ---------------------------------------------------------------------------
# load_sample_from_file
# ---------------------------------------------------------------------------
def test_load_sample_from_file_success(tmp_path):
    f = tmp_path / "movies.json"
    f.write_text(json.dumps([
        {"title": "The Matrix is a great movie", "year": 1999},
        {"title": "Inception is mind bending", "year": 2010},
    ]))

    result = json.loads(load_sample_from_file(str(f)))

    assert result["status"] == "loaded"
    assert result["record_count"] == 2
    assert result["sample_doc"]["title"] == "The Matrix is a great movie"
    assert "title" in result["text_fields"]
    assert result["text_search_required"] is True


def test_load_sample_from_file_not_found():
    result = json.loads(load_sample_from_file("/nonexistent/path.json"))

    assert "error" in result
    assert "not found" in result["error"].lower()


def test_load_sample_from_file_empty_records(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("[]")

    result = json.loads(load_sample_from_file(str(f)))

    assert "error" in result
    assert "No records" in result["error"]


def test_load_sample_from_file_numeric_only(tmp_path):
    f = tmp_path / "numeric.json"
    f.write_text(json.dumps([{"id": 1, "score": 99.5}]))

    result = json.loads(load_sample_from_file(str(f)))

    assert result["status"] == "loaded"
    assert result["text_fields"] == []
    assert result["text_search_required"] is False


# ---------------------------------------------------------------------------
# load_sample_from_paste
# ---------------------------------------------------------------------------
def test_load_sample_from_paste_valid_json():
    doc = '{"title": "Test document with enough words", "id": 1}'

    result = json.loads(load_sample_from_paste(doc))

    assert result["status"] == "loaded"
    assert result["source"] == "paste"
    assert result["record_count"] == 1
    assert result["sample_doc"]["id"] == 1


def test_load_sample_from_paste_invalid_json():
    result = json.loads(load_sample_from_paste("not json at all"))

    assert "error" in result
    assert "Invalid JSON" in result["error"]


def test_load_sample_from_paste_non_object():
    result = json.loads(load_sample_from_paste("[1, 2, 3]"))

    assert "error" in result
    assert "must be a JSON object" in result["error"]


def test_load_sample_from_paste_text_field_detection():
    doc = json.dumps({
        "title": "A document with several words here",
        "code": "XY",
    })

    result = json.loads(load_sample_from_paste(doc))

    assert "title" in result["text_fields"]
    assert "code" not in result["text_fields"]


# ---------------------------------------------------------------------------
# _load_records_from_file — limit enforcement
# ---------------------------------------------------------------------------
def test_load_records_respects_limit_csv(tmp_path):
    rows = "id,val\n" + "\n".join(f"{i},v{i}" for i in range(50))
    f = tmp_path / "big.csv"
    f.write_text(rows)

    records, error = _load_records_from_file(f, limit=5)

    assert error is None
    assert len(records) == 5


def test_load_records_respects_limit_jsonl(tmp_path):
    lines = "\n".join(json.dumps({"i": i}) for i in range(50))
    f = tmp_path / "big.jsonl"
    f.write_text(lines)

    records, error = _load_records_from_file(f, limit=3)

    assert error is None
    assert len(records) == 3
