"""Tests for Agent Skills preflight cluster check functionality."""

import os
import sys
from pathlib import Path

import pytest

# Add agent skills scripts to path
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts")
)

from lib.client import preflight_check_cluster, clear_cluster_credentials


class _ConnectableClient:
    """Simulates a cluster that responds successfully."""

    def info(self):
        return {"version": {"number": "2.19.0"}}


class _AuthFailureClient:
    """Simulates a cluster that rejects credentials."""

    def info(self):
        raise RuntimeError("401 Unauthorized")


class _UnreachableClient:
    """Simulates no cluster listening."""

    def info(self):
        from opensearchpy.exceptions import ConnectionError as OSConnectionError

        raise OSConnectionError("N/A", "Connection refused", Exception("refused"))


def test_preflight_detects_no_auth_cluster(monkeypatch):
    """No-auth insecure cluster is detected as available."""

    def _build(use_ssl: bool, http_auth=None):
        if not use_ssl and http_auth is None:
            return _ConnectableClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["status"] == "available"
    assert result["auth_mode"] == "none"
    assert "security disabled" in result["message"]


def test_preflight_detects_ssl_no_auth_cluster(monkeypatch):
    """No-auth SSL cluster is detected as available."""

    def _build(use_ssl: bool, http_auth=None):
        if use_ssl and http_auth is None:
            return _ConnectableClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["status"] == "available"
    assert result["auth_mode"] == "none"


def test_preflight_detects_default_creds_cluster(monkeypatch):
    """Cluster reachable with default admin creds is detected as available."""

    def _build(use_ssl: bool, http_auth=None):
        if http_auth is None:
            return _UnreachableClient()
        if http_auth == ("admin", "myStrongPassword123!"):
            return _ConnectableClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["status"] == "available"
    assert result["auth_mode"] == "default"
    assert "default credentials" in result["message"]


def test_preflight_detects_auth_required(monkeypatch):
    """Cluster that rejects both no-auth and default creds returns auth_required."""

    def _build(use_ssl: bool, http_auth=None):
        return _AuthFailureClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["status"] == "auth_required"
    assert "authentication failed" in result["message"].lower()


def test_preflight_ssl_cluster_with_custom_creds_not_misdetected(monkeypatch):
    """HTTPS cluster with non-default creds: no-auth gets auth failure,
    default creds also get auth failure. Should return auth_required, not no_cluster."""

    def _build(use_ssl: bool, http_auth=None):
        if not use_ssl:
            return _UnreachableClient()
        return _AuthFailureClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["status"] == "auth_required"
    assert "authentication failed" in result["message"].lower()
    assert len(result["auth_modes_tried"]) == 4


def test_preflight_ssl_default_creds_succeeds_after_noauth_authfail(monkeypatch):
    """HTTPS cluster where no-auth returns 401 but default creds work.
    This is the common Docker OpenSearch case."""

    def _build(use_ssl: bool, http_auth=None):
        if not use_ssl:
            return _UnreachableClient()
        if http_auth is None:
            return _AuthFailureClient()
        if http_auth == ("admin", "myStrongPassword123!"):
            return _ConnectableClient()
        return _AuthFailureClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["status"] == "available"
    assert result["auth_mode"] == "default"
    assert "SSL" in result["message"]


def test_preflight_detects_no_cluster(monkeypatch):
    """Nothing listening returns no_cluster."""

    def _build(use_ssl: bool, http_auth=None):
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["status"] == "no_cluster"
    assert "no opensearch cluster detected" in result["message"].lower()
    assert result["is_local"] is True


def test_preflight_returns_host_port_info(monkeypatch):
    """Result always includes host, port, and is_local."""

    def _build(use_ssl: bool, http_auth=None):
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster()

    assert result["host"] == "localhost"
    assert result["port"] == 9200
    assert result["is_local"] is True
    assert "auth_modes_tried" in result


def test_preflight_custom_creds_success_sets_env_vars(monkeypatch):
    """Custom creds that succeed set OPENSEARCH_AUTH_MODE/USER/PASSWORD env vars."""

    def _build(use_ssl: bool, http_auth=None):
        if http_auth == ("myuser", "mypass"):
            return _ConnectableClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)
    monkeypatch.delenv("OPENSEARCH_AUTH_MODE", raising=False)
    monkeypatch.delenv("OPENSEARCH_USER", raising=False)
    monkeypatch.delenv("OPENSEARCH_PASSWORD", raising=False)

    result = preflight_check_cluster(
        auth_mode="custom", username="myuser", password="mypass"
    )

    assert result["status"] == "available"
    assert result["auth_mode"] == "custom"
    assert "myuser" not in result["message"]  # creds not leaked in message
    assert os.environ.get("OPENSEARCH_AUTH_MODE") == "custom"
    assert os.environ.get("OPENSEARCH_USER") == "myuser"
    assert os.environ.get("OPENSEARCH_PASSWORD") == "mypass"


