"""Build opensearch-py clients from runtime configuration."""

from urllib.parse import urlsplit

from opensearchpy import OpenSearch

from .client import OPENSEARCH_DEFAULT_USER, OPENSEARCH_DEFAULT_PASSWORD

REQUEST_TIMEOUT = 60


def build_admin_client(config: dict) -> OpenSearch:
    cfg = config.get("opensearch", {})
    return _build(
        url=cfg.get("url", "https://localhost:9200"),
        username=cfg.get("admin_username", OPENSEARCH_DEFAULT_USER),
        password=cfg.get("admin_password", OPENSEARCH_DEFAULT_PASSWORD),
        ssl_verify=cfg.get("ssl_verify"),
    )


def build_app_client(config: dict, username: str, password: str) -> OpenSearch:
    if not username or not password:
        raise ValueError("Explicit end-user credentials are required for DLS queries")
    cfg = config.get("opensearch", {})
    return _build(
        url=cfg.get("url", "https://localhost:9200"),
        username=username,
        password=password,
        ssl_verify=cfg.get("ssl_verify"),
    )


def is_loopback_host(url: str) -> bool:
    """Report whether a URL points at the local machine."""
    host = (urlsplit(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.startswith("127.")


def _build(
    url: str, username: str, password: str, ssl_verify: bool | None = None
) -> OpenSearch:
    use_ssl = url.startswith("https")
    # Certificate verification is disabled only for loopback hosts, which
    # typically serve the self-signed certificate of a local Docker cluster.
    # Any other host is verified so that admin and end-user credentials cannot
    # be captured by a man-in-the-middle. Pass ssl_verify to override.
    if ssl_verify is None:
        verify = use_ssl and not is_loopback_host(url)
    else:
        verify = bool(ssl_verify)
    kwargs = {
        "hosts": [url],
        "use_ssl": use_ssl,
        "verify_certs": verify,
        "ssl_show_warn": verify,
        "timeout": REQUEST_TIMEOUT,
    }
    # OPENSEARCH_AUTH_MODE=none yields no credentials, for a cluster running
    # without the security plugin. Sending empty basic auth would fail instead.
    if username and password:
        kwargs["http_auth"] = (username, password)
    return OpenSearch(**kwargs)
