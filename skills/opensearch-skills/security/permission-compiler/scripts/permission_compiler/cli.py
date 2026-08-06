"""Command-line interface for the OpenSearch Permission Compiler."""

from __future__ import annotations

import argparse
import base64
import http.client
import ipaddress
import json
import math
import os
import socket
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.parse import (
    SplitResult,
    parse_qsl,
    unquote,
    urlencode,
    urlsplit,
    urlunsplit,
)

from .core import (
    WorkflowError,
    compile_role,
    parse_evidence_document,
    validate_workflow,
    verify_workflow,
)

_MAX_RESPONSE_BYTES = 1024 * 1024


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int,
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
        timeout: float,
    ):
        super().__init__(host, port=port, timeout=timeout)
        self._pinned_address = address

    def connect(self) -> None:
        self.sock = _connect_pinned_address(
            self._pinned_address, self.port, self.timeout
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
        timeout: float,
        context: ssl.SSLContext,
    ):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned_address = address

    def connect(self) -> None:
        raw_socket = _connect_pinned_address(
            self._pinned_address, self.port, self.timeout
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket, server_hostname=self.host
            )
        except Exception:
            raw_socket.close()
            raise


def _connect_pinned_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    port: int,
    timeout: float,
) -> socket.socket:
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    connection = socket.socket(family, socket.SOCK_STREAM)
    try:
        connection.settimeout(timeout)
        target = (
            (str(address), port, 0, 0)
            if family == socket.AF_INET6
            else (str(address), port)
        )
        connection.connect(target)
        return connection
    except Exception:
        connection.close()
        raise


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkflowError(f"file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"invalid JSON in {path}: {exc}") from exc


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _permission_check_path(path: str) -> str:
    parts = urlsplit(path)
    if (
        parts.scheme
        or parts.netloc
        or parts.fragment
        or not parts.path.startswith("/")
    ):
        raise WorkflowError(
            "workflow step path must be root-relative and contain no fragment"
        )
    decoded_path = parts.path
    for _ in range(2):
        decoded_path = unquote(decoded_path)
    if "\\" in decoded_path or any(
        segment in {".", ".."} for segment in decoded_path.split("/")
    ):
        raise WorkflowError("workflow step path contains an unsafe segment")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key != "perform_permission_check"
    ]
    query.append(("perform_permission_check", "true"))
    return urlunsplit(("", "", parts.path, urlencode(query), parts.fragment))


def _ssl_context(ca_cert: str | None) -> ssl.SSLContext:
    return (
        ssl.create_default_context(cafile=ca_cert)
        if ca_cert
        else ssl.create_default_context()
    )


def _read_response_body(stream: Any) -> str:
    payload = stream.read(_MAX_RESPONSE_BYTES + 1)
    if len(payload) > _MAX_RESPONSE_BYTES:
        raise WorkflowError(
            f"permission-check response exceeds {_MAX_RESPONSE_BYTES} bytes"
        )
    return payload.decode("utf-8", errors="replace")


