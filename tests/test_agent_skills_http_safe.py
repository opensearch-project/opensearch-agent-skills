"""SSRF protection tests for lib/http_safe.py."""

import socket
import sys
from pathlib import Path

import pytest

# Make the scripts/lib package importable
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib import http_safe


@pytest.fixture
def resolves_to(monkeypatch):
    """Force DNS resolution to a chosen address."""

    def _resolve(address):
        monkeypatch.setattr(
            http_safe.socket,
            "getaddrinfo",
            lambda host, port, **kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))
            ],
        )

    return _resolve


@pytest.mark.parametrize(
    "scheme",
    ["file", "ftp", "gopher", "data"],
)
def test_validate_url_rejects_non_http_schemes(scheme):
    with pytest.raises(ValueError, match="scheme must be http"):
        http_safe.validate_url(f"{scheme}://example.com/x")


def test_validate_url_requires_a_hostname():
    with pytest.raises(ValueError, match="must include a hostname"):
        http_safe.validate_url("http://")


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",       # loopback
        "10.0.0.5",        # private
        "192.168.1.1",     # private
        "172.16.0.1",      # private
        "169.254.169.254", # link-local, the cloud metadata endpoint
        "0.0.0.0",         # unspecified
        "224.0.0.1",       # multicast
    ],
)
def test_validate_url_rejects_restricted_addresses(resolves_to, address):
    resolves_to(address)

    with pytest.raises(ValueError, match="restricted address"):
        http_safe.validate_url("https://target.example")


def test_validate_url_allows_a_public_address(resolves_to):
    resolves_to("93.184.216.34")

    http_safe.validate_url("https://target.example")


def test_validate_url_rejects_ipv4_mapped_loopback(resolves_to):
    # ::ffff:127.0.0.1 must not slip past the IPv4 checks.
    resolves_to("::ffff:127.0.0.1")

    with pytest.raises(ValueError, match="restricted address"):
        http_safe.validate_url("https://target.example")


def test_validate_url_reports_an_unresolvable_host(monkeypatch):
    def fail(host, port, **kwargs):
        raise socket.gaierror("nodename nor servname provided")

    monkeypatch.setattr(http_safe.socket, "getaddrinfo", fail)

    with pytest.raises(ValueError, match="Could not resolve host"):
        http_safe.validate_url("https://nonexistent.example")


def test_allow_loopback_permits_loopback_only(resolves_to):
    resolves_to("127.0.0.1")

    # Opting in is required for a local model runner...
    http_safe.validate_url("http://localhost:12434/engines/v1", allow_loopback=True)

    # ...and must not also permit other restricted ranges.
    resolves_to("169.254.169.254")
    with pytest.raises(ValueError, match="restricted address"):
        http_safe.validate_url("http://metadata.example", allow_loopback=True)

    resolves_to("10.0.0.5")
    with pytest.raises(ValueError, match="restricted address"):
        http_safe.validate_url("http://internal.example", allow_loopback=True)


@pytest.mark.parametrize("allow_loopback", [False, True])
def test_safe_opener_ignores_environment_proxies(monkeypatch, allow_loopback):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")

    opener = http_safe.build_safe_opener(allow_loopback=allow_loopback)

    # An empty ProxyHandler registers no proxy_open method, so build_opener
    # drops it from the chain entirely. Its absence is what proves the
    # environment cannot route a request through a proxy to reach a blocked
    # address; a default opener would carry one built from HTTP_PROXY.
    assert not any(
        isinstance(handler, http_safe.urllib.request.ProxyHandler)
        for handler in opener.handlers
    )
    assert any(
        isinstance(handler, http_safe.urllib.request.ProxyHandler)
        for handler in http_safe.urllib.request.build_opener().handlers
    ), "a default opener should pick up the proxy environment we just set"


def test_safe_opener_installs_validating_handlers():
    opener = http_safe.build_safe_opener()

    assert any(
        isinstance(h, http_safe.ValidatingHTTPHandler) for h in opener.handlers
    )
    assert any(
        isinstance(h, http_safe.ValidatingHTTPSHandler) for h in opener.handlers
    )
    assert any(
        isinstance(h, http_safe.RevalidatingRedirectHandler) for h in opener.handlers
    )


def test_redirect_targets_are_revalidated(resolves_to):
    resolves_to("169.254.169.254")
    handler = http_safe.RevalidatingRedirectHandler()

    # A public URL that redirects to the metadata endpoint must be stopped.
    with pytest.raises(ValueError, match="restricted address"):
        handler.redirect_request(
            None, None, 302, "Found", {}, "http://metadata.example/latest"
        )


def test_connection_revalidates_the_address_at_connect_time(resolves_to):
    # Closes the DNS-rebinding window: the name resolved to a public address
    # during validation but points somewhere restricted by connect time.
    resolves_to("10.0.0.5")
    connection = http_safe.ValidatingHTTPConnection("target.example", 80)

    with pytest.raises(ValueError, match="restricted address"):
        connection.connect()


def test_loopback_connection_class_permits_loopback(resolves_to, monkeypatch):
    resolves_to("127.0.0.1")
    connected = []
    monkeypatch.setattr(
        http_safe.http.client.HTTPConnection, "connect", lambda self: connected.append(True)
    )

    http_safe._LoopbackHTTPConnection("localhost", 12434).connect()

    assert connected == [True]


def test_samples_module_reuses_this_implementation():
    from lib import samples

    assert samples._validate_url is http_safe.validate_url
    assert samples._build_safe_opener is http_safe.build_safe_opener
    assert samples._is_restricted_ip is http_safe.is_restricted_ip
