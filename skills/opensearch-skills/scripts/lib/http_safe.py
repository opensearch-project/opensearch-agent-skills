"""Outbound HTTP with SSRF protection.

Any URL that reaches this module is checked before a connection is made, again at
connect time (closing the DNS-rebinding window), and again for every redirect
target. Proxy environment variables are ignored so a proxy cannot be used to
reach an address the checks would reject.

Loopback is treated as restricted by default. Callers that legitimately target a
local service, such as a model runner on `localhost`, opt in explicitly with
``allow_loopback=True``; every other address range is still rejected.
"""

import http.client
import ipaddress
import socket
import urllib.request
from urllib.parse import urlparse


def is_restricted_ip(ip_str: str, *, allow_loopback: bool = False) -> bool:
    """True if ip_str is private, loopback, link-local (includes
    169.254.0.0/16), or otherwise reserved."""
    addr = ipaddress.ip_address(ip_str)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if allow_loopback and addr.is_loopback:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
        or addr.is_multicast
    )


def validate_url(url: str, *, allow_loopback: bool = False) -> None:
    """Only allow http/https URLs whose host resolves to a permitted address."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got: {parsed.scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve host: {hostname} ({e})")
    for info in infos:
        if is_restricted_ip(info[4][0], allow_loopback=allow_loopback):
            raise ValueError(f"URL resolves to a restricted address: {info[4][0]}")


class _RevalidatingConnectionMixin:
    """Re-checks the resolved address right before connecting."""

    allow_loopback = False

    def connect(self):
        for info in socket.getaddrinfo(self.host, self.port, proto=socket.IPPROTO_TCP):
            if is_restricted_ip(info[4][0], allow_loopback=self.allow_loopback):
                raise ValueError(f"URL resolves to a restricted address: {info[4][0]}")
        super().connect()


class ValidatingHTTPConnection(_RevalidatingConnectionMixin, http.client.HTTPConnection):
    pass


class ValidatingHTTPSConnection(_RevalidatingConnectionMixin, http.client.HTTPSConnection):
    pass


class _LoopbackHTTPConnection(ValidatingHTTPConnection):
    allow_loopback = True


class _LoopbackHTTPSConnection(ValidatingHTTPSConnection):
    allow_loopback = True


class ValidatingHTTPHandler(urllib.request.HTTPHandler):
    connection_class = ValidatingHTTPConnection

    def http_open(self, req):
        return self.do_open(self.connection_class, req)


class ValidatingHTTPSHandler(urllib.request.HTTPSHandler):
    connection_class = ValidatingHTTPSConnection

    def https_open(self, req):
        return self.do_open(self.connection_class, req)


class _LoopbackHTTPHandler(ValidatingHTTPHandler):
    connection_class = _LoopbackHTTPConnection


class _LoopbackHTTPSHandler(ValidatingHTTPSHandler):
    connection_class = _LoopbackHTTPSConnection


class RevalidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates each redirect target before following it."""

    allow_loopback = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, allow_loopback=self.allow_loopback)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _LoopbackRedirectHandler(RevalidatingRedirectHandler):
    allow_loopback = True


def build_safe_opener(*, allow_loopback: bool = False) -> urllib.request.OpenerDirector:
    if allow_loopback:
        handlers = (
            _LoopbackHTTPHandler(),
            _LoopbackHTTPSHandler(),
            _LoopbackRedirectHandler(),
        )
    else:
        handlers = (
            ValidatingHTTPHandler(),
            ValidatingHTTPSHandler(),
            RevalidatingRedirectHandler(),
        )
    # ProxyHandler({}) ignores HTTP_PROXY/HTTPS_PROXY so a proxy cannot reach an
    # address the validation above would reject.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), *handlers)