def test_preflight_custom_creds_failure(monkeypatch):
    """Custom creds that fail return auth_required without setting env vars."""

    def _build(use_ssl: bool, http_auth=None):
        return _AuthFailureClient() if http_auth else _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)
    monkeypatch.delenv("OPENSEARCH_AUTH_MODE", raising=False)
    monkeypatch.delenv("OPENSEARCH_USER", raising=False)
    monkeypatch.delenv("OPENSEARCH_PASSWORD", raising=False)

    result = preflight_check_cluster(
        auth_mode="custom", username="bad", password="wrong"
    )

    assert result["status"] == "auth_required"
    assert "rejected" in result["message"].lower()
    assert os.environ.get("OPENSEARCH_AUTH_MODE") is None
    assert os.environ.get("OPENSEARCH_USER") is None


def test_preflight_custom_creds_missing_returns_error(monkeypatch):
    """Custom mode without username/password returns error."""

    def _build(use_ssl: bool, http_auth=None):
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster(auth_mode="custom", username="", password="")

    assert result["status"] == "error"
    assert "requires" in result["message"].lower()


def test_preflight_none_mode_success_sets_env(monkeypatch):
    """Explicit none mode that succeeds sets OPENSEARCH_AUTH_MODE=none."""

    def _build(use_ssl: bool, http_auth=None):
        if http_auth is None:
            return _ConnectableClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)
    monkeypatch.delenv("OPENSEARCH_AUTH_MODE", raising=False)

    result = preflight_check_cluster(auth_mode="none")

    assert result["status"] == "available"
    assert result["auth_mode"] == "none"
    assert os.environ.get("OPENSEARCH_AUTH_MODE") == "none"
    assert os.environ.get("OPENSEARCH_USER") is None


def test_preflight_none_mode_failure(monkeypatch):
    """Explicit none mode that fails returns auth_required."""

    def _build(use_ssl: bool, http_auth=None):
        return _AuthFailureClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)

    result = preflight_check_cluster(auth_mode="none")

    assert result["status"] == "auth_required"


def test_preflight_default_mode_success(monkeypatch):
    """Explicit default mode that succeeds sets OPENSEARCH_AUTH_MODE=default."""

    def _build(use_ssl: bool, http_auth=None):
        if http_auth == ("admin", "myStrongPassword123!"):
            return _ConnectableClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)
    monkeypatch.delenv("OPENSEARCH_AUTH_MODE", raising=False)

    result = preflight_check_cluster(auth_mode="default")

    assert result["status"] == "available"
    assert result["auth_mode"] == "default"
    assert os.environ.get("OPENSEARCH_AUTH_MODE") == "default"


def test_clear_cluster_credentials(monkeypatch):
    """clear_cluster_credentials removes all auth env vars."""

    monkeypatch.setenv("OPENSEARCH_AUTH_MODE", "custom")
    monkeypatch.setenv("OPENSEARCH_USER", "admin")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "secret")

    clear_cluster_credentials()

    assert os.environ.get("OPENSEARCH_AUTH_MODE") is None
    assert os.environ.get("OPENSEARCH_USER") is None
    assert os.environ.get("OPENSEARCH_PASSWORD") is None


def test_clear_cluster_credentials_noop_when_unset():
    """clear_cluster_credentials is safe to call when env vars are not set."""

    os.environ.pop("OPENSEARCH_AUTH_MODE", None)
    os.environ.pop("OPENSEARCH_USER", None)
    os.environ.pop("OPENSEARCH_PASSWORD", None)

    # Should not raise
    clear_cluster_credentials()


def test_autodetect_sets_env_for_default_creds(monkeypatch):
    """Auto-detect mode that finds default creds sets OPENSEARCH_AUTH_MODE=default."""

    def _build(use_ssl: bool, http_auth=None):
        if http_auth == ("admin", "myStrongPassword123!") and use_ssl:
            return _ConnectableClient()
        if http_auth is None:
            return _AuthFailureClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)
    monkeypatch.delenv("OPENSEARCH_AUTH_MODE", raising=False)

    result = preflight_check_cluster()

    assert result["status"] == "available"
    assert result["auth_mode"] == "default"
    assert os.environ.get("OPENSEARCH_AUTH_MODE") == "default"


def test_autodetect_sets_env_for_none_mode(monkeypatch):
    """Auto-detect mode that finds no-auth cluster sets OPENSEARCH_AUTH_MODE=none."""

    def _build(use_ssl: bool, http_auth=None):
        if not use_ssl and http_auth is None:
            return _ConnectableClient()
        return _UnreachableClient()

    from lib import client as client_module
    monkeypatch.setattr(client_module, "build_client", _build)
    monkeypatch.delenv("OPENSEARCH_AUTH_MODE", raising=False)

    result = preflight_check_cluster()

    assert result["status"] == "available"
    assert result["auth_mode"] == "none"
    assert os.environ.get("OPENSEARCH_AUTH_MODE") == "none"
    assert os.environ.get("OPENSEARCH_USER") is None
