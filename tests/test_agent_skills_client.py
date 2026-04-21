"""Tests for skills/scripts/lib/client.py"""

import os
import sys
from pathlib import Path

import pytest

# Make the scripts/lib package importable
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.client import (
    normalize_text,
    resolve_http_auth,
    build_client,
    can_connect,
    OPENSEARCH_DEFAULT_USER,
    OPENSEARCH_DEFAULT_PASSWORD,
)


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------
def test_normalize_text_collapses_whitespace():
    assert normalize_text("  hello   world  ") == "hello world"


def test_normalize_text_handles_none():
    assert normalize_text(None) == ""


def test_normalize_text_converts_non_string():
    assert normalize_text(42) == "42"


def test_normalize_text_handles_empty_string():
    assert normalize_text("") == ""


def test_normalize_text_preserves_single_word():
    assert normalize_text("hello") == "hello"


# ---------------------------------------------------------------------------
# resolve_http_auth
# ---------------------------------------------------------------------------
def test_resolve_http_auth_default_mode(monkeypatch):
    monkeypatch.delenv("OPENSEARCH_AUTH_MODE", raising=False)
    monkeypatch.delenv("OPENSEARCH_USER", raising=False)
    monkeypatch.delenv("OPENSEARCH_PASSWORD", raising=False)

    result = resolve_http_auth()

    assert result == (OPENSEARCH_DEFAULT_USER, OPENSEARCH_DEFAULT_PASSWORD)


def test_resolve_http_auth_none_mode(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_AUTH_MODE", "none")

    result = resolve_http_auth()

    assert result is None


def test_resolve_http_auth_custom_mode(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_AUTH_MODE", "custom")
    monkeypatch.setenv("OPENSEARCH_USER", "myuser")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "mypass")

    result = resolve_http_auth()

    assert result == ("myuser", "mypass")


def test_resolve_http_auth_custom_mode_missing_user(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_AUTH_MODE", "custom")
    monkeypatch.delenv("OPENSEARCH_USER", raising=False)
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "mypass")

    with pytest.raises(RuntimeError, match="requires OPENSEARCH_USER and OPENSEARCH_PASSWORD"):
        resolve_http_auth()


def test_resolve_http_auth_custom_mode_missing_password(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_AUTH_MODE", "custom")
    monkeypatch.setenv("OPENSEARCH_USER", "myuser")
    monkeypatch.delenv("OPENSEARCH_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="requires OPENSEARCH_USER and OPENSEARCH_PASSWORD"):
        resolve_http_auth()


def test_resolve_http_auth_case_insensitive(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_AUTH_MODE", "  None  ")

    result = resolve_http_auth()

    assert result is None


# ---------------------------------------------------------------------------
# build_client
# ---------------------------------------------------------------------------
def test_build_client_ssl_with_auth(monkeypatch):
    calls = []

    class _FakeOpenSearch:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    import lib.client as client_mod
    monkeypatch.setattr(client_mod, "OpenSearch", _FakeOpenSearch)

    build_client(use_ssl=True, http_auth=("admin", "pass"))

    assert len(calls) == 1
    assert calls[0]["use_ssl"] is True
    assert calls[0]["http_auth"] == ("admin", "pass")
    assert calls[0]["verify_certs"] is False


def test_build_client_no_ssl_no_auth(monkeypatch):
    calls = []

    class _FakeOpenSearch:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    import lib.client as client_mod
    monkeypatch.setattr(client_mod, "OpenSearch", _FakeOpenSearch)

    build_client(use_ssl=False, http_auth=None)

    assert len(calls) == 1
    assert calls[0]["use_ssl"] is False
    assert "http_auth" not in calls[0]


# ---------------------------------------------------------------------------
# can_connect
# ---------------------------------------------------------------------------
def test_can_connect_success():
    class _FakeClient:
        def info(self):
            return {"version": {"number": "2.17.0"}}

    ok, auth_fail = can_connect(_FakeClient())

    assert ok is True
    assert auth_fail is False


def test_can_connect_auth_failure():
    class _FakeClient:
        def info(self):
            raise Exception("security_exception: missing authentication credentials")

    ok, auth_fail = can_connect(_FakeClient())

    assert ok is False
    assert auth_fail is True


def test_can_connect_generic_failure():
    class _FakeClient:
        def info(self):
            raise Exception("Connection refused")

    ok, auth_fail = can_connect(_FakeClient())

    assert ok is False
    assert auth_fail is False


def test_can_connect_404_with_fallback_cat_success():
    class _FakeCat:
        def indices(self, format="json"):
            return []

    class _FakeClient:
        def __init__(self):
            self.cat = _FakeCat()

        def info(self):
            raise Exception("NotFoundError 404")

    ok, auth_fail = can_connect(_FakeClient())

    assert ok is True
    assert auth_fail is False


def test_can_connect_403_token_detected():
    class _FakeClient:
        def info(self):
            raise Exception("403 Forbidden")

    ok, auth_fail = can_connect(_FakeClient())

    assert ok is False
    assert auth_fail is True
