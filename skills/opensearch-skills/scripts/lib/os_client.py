"""Build opensearch-py clients from runtime configuration."""

from opensearchpy import OpenSearch

from .client import OPENSEARCH_DEFAULT_USER, OPENSEARCH_DEFAULT_PASSWORD


def build_admin_client(config: dict) -> OpenSearch:
    cfg = config.get("opensearch", {})
    return _build(
        url=cfg.get("url", "https://localhost:9200"),
        username=cfg.get("admin_username", OPENSEARCH_DEFAULT_USER),
        password=cfg.get("admin_password", OPENSEARCH_DEFAULT_PASSWORD),
        ssl_verify=cfg.get("ssl_verify", False),
    )


def build_app_client(config: dict, username: str, password: str) -> OpenSearch:
    if not username or not password:
        raise ValueError("Explicit end-user credentials are required for DLS queries")
    cfg = config.get("opensearch", {})
    return _build(
        url=cfg.get("url", "https://localhost:9200"),
        username=username,
        password=password,
        ssl_verify=cfg.get("ssl_verify", False),
    )


def _build(url: str, username: str, password: str, ssl_verify: bool) -> OpenSearch:
    return OpenSearch(
        hosts=[url],
        http_auth=(username, password),
        use_ssl=url.startswith("https"),
        verify_certs=ssl_verify,
        ssl_show_warn=False,
    )
