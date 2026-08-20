"""Client construction tests for lib/os_client.py, focused on TLS verification."""

import sys
from pathlib import Path

import pytest

# Make the scripts/lib package importable
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib import os_client


@pytest.fixture
def captured(monkeypatch):
    """Capture the kwargs os_client passes to the OpenSearch constructor."""
    calls = []

    def fake_opensearch(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(os_client, "OpenSearch", fake_opensearch)
    return calls


def _config(url, **overrides):
    opensearch = {"url": url}
    opensearch.update(overrides)
    return {"opensearch": opensearch}


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:9200",
        "https://127.0.0.1:9200",
        "https://127.1.2.3:9200",
        "https://LOCALHOST:9200",
    ],
)
def test_loopback_hosts_skip_certificate_verification(captured, url):
    os_client.build_admin_client(_config(url))

    assert captured[0]["verify_certs"] is False
    assert captured[0]["ssl_show_warn"] is False


@pytest.mark.parametrize(
    "url",
    [
        "https://search.example.com:9200",
        "https://10.0.0.5:9200",
        "https://localhost.evil.example:9200",
    ],
)
def test_remote_hosts_verify_certificates_by_default(captured, url):
    os_client.build_admin_client(_config(url))

    assert captured[0]["verify_certs"] is True, (
        "credentials must not be sent to a non-loopback host over unverified TLS"
    )
    assert captured[0]["ssl_show_warn"] is True


def test_explicit_ssl_verify_overrides_the_host_default(captured):
    os_client.build_admin_client(_config("https://localhost:9200", ssl_verify=True))
    assert captured[0]["verify_certs"] is True

    os_client.build_admin_client(_config("https://search.example.com:9200", ssl_verify=False))
    assert captured[1]["verify_certs"] is False


def test_plain_http_never_claims_to_verify(captured):
    os_client.build_admin_client(_config("http://search.example.com:9200"))

    assert captured[0]["use_ssl"] is False
    assert captured[0]["verify_certs"] is False


def test_clients_set_a_request_timeout(captured):
    os_client.build_admin_client(_config("https://localhost:9200"))

    assert captured[0]["timeout"] == os_client.REQUEST_TIMEOUT


def test_admin_client_uses_configured_credentials(captured):
    config = _config(
        "https://localhost:9200",
        admin_username="operator",
        admin_password="secret",
    )

    os_client.build_admin_client(config)

    assert captured[0]["http_auth"] == ("operator", "secret")


def test_admin_client_omits_auth_when_no_credentials_are_configured(captured):
    # OPENSEARCH_AUTH_MODE=none targets a cluster without the security plugin;
    # empty basic auth would be rejected rather than treated as anonymous.
    os_client.build_admin_client(
        _config("https://localhost:9200", admin_username="", admin_password="")
    )

    assert "http_auth" not in captured[0]


def test_app_client_uses_the_end_user_identity(captured):
    os_client.build_app_client(
        _config("https://localhost:9200", admin_username="admin"),
        "alice",
        "alice-password",
    )

    assert captured[0]["http_auth"] == ("alice", "alice-password")


@pytest.mark.parametrize(
    ("username", "password"),
    [("", "password"), ("alice", ""), ("", "")],
)
def test_app_client_requires_explicit_end_user_credentials(captured, username, password):
    with pytest.raises(ValueError, match="end-user credentials"):
        os_client.build_app_client(
            _config("https://localhost:9200"), username, password
        )

    assert captured == []


def test_app_client_inherits_the_remote_verification_default(captured):
    os_client.build_app_client(
        _config("https://search.example.com:9200"), "alice", "alice-password"
    )

    assert captured[0]["verify_certs"] is True


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://localhost:9200", True),
        ("https://127.0.0.1:9200", True),
        ("https://[::1]:9200", True),
        ("https://search.example.com:9200", False),
        ("https://localhost.evil.example:9200", False),
        ("not-a-url", False),
    ],
)
def test_is_loopback_host(url, expected):
    assert os_client.is_loopback_host(url) is expected
