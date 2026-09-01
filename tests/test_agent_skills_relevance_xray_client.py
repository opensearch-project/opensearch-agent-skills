"""Connection security tests for the standalone Relevance X-Ray client."""

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "search"
    / "relevance-x-ray"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

from relevance_xray_lib import client


def test_resolve_http_auth_rejects_default_credentials_for_remote_host(monkeypatch):
    monkeypatch.setattr(client, "OPENSEARCH_HOST", "search.example.com")
    monkeypatch.setenv("OPENSEARCH_AUTH_MODE", "default")

    with pytest.raises(RuntimeError, match="only available for local"):
        client.resolve_http_auth()


def test_remote_auto_preflight_never_probes_with_default_credentials(monkeypatch):
    probes = []

    def probe(auth, label, **kwargs):
        probes.append((auth, label))
        return False, True, [f"{label}_ssl"]

    monkeypatch.setattr(client, "OPENSEARCH_HOST", "search.example.com")
    monkeypatch.setattr(client, "_probe", probe)

    result = client.preflight_check_cluster()

    assert probes == [(None, "none")]
    assert result["status"] == "auth_required"
    assert result["auth_modes_tried"] == ["none_ssl"]
    assert "custom credentials" in result["message"]
