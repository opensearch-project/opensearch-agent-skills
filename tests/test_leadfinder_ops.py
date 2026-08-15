"""Tests for leadfinder-ops skill utilities.

No running OpenSearch cluster required — these test the pure functions
(window parsing, ISO formatting, query construction) per the repo's
convention of mock/fake-based tests.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "leadfinder-ops" / "scripts" / "leadsearch.py"
spec = importlib.util.spec_from_file_location("leadsearch", SCRIPT)
assert spec is not None and spec.loader is not None, f"cannot load {SCRIPT}"
leadsearch = importlib.util.module_from_spec(spec)
sys.modules["leadsearch"] = leadsearch
spec.loader.exec_module(leadsearch)


def test_parse_window_days():
    before = datetime.now(timezone.utc)
    got = leadsearch.parse_window("30d")
    delta = before - got
    assert timedelta(days=29, hours=23) < delta < timedelta(days=30, minutes=5)


def test_parse_window_hours():
    got = leadsearch.parse_window("72h")
    delta = datetime.now(timezone.utc) - got
    assert timedelta(hours=71, minutes=55) < delta < timedelta(hours=72, minutes=5)


def test_parse_window_minutes():
    got = leadsearch.parse_window("15m")
    delta = datetime.now(timezone.utc) - got
    assert timedelta(minutes=14, seconds=30) < delta < timedelta(minutes=15, seconds=30)


def test_iso_format():
    dt = datetime(2026, 8, 14, 21, 14, 0, tzinfo=timezone(timedelta(hours=-7)))
    assert leadsearch.iso(dt) == "2026-08-15T04:14:00Z"


def test_index_body_has_knn_mapping():
    props = leadsearch.INDEX_BODY["mappings"]["properties"]
    emb = props["message_embedding"]
    assert emb["type"] == "knn_vector"
    assert emb["dimension"] == 384
    assert props["responded_at"]["type"] == "date"
    assert props["contact"]["type"] == "keyword"
    assert props["message"]["type"] == "text"


def test_index_body_enables_knn():
    assert leadsearch.INDEX_BODY["settings"]["index.knn"] is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("all tests passed")
