"""OpenSearch client creation, connectivity checks, and Docker bootstrap."""

import os
import platform
import re
import shutil
import subprocess
import sys
import time

from opensearchpy import OpenSearch

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_AUTH_MODE_ENV = "OPENSEARCH_AUTH_MODE"
OPENSEARCH_AUTH_MODE_DEFAULT = "default"
OPENSEARCH_AUTH_MODE_NONE = "none"
OPENSEARCH_AUTH_MODE_CUSTOM = "custom"
OPENSEARCH_USER_ENV = "OPENSEARCH_USER"
OPENSEARCH_PASSWORD_ENV = "OPENSEARCH_PASSWORD"
OPENSEARCH_DEFAULT_USER = "admin"
OPENSEARCH_DEFAULT_PASSWORD = "myStrongPassword123!"
OPENSEARCH_DOCKER_IMAGE = os.getenv(
    "OPENSEARCH_DOCKER_IMAGE", "opensearchproject/opensearch:latest"
)
OPENSEARCH_DOCKER_CONTAINER = os.getenv("OPENSEARCH_DOCKER_CONTAINER", "opensearch-local")
OPENSEARCH_DOCKER_START_TIMEOUT = int(os.getenv("OPENSEARCH_DOCKER_START_TIMEOUT", "120"))

_AUTH_FAILURE_TOKENS = (
    "401", "403", "unauthorized", "forbidden",
    "authentication", "security_exception",
    "missing authentication credentials",
)


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    return " ".join(text.split())


def resolve_http_auth() -> tuple[str, str] | None:
    mode = os.getenv("OPENSEARCH_AUTH_MODE", "default").strip().lower()
    if mode == "none":
        return None
    if mode == "custom":
        user = os.getenv("OPENSEARCH_USER", "").strip()
        password = os.getenv("OPENSEARCH_PASSWORD", "").strip()
        if not user or not password:
            raise RuntimeError(
                "OPENSEARCH_AUTH_MODE=custom requires OPENSEARCH_USER and OPENSEARCH_PASSWORD."
            )
        return user, password
    return OPENSEARCH_DEFAULT_USER, OPENSEARCH_DEFAULT_PASSWORD