def _resolved_probe_addresses(
    host: str, port: int
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        results = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WorkflowError("probe host could not be resolved") from exc
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for result in results:
        raw_address = result[4][0].split("%", 1)[0]
        address = ipaddress.ip_address(raw_address)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        addresses.add(address)
    if not addresses:
        raise WorkflowError("probe host did not resolve to an IP address")
    return addresses


def _probe_url_parts(
    base_url: str,
) -> tuple[SplitResult, ipaddress.IPv4Address | ipaddress.IPv6Address | None]:
    parts = urlsplit(base_url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not parts.netloc or not host:
        raise WorkflowError("probe base URL must include a host")
    if parts.username is not None or parts.password is not None:
        raise WorkflowError("probe base URL must not contain user information")
    try:
        explicit_port = parts.port
    except ValueError as exc:
        raise WorkflowError("probe base URL contains an invalid port") from exc
    literal_address = None
    try:
        literal_address = ipaddress.ip_address(host)
        if (
            isinstance(literal_address, ipaddress.IPv6Address)
            and literal_address.ipv4_mapped
        ):
            literal_address = literal_address.ipv4_mapped
    except ValueError:
        pass
    if host in {"metadata.google.internal", "metadata.azure.internal"}:
        raise WorkflowError("probe refuses known cloud metadata hostnames")
    if scheme not in {"http", "https"}:
        raise WorkflowError("probe base URL must use HTTPS or loopback HTTP")
    is_literal_loopback = literal_address is not None and literal_address.is_loopback
    if scheme == "http" and not is_literal_loopback:
        raise WorkflowError(
            "probe refuses to send credentials over a non-HTTPS URL; "
            "plaintext HTTP is allowed only for loopback development clusters"
        )
    if parts.query or parts.fragment:
        raise WorkflowError("probe base URL must not contain a query or fragment")
    return parts, literal_address


def _validate_probe_url(
    base_url: str, allow_private_target: bool = False
) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]:
    parts, literal_address = _probe_url_parts(base_url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    explicit_port = parts.port
    is_literal_loopback = literal_address is not None and literal_address.is_loopback
    port = explicit_port or (443 if scheme == "https" else 80)
    addresses = (
        {literal_address}
        if literal_address is not None
        else _resolved_probe_addresses(host, port)
    )
    for address in addresses:
        if (
            address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or (address.is_reserved and not address.is_loopback)
        ):
            raise WorkflowError(
                "probe refuses link-local, unspecified, multicast, or reserved "
                "target addresses"
            )
        if (
            (address.is_private or address.is_loopback)
            and not allow_private_target
            and not (scheme == "http" and is_literal_loopback)
        ):
            raise WorkflowError(
                "probe refuses private or loopback HTTPS targets unless "
                "--allow-private-target is set"
            )
        if not address.is_global and not (address.is_private or address.is_loopback):
            raise WorkflowError("probe refuses non-global target addresses")
    return tuple(sorted(addresses, key=lambda address: (address.version, int(address))))


def _compose_probe_url(base_url: str, path: str) -> str:
    base_parts, _ = _probe_url_parts(base_url)
    permission_path = _permission_check_path(path)
    if not permission_path.startswith("/") or permission_path.startswith("//"):
        raise WorkflowError("workflow step path must begin with exactly one slash")
    permission_parts = urlsplit(permission_path)
    base_path = base_parts.path.rstrip("/")
    decoded_base_path = base_path
    for _ in range(2):
        decoded_base_path = unquote(decoded_base_path)
    if "\\" in decoded_base_path or any(
        segment in {".", ".."} for segment in decoded_base_path.split("/")
    ):
        raise WorkflowError("probe base URL path contains an unsafe segment")
    combined_path = base_path + permission_parts.path
    url = urlunsplit(
        (
            base_parts.scheme,
            base_parts.netloc,
            combined_path,
            permission_parts.query,
            "",
        )
    )
    url_parts = urlsplit(url)
    base_origin = (
        base_parts.scheme.lower(),
        (base_parts.hostname or "").lower(),
        base_parts.port,
    )
    url_origin = (
        url_parts.scheme.lower(),
        (url_parts.hostname or "").lower(),
        url_parts.port,
    )
    if url_origin != base_origin:
        raise WorkflowError("workflow step path resolves outside the probe origin")
    expected_path_prefix = f"{base_path}/" if base_path else "/"
    if not url_parts.path.startswith(expected_path_prefix):
        raise WorkflowError("workflow step path resolves outside the probe base path")
    return url


def _positive_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be a positive finite number")
    return timeout


def _validate_credentials(username: str, password: str) -> None:
    if ":" in username:
        raise WorkflowError("OpenSearch username must not contain ':'")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in username):
        raise WorkflowError("OpenSearch username must not contain control characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in password):
        raise WorkflowError("OpenSearch password must not contain control characters")


def _probe_step(
    base_url: str,
    step: dict[str, Any],
    username: str,
    password: str,
    ca_cert: str | None,
    timeout: float,
    allow_private_target: bool = False,
) -> dict[str, Any]:
    # Keep these validated addresses coupled to the connection loop below. The
    # pinned transport must never perform a second hostname lookup.
    addresses = _validate_probe_url(base_url, allow_private_target)
    url = _compose_probe_url(base_url, step["path"])
    _validate_credentials(username, password)
    body = step.get("body")
    data = None if body is None else json.dumps(body).encode("utf-8")
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    url_parts = urlsplit(url)
    host = url_parts.hostname or ""
    port = url_parts.port or (443 if url_parts.scheme == "https" else 80)
    request_target = urlunsplit(("", "", url_parts.path or "/", url_parts.query, ""))
    last_error: Exception | None = None
    for address in addresses:
        connection: http.client.HTTPConnection
        if url_parts.scheme == "https":
            connection = _PinnedHTTPSConnection(
                host, port, address, timeout, _ssl_context(ca_cert)
            )
        else:
            connection = _PinnedHTTPConnection(host, port, address, timeout)
        try:
            connection.request(
                str(step.get("method", "GET")).upper(),
                request_target,
                body=data,
                headers=headers,
            )
            response = connection.getresponse()
            try:
                payload = _read_response_body(response)
            except WorkflowError as exc:
                return {"response_error": str(exc), "status": response.status}
            if 300 <= response.status < 400:
                return {
                    "response_error": "probe refuses redirect responses",
                    "status": response.status,
                }
            try:
                parsed = json.loads(payload) if payload else {}
            except json.JSONDecodeError:
                parsed = {"error_body": payload}
            if isinstance(parsed, dict):
                parsed.setdefault("status", response.status)
            return parsed
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            last_error = exc
        finally:
            connection.close()
    return {"connection_error": str(last_error), "status": 0}


def _command_compile(args: argparse.Namespace) -> int:
    workflow = _load_json(args.workflow)
    evidence = []
    for path in args.evidence:
        evidence.extend(parse_evidence_document(_load_json(path), str(path)))
    candidate, report = compile_role(workflow, evidence)
    _write_json(args.output, candidate)
    _write_json(args.report, report)
    print(f"Wrote candidate role: {args.output}")
    print(f"Wrote evidence report: {args.report}")
    return 0 if report["safe_to_review"] else 2


def _command_probe(args: argparse.Namespace) -> int:
    workflow = _load_json(args.workflow)
    validate_workflow(workflow)
    username = args.username or os.getenv("OPENSEARCH_USERNAME")
    password = os.getenv("OPENSEARCH_PASSWORD")
    if not username or not password:
        raise WorkflowError(
            "probe requires --username/OPENSEARCH_USERNAME and a password via "
            "OPENSEARCH_PASSWORD; password flags are intentionally unsupported"
        )
    base_url = args.url or os.getenv("OPENSEARCH_URL")
    if not base_url:
        raise WorkflowError("probe requires --url or OPENSEARCH_URL")
    evidence = []
    connection_failures = []
    for step in workflow["steps"]:
        response = _probe_step(
            base_url=base_url,
            step=step,
            username=username,
            password=password,
            ca_cert=args.ca_cert,
            timeout=args.timeout,
            allow_private_target=args.allow_private_target,
        )
        evidence.append({"step_id": step["id"], "response": response})
        if "connection_error" in response or "response_error" in response:
            connection_failures.append(step["id"])
    _write_json(args.output, evidence)
    print(f"Wrote permission-check evidence: {args.output}")
    if connection_failures:
        print(
            "error: probe failed to collect usable evidence for steps: "
            + ", ".join(connection_failures),
            file=sys.stderr,
        )
        return 2
    return 0


def _command_verify(args: argparse.Namespace) -> int:
    workflow = _load_json(args.workflow)
    evidence = []
    for path in args.evidence:
        evidence.extend(parse_evidence_document(_load_json(path), str(path)))
    report = verify_workflow(workflow, evidence)
    _write_json(args.report, report)
    print(f"Wrote verification report: {args.report}")
    return 0 if report["passed"] else 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opensearch-permission-compiler",
        description=(
            "Compile OpenSearch permission-check evidence into an observed-minimum "
            "role candidate."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser(
        "compile", help="compile evidence into a role candidate"
    )
    compile_parser.add_argument("--workflow", type=Path, required=True)
    compile_parser.add_argument(
        "--evidence", type=Path, required=True, action="append"
    )
    compile_parser.add_argument("--output", type=Path, required=True)
    compile_parser.add_argument("--report", type=Path, required=True)
    compile_parser.set_defaults(handler=_command_compile)

    probe_parser = subparsers.add_parser(
        "probe", help="run non-mutating OpenSearch permission checks"
    )
    probe_parser.add_argument("--workflow", type=Path, required=True)
    probe_parser.add_argument("--output", type=Path, required=True)
    probe_parser.add_argument("--url")
    probe_parser.add_argument("--username")
    probe_parser.add_argument("--ca-cert")
    probe_parser.add_argument(
        "--allow-private-target",
        action="store_true",
        help=(
            "allow HTTPS targets that resolve to private or loopback addresses; "
            "link-local and metadata targets remain forbidden"
        ),
    )
    probe_parser.add_argument("--timeout", type=_positive_timeout, default=10.0)
    probe_parser.set_defaults(handler=_command_probe)

    verify_parser = subparsers.add_parser(
        "verify", help="verify allowed and denied workflow assertions"
    )
    verify_parser.add_argument("--workflow", type=Path, required=True)
    verify_parser.add_argument(
        "--evidence", type=Path, required=True, action="append"
    )
    verify_parser.add_argument("--report", type=Path, required=True)
    verify_parser.set_defaults(handler=_command_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except WorkflowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
