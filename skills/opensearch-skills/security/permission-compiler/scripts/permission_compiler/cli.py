"""Command-line interface for the OpenSearch Permission Compiler."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .core import (
    WorkflowError,
    compile_role,
    parse_evidence_document,
    validate_workflow,
    verify_workflow,
)


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


def _ssl_context(
    ca_cert: str | None, skip_hostname_verification: bool = False
) -> ssl.SSLContext:
    if skip_hostname_verification and not ca_cert:
        raise WorkflowError(
            "--skip-hostname-verification requires --ca-cert so certificate "
            "chain verification remains enabled"
        )
    context = (
        ssl.create_default_context(cafile=ca_cert)
        if ca_cert
        else ssl.create_default_context()
    )
    if skip_hostname_verification:
        context.check_hostname = False
    return context


def _validate_probe_url(base_url: str) -> None:
    parts = urlsplit(base_url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    loopback_hosts = {"127.0.0.1", "localhost", "::1"}
    if not parts.netloc or not host:
        raise WorkflowError("probe base URL must include a host")
    if parts.username is not None or parts.password is not None:
        raise WorkflowError("probe base URL must not contain user information")
    try:
        parts.port
    except ValueError as exc:
        raise WorkflowError("probe base URL contains an invalid port") from exc
    if scheme != "https" and not (scheme == "http" and host in loopback_hosts):
        raise WorkflowError(
            "probe refuses to send credentials over a non-HTTPS URL; "
            "plaintext HTTP is allowed only for loopback development clusters"
        )
    if parts.query or parts.fragment:
        raise WorkflowError("probe base URL must not contain a query or fragment")


def _compose_probe_url(base_url: str, path: str) -> str:
    _validate_probe_url(base_url)
    permission_path = _permission_check_path(path)
    if not permission_path.startswith("/") or permission_path.startswith("//"):
        raise WorkflowError("workflow step path must begin with exactly one slash")
    url = base_url.rstrip("/") + permission_path
    base_parts = urlsplit(base_url)
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
    base_path = base_parts.path.rstrip("/")
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


def _probe_step(
    base_url: str,
    step: dict[str, Any],
    username: str,
    password: str,
    ca_cert: str | None,
    skip_hostname_verification: bool,
    timeout: float,
) -> dict[str, Any]:
    url = _compose_probe_url(base_url, step["path"])
    body = step.get("body")
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(url, data=data, method=str(step.get("method", "GET")).upper())
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(
            request,
            context=_ssl_context(ca_cert, skip_hostname_verification),
            timeout=timeout,
        ) as response:
            payload = response.read().decode("utf-8")
            parsed = json.loads(payload) if payload else {}
            if isinstance(parsed, dict):
                parsed.setdefault("status", response.status)
            return parsed
    except HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error_body": payload}
        if isinstance(parsed, dict):
            parsed.setdefault("status", exc.code)
        return parsed
    except URLError as exc:
        return {"connection_error": str(exc.reason), "status": 0}


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
    _validate_probe_url(base_url)
    evidence = []
    connection_failures = []
    for step in workflow["steps"]:
        response = _probe_step(
            base_url=base_url,
            step=step,
            username=username,
            password=password,
            ca_cert=args.ca_cert,
            skip_hostname_verification=args.skip_hostname_verification,
            timeout=args.timeout,
        )
        evidence.append({"step_id": step["id"], "response": response})
        if "connection_error" in response:
            connection_failures.append(step["id"])
    _write_json(args.output, evidence)
    print(f"Wrote permission-check evidence: {args.output}")
    if connection_failures:
        print(
            "error: probe connection failed for steps: "
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
        "--skip-hostname-verification",
        action="store_true",
        help=(
            "verify the certificate chain but skip hostname matching; use only "
            "with disposable demo certificates and --ca-cert"
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