def build_client(use_ssl: bool, http_auth: tuple[str, str] | None = None) -> OpenSearch:
    kwargs = {
        "hosts": [{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        "use_ssl": use_ssl,
        "verify_certs": False,
        "ssl_show_warn": False,
        "timeout": 60,
    }
    if http_auth is not None:
        kwargs["http_auth"] = http_auth
    return OpenSearch(**kwargs)


def can_connect(client: OpenSearch) -> tuple[bool, bool]:
    try:
        client.info()
        return True, False
    except Exception as e:
        lowered = normalize_text(e).lower()
        if "404" in lowered or "notfounderror" in lowered:
            try:
                client.cat.indices(format="json")
                return True, False
            except Exception:
                pass
            try:
                client.search(index="*", body={"size": 0}, params={"timeout": "5s"})
                return True, False
            except Exception as se:
                sl = normalize_text(se).lower()
                if "403" in sl or "forbidden" in sl:
                    return True, False
        auth_failure = any(t in lowered for t in _AUTH_FAILURE_TOKENS)
        return False, auth_failure


def _resolve_docker() -> str:
    system = platform.system().lower()
    candidates = {
        "darwin": [
            "/usr/local/bin/docker",
            "/opt/homebrew/bin/docker",
            "/Applications/Docker.app/Contents/Resources/bin/docker",
        ],
        "linux": ["/usr/bin/docker", "/usr/local/bin/docker", "/snap/bin/docker"],
    }.get(system, [])

    from_env = os.getenv("OPENSEARCH_DOCKER_CLI_PATH", "").strip()
    if from_env:
        candidates.insert(0, from_env)

    from_path = shutil.which("docker")
    if from_path:
        candidates.insert(0, from_path)

    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path

    raise RuntimeError(
        "Docker CLI not found. Install Docker or set OPENSEARCH_DOCKER_CLI_PATH."
    )


def _run_docker(command: list[str]) -> subprocess.CompletedProcess:
    docker = _resolve_docker()
    return subprocess.run(
        [docker] + command,
        capture_output=True, text=True, timeout=60,
    )


def _start_local_container() -> None:
    result = _run_docker(["ps", "--format", "{{.Names}}"])
    if OPENSEARCH_DOCKER_CONTAINER in (result.stdout or "").split():
        print(f"Container '{OPENSEARCH_DOCKER_CONTAINER}' already running.", file=sys.stderr)
        return

    _run_docker(["rm", "-f", OPENSEARCH_DOCKER_CONTAINER])

    password = os.getenv("OPENSEARCH_PASSWORD", OPENSEARCH_DEFAULT_PASSWORD).strip() or OPENSEARCH_DEFAULT_PASSWORD
    print(f"Starting OpenSearch container '{OPENSEARCH_DOCKER_CONTAINER}'...", file=sys.stderr)
    result = _run_docker([
        "run", "-d",
        "--name", OPENSEARCH_DOCKER_CONTAINER,
        "-p", f"{OPENSEARCH_PORT}:9200",
        "-p", "9600:9600",
        "-e", "discovery.type=single-node",
        "-e", "DISABLE_SECURITY_PLUGIN=true",
        "-e", f"OPENSEARCH_INITIAL_ADMIN_PASSWORD={password}",
        OPENSEARCH_DOCKER_IMAGE,
    ])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to start container: {result.stderr}")


def _wait_for_cluster() -> OpenSearch:
    http_auth = resolve_http_auth()
    secure = build_client(use_ssl=True, http_auth=http_auth)
    insecure = build_client(use_ssl=False, http_auth=http_auth)
    deadline = time.time() + OPENSEARCH_DOCKER_START_TIMEOUT

    while time.time() < deadline:
        ok, _ = can_connect(secure)
        if ok:
            return secure
        ok, _ = can_connect(insecure)
        if ok:
            return insecure
        time.sleep(2)

    raise RuntimeError(
        f"OpenSearch did not become ready within {OPENSEARCH_DOCKER_START_TIMEOUT}s."
    )


def _is_local_host(host: str) -> bool:
    """Check if the given host is a local address."""
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def preflight_check_cluster(
    auth_mode: str = "",
    username: str = "",
    password: str = "",
) -> dict:
    """Probe the configured OpenSearch host:port before execution.

    On the first call (no auth args), probes with no-auth and default creds.
    If the result is ``auth_required``, the caller should ask the user for
    credentials and call again with ``auth_mode="custom"``, ``username``,
    and ``password``.  When custom creds succeed the function sets
    ``OPENSEARCH_AUTH_MODE``, ``OPENSEARCH_USER``, and ``OPENSEARCH_PASSWORD``
    as in-process environment variables so every subsequent tool call
    (``create_index``, ``execute_plan``, etc.) picks them up automatically
    via ``resolve_http_auth()``.

    Args:
        auth_mode: ``""`` (auto-detect), ``"none"``, ``"default"``, or ``"custom"``.
        username: Required when auth_mode is ``"custom"``.
        password: Required when auth_mode is ``"custom"``.

    Returns:
        dict with status, host, port, is_local, message, auth_modes_tried,
        and auth_mode (when status is "available").
    """
    host = OPENSEARCH_HOST
    port = OPENSEARCH_PORT
    is_local = _is_local_host(host)
    result: dict = {"host": host, "port": port, "is_local": is_local}

    normalized_mode = str(auth_mode or "").strip().lower()

    # --- Caller-supplied custom credentials ---
    if normalized_mode == "custom":
        user = str(username or "").strip()
        pwd = str(password or "").strip()
        if not user or not pwd:
            result["status"] = "error"
            result["message"] = (
                "auth_mode='custom' requires both username and password."
            )
            result["auth_modes_tried"] = []
            return result

        custom_auth = (user, pwd)
        for use_ssl in (True, False):
            client = build_client(use_ssl=use_ssl, http_auth=custom_auth)
            ok, _ = can_connect(client)
            if ok:
                # Persist creds in-process for all subsequent tool calls.
                os.environ[OPENSEARCH_AUTH_MODE_ENV] = OPENSEARCH_AUTH_MODE_CUSTOM
                os.environ[OPENSEARCH_USER_ENV] = user
                os.environ[OPENSEARCH_PASSWORD_ENV] = pwd
                ssl_label = "SSL" if use_ssl else "HTTP"
                result["status"] = "available"
                result["auth_mode"] = "custom"
                result["message"] = (
                    f"Connected to OpenSearch at {host}:{port} ({ssl_label}) "
                    f"with provided credentials. Credentials set for this session."
                )
                result["auth_modes_tried"] = [
                    f"custom_{'ssl' if use_ssl else 'http'}"
                ]
                return result

        result["status"] = "auth_required"
        result["message"] = (
            f"OpenSearch cluster at {host}:{port} rejected the provided "
            f"credentials. Please verify username/password and try again."
        )
        result["auth_modes_tried"] = ["custom_ssl", "custom_http"]
        return result

    # --- Caller-supplied no-auth mode ---
    if normalized_mode == "none":
        for use_ssl in (False, True):
            client = build_client(use_ssl=use_ssl, http_auth=None)
            ok, _ = can_connect(client)
            if ok:
                os.environ[OPENSEARCH_AUTH_MODE_ENV] = OPENSEARCH_AUTH_MODE_NONE
                os.environ.pop(OPENSEARCH_USER_ENV, None)
                os.environ.pop(OPENSEARCH_PASSWORD_ENV, None)
                ssl_label = "SSL" if use_ssl else "HTTP"
                result["status"] = "available"
                result["auth_mode"] = "none"
                result["message"] = (
                    f"Connected to OpenSearch at {host}:{port} ({ssl_label}) "
                    f"with no authentication. Auth mode set for this session."
                )
                result["auth_modes_tried"] = [
                    f"none_{'ssl' if use_ssl else 'http'}"
                ]
                return result

        result["status"] = "auth_required"
        result["message"] = (
            f"Could not connect to OpenSearch at {host}:{port} without "
            f"authentication. The cluster may require credentials."
        )
        result["auth_modes_tried"] = ["none_http", "none_ssl"]
        return result

    # --- Explicit default mode ---
    if normalized_mode == "default":
        default_auth = (OPENSEARCH_DEFAULT_USER, OPENSEARCH_DEFAULT_PASSWORD)
        for use_ssl in (True, False):
            client = build_client(use_ssl=use_ssl, http_auth=default_auth)
            ok, _ = can_connect(client)
            if ok:
                os.environ[OPENSEARCH_AUTH_MODE_ENV] = OPENSEARCH_AUTH_MODE_DEFAULT
                os.environ.pop(OPENSEARCH_USER_ENV, None)
                os.environ.pop(OPENSEARCH_PASSWORD_ENV, None)
                ssl_label = "SSL" if use_ssl else "HTTP"
                result["status"] = "available"
                result["auth_mode"] = "default"
                result["message"] = (
                    f"Connected to OpenSearch at {host}:{port} ({ssl_label}) "
                    f"using default credentials. Auth mode set for this session."
                )
                result["auth_modes_tried"] = [
                    f"default_{'ssl' if use_ssl else 'http'}"
                ]
                return result

        result["status"] = "auth_required"
        result["message"] = (
            f"Could not connect to OpenSearch at {host}:{port} with "
            f"default credentials. The cluster may require custom credentials."
        )
        result["auth_modes_tried"] = ["default_ssl", "default_http"]
        return result

    # --- Auto-detect (no auth args supplied) ---
    auth_modes_tried: list[str] = []
    saw_auth_failure = False

    default_auth = (OPENSEARCH_DEFAULT_USER, OPENSEARCH_DEFAULT_PASSWORD)
    probes: list[tuple[bool, tuple[str, str] | None, str]] = [
        (False, None, "none_http"),
        (True, None, "none_ssl"),
        (True, default_auth, "default_ssl"),
        (False, default_auth, "default_http"),
    ]

    for use_ssl, http_auth, label in probes:
        auth_modes_tried.append(label)
        client = build_client(use_ssl=use_ssl, http_auth=http_auth)
        ok, auth_fail = can_connect(client)
        if ok:
            mode_name = "none" if http_auth is None else "default"
            ssl_label = "SSL" if use_ssl else "HTTP"
            if http_auth is None:
                detail = f"with security disabled (no auth, {ssl_label})"
                os.environ[OPENSEARCH_AUTH_MODE_ENV] = OPENSEARCH_AUTH_MODE_NONE
                os.environ.pop(OPENSEARCH_USER_ENV, None)
                os.environ.pop(OPENSEARCH_PASSWORD_ENV, None)
            else:
                detail = f"({ssl_label}) using default credentials"
                os.environ[OPENSEARCH_AUTH_MODE_ENV] = OPENSEARCH_AUTH_MODE_DEFAULT
                os.environ.pop(OPENSEARCH_USER_ENV, None)
                os.environ.pop(OPENSEARCH_PASSWORD_ENV, None)
            result["status"] = "available"
            result["auth_mode"] = mode_name
            result["message"] = (
                f"OpenSearch cluster detected at {host}:{port} {detail}."
            )
            result["auth_modes_tried"] = auth_modes_tried
            return result
        if auth_fail:
            saw_auth_failure = True

    result["auth_modes_tried"] = auth_modes_tried
    if saw_auth_failure:
        result["status"] = "auth_required"
        result["message"] = (
            f"OpenSearch cluster detected at {host}:{port} but authentication "
            f"failed with all attempted credentials. Please provide your "
            f"credentials or allow bootstrapping a new local cluster."
        )
    else:
        result["status"] = "no_cluster"
        result["message"] = (
            f"No OpenSearch cluster detected at {host}:{port}. "
            f"A local cluster can be bootstrapped via Docker."
        )
    return result


def clear_cluster_credentials() -> None:
    """Remove in-process cluster credentials set by ``preflight_check_cluster``.

    Call this at the end of a session (e.g. from ``cleanup()``) so credentials
    do not linger in the process environment.
    """
    os.environ.pop(OPENSEARCH_AUTH_MODE_ENV, None)
    os.environ.pop(OPENSEARCH_USER_ENV, None)
    os.environ.pop(OPENSEARCH_PASSWORD_ENV, None)


def create_client() -> OpenSearch:
    http_auth = resolve_http_auth()

    secure = build_client(use_ssl=True, http_auth=http_auth)
    ok, _ = can_connect(secure)
    if ok:
        return secure

    insecure = build_client(use_ssl=False, http_auth=http_auth)
    ok, auth_fail = can_connect(insecure)
    if ok:
        return insecure

    if auth_fail:
        raise RuntimeError(
            f"Authentication failed connecting to OpenSearch at {OPENSEARCH_HOST}:{OPENSEARCH_PORT}."
        )

    _start_local_container()
    return _wait_for_cluster()


def create_remote_client(
    endpoint: str,
    port: int = 443,
    use_ssl: bool = True,
    username: str = "",
    password: str = "",
    aws_region: str = "",
    aws_service: str = "",
) -> OpenSearch:
    kwargs: dict = {
        "hosts": [{"host": endpoint, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": use_ssl,
        "ssl_show_warn": False,
    }

    if aws_region and aws_service:
        import boto3
        from opensearchpy import AWSV4SignerAuth, RequestsHttpConnection
        session = boto3.Session()
        credentials = session.get_credentials()
        kwargs["http_auth"] = AWSV4SignerAuth(credentials, aws_region, aws_service)
        kwargs["connection_class"] = RequestsHttpConnection
    elif username and password:
        kwargs["http_auth"] = (username, password)

    return OpenSearch(**kwargs)
