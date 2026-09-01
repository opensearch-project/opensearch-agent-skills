"""Read-only OpenSearch connections for the standalone Relevance X-Ray skill."""

from __future__ import annotations

import os

from opensearchpy import OpenSearch


OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
_DEFAULT_USER = "admin"
_DEFAULT_PASSWORD = "myStrongPassword123!"
_AUTH_FAILURE_TOKENS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "authentication",
    "security_exception",
    "missing authentication credentials",
)


def _is_local_host(host: str) -> bool:
    normalized = str(host or "").strip().lower().rstrip(".")
    return normalized in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def connection_ssl_modes(
    http_auth: tuple[str, str] | None,
    *,
    host: str | None = None,
    prefer_ssl: bool = True,
) -> tuple[bool, ...]:
    """Never send Basic credentials over remote plaintext HTTP."""
    target_host = OPENSEARCH_HOST if host is None else host
    if http_auth is not None and not _is_local_host(target_host):
        return (True,)
    return (True, False) if prefer_ssl else (False, True)


def resolve_http_auth() -> tuple[str, str] | None:
    mode = os.getenv("OPENSEARCH_AUTH_MODE", "default").strip().lower()
    if mode == "none":
        return None
    if mode == "custom":
        user = os.getenv("OPENSEARCH_USER", "").strip()
        password = os.getenv("OPENSEARCH_PASSWORD", "").strip()
        if not user or not password:
            raise RuntimeError(
                "OPENSEARCH_AUTH_MODE=custom requires OPENSEARCH_USER and "
                "OPENSEARCH_PASSWORD."
            )
        return user, password
    if not _is_local_host(OPENSEARCH_HOST):
        raise RuntimeError(
            "Default credentials are only available for local OpenSearch endpoints; "
            "set OPENSEARCH_AUTH_MODE=custom with OPENSEARCH_USER and "
            "OPENSEARCH_PASSWORD for a remote endpoint."
        )
    return _DEFAULT_USER, _DEFAULT_PASSWORD


def build_client(
    use_ssl: bool,
    http_auth: tuple[str, str] | None = None,
) -> OpenSearch:
    verify = use_ssl and not _is_local_host(OPENSEARCH_HOST)
    kwargs = {
        "hosts": [{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        "use_ssl": use_ssl,
        "verify_certs": verify,
        "ssl_show_warn": verify,
        "timeout": 60,
    }
    if http_auth is not None:
        kwargs["http_auth"] = http_auth
    return OpenSearch(**kwargs)


def can_connect(client: OpenSearch) -> tuple[bool, bool]:
    try:
        client.info()
        return True, False
    except Exception as exc:
        lowered = " ".join(str(exc).split()).lower()
        if "404" in lowered or "notfounderror" in lowered:
            try:
                client.cat.indices(format="json")
                return True, False
            except Exception:
                pass
            try:
                client.search(index="*", body={"size": 0}, params={"timeout": "5s"})
                return True, False
            except Exception as search_exc:
                search_error = " ".join(str(search_exc).split()).lower()
                if "403" in search_error or "forbidden" in search_error:
                    return True, False
        return False, any(token in lowered for token in _AUTH_FAILURE_TOKENS)


def _set_auth_environment(
    mode: str,
    username: str = "",
    password: str = "",
) -> None:
    os.environ["OPENSEARCH_AUTH_MODE"] = mode
    if mode == "custom":
        os.environ["OPENSEARCH_USER"] = username
        os.environ["OPENSEARCH_PASSWORD"] = password
    else:
        os.environ.pop("OPENSEARCH_USER", None)
        os.environ.pop("OPENSEARCH_PASSWORD", None)


def _probe(
    auth: tuple[str, str] | None,
    label: str,
    *,
    host: str,
    prefer_ssl: bool = True,
) -> tuple[bool, bool, list[str]]:
    attempts: list[str] = []
    saw_auth_failure = False
    for use_ssl in connection_ssl_modes(
        auth,
        host=host,
        prefer_ssl=prefer_ssl,
    ):
        attempts.append(f"{label}_{'ssl' if use_ssl else 'http'}")
        client = build_client(use_ssl=use_ssl, http_auth=auth)
        connected, auth_failure = can_connect(client)
        saw_auth_failure = saw_auth_failure or auth_failure
        if connected:
            return True, saw_auth_failure, attempts
    return False, saw_auth_failure, attempts


def preflight_check_cluster(
    auth_mode: str = "",
    username: str = "",
    password: str = "",
) -> dict:
    """Probe a configured cluster without bootstrapping or mutating anything."""
    host = OPENSEARCH_HOST
    port = OPENSEARCH_PORT
    is_local = _is_local_host(host)
    result = {"host": host, "port": port, "is_local": is_local}
    mode = str(auth_mode or "").strip().lower()

    if mode == "custom":
        user = str(username or "").strip()
        pwd = str(password or "").strip()
        if not user or not pwd:
            return {
                **result,
                "status": "error",
                "message": "auth_mode='custom' requires both username and password.",
                "auth_modes_tried": [],
            }
        connected, _, attempts = _probe((user, pwd), "custom", host=host)
        if connected:
            _set_auth_environment("custom", user, pwd)
            return {
                **result,
                "status": "available",
                "auth_mode": "custom",
                "message": f"Connected to OpenSearch at {host}:{port}.",
                "auth_modes_tried": attempts,
            }
        return {
            **result,
            "status": "auth_required",
            "message": (
                f"Could not authenticate to OpenSearch at {host}:{port}. "
                + (
                    "Plaintext HTTP was not attempted because the endpoint is not local."
                    if not is_local
                    else "Verify the provided credentials."
                )
            ),
            "auth_modes_tried": attempts,
        }

    if mode in {"none", "default"}:
        if mode == "default" and not is_local:
            return {
                **result,
                "status": "auth_required",
                "message": (
                    "Default credentials are only available for local OpenSearch "
                    "endpoints; use auth_mode='custom' for a remote endpoint."
                ),
                "auth_modes_tried": [],
            }
        auth = None if mode == "none" else (_DEFAULT_USER, _DEFAULT_PASSWORD)
        connected, _, attempts = _probe(
            auth,
            mode,
            host=host,
            prefer_ssl=mode != "none",
        )
        if connected:
            _set_auth_environment(mode)
            return {
                **result,
                "status": "available",
                "auth_mode": mode,
                "message": f"Connected to OpenSearch at {host}:{port}.",
                "auth_modes_tried": attempts,
            }
        return {
            **result,
            "status": "auth_required",
            "message": (
                f"Could not connect to OpenSearch at {host}:{port}. "
                + (
                    "Plaintext HTTP was not attempted with credentials because "
                    "the endpoint is not local."
                    if auth is not None and not is_local
                    else "Verify the endpoint and authentication mode."
                )
            ),
            "auth_modes_tried": attempts,
        }

    attempts: list[str] = []
    connected, saw_auth_failure, tried = _probe(
        None,
        "none",
        host=host,
        prefer_ssl=False,
    )
    attempts.extend(tried)
    if connected:
        _set_auth_environment("none")
        return {
            **result,
            "status": "available",
            "auth_mode": "none",
            "message": f"Connected to OpenSearch at {host}:{port} without authentication.",
            "auth_modes_tried": attempts,
        }

    if not is_local:
        return {
            **result,
            "status": "auth_required" if saw_auth_failure else "no_cluster",
            "message": (
                (
                    f"OpenSearch at {host}:{port} requires custom credentials."
                    if saw_auth_failure
                    else f"No usable OpenSearch cluster detected at {host}:{port}."
                )
                + " This diagnostic skill never sends bundled default credentials "
                "to remote endpoints."
            ),
            "auth_modes_tried": attempts,
        }

    connected, default_auth_failure, tried = _probe(
        (_DEFAULT_USER, _DEFAULT_PASSWORD),
        "default",
        host=host,
    )
    attempts.extend(tried)
    if connected:
        _set_auth_environment("default")
        return {
            **result,
            "status": "available",
            "auth_mode": "default",
            "message": f"Connected to OpenSearch at {host}:{port} with default credentials.",
            "auth_modes_tried": attempts,
        }
    saw_auth_failure = saw_auth_failure or default_auth_failure
    return {
        **result,
        "status": "auth_required" if saw_auth_failure else "no_cluster",
        "message": (
            (
                f"OpenSearch at {host}:{port} requires different credentials."
                if saw_auth_failure
                else f"No usable OpenSearch cluster detected at {host}:{port}."
            )
            + " This diagnostic skill never bootstraps Docker."
        ),
        "auth_modes_tried": attempts,
    }
