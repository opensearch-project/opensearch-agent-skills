from __future__ import annotations

import argparse
import importlib
import io
import json
import socket
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "security"
    / "permission-compiler"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

import permission_compiler.cli as compiler_cli  # noqa: E402
from permission_compiler.cli import (  # noqa: E402
    _compose_probe_url,
    _permission_check_path,
    _positive_timeout,
    _probe_step,
    _read_response_body,
    _ssl_context,
    _validate_probe_url,
    _validate_credentials,
    main,
)
from permission_compiler.core import (
    Evidence,
    WorkflowError,
    compile_role,
    parse_evidence_document,
    parse_missing_privileges,
    validate_workflow,
    verify_workflow,
)


@pytest.fixture(autouse=True)
def stable_public_probe_dns(monkeypatch):
    real_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if host == "search.example.com":
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("8.8.8.8", port),
                )
            ]
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(compiler_cli.socket, "getaddrinfo", getaddrinfo)


def workflow():
    return {
        "name": "reader",
        "role_name": "reader-observed",
        "steps": [
            {
                "id": "search",
                "method": "POST",
                "path": "/logs-*/_search",
                "index_patterns": ["logs-*"],
                "expect": "allow",
            },
            {
                "id": "health",
                "method": "GET",
                "path": "/_cluster/health",
                "index_patterns": [],
                "expect": "allow",
            },
            {
                "id": "delete",
                "method": "DELETE",
                "path": "/logs-2026",
                "index_patterns": ["logs-*"],
                "expect": "deny",
            },
        ],
    }


def test_parse_direct_missing_privileges():
    response = {
        "accessAllowed": False,
        "missingPrivileges": ["indices:data/read/search", "cluster:monitor/health"],
    }
    assert parse_missing_privileges(response) == (
        "cluster:monitor/health",
        "indices:data/read/search",
    )


def test_parse_nested_security_exception_with_bracketed_action():
    response = {
        "error": {
            "root_cause": [
                {
                    "type": "security_exception",
                    "reason": (
                        "no permissions for [indices:data/write/bulk[s]] and User "
                        "[name=a, backend_roles=[], requestedTenant=null]"
                    )
                }
            ]
        }
    }
    assert parse_missing_privileges(response) == ("indices:data/write/bulk[s]",)


def test_parse_multiple_actions_with_nested_commas():
    response = {
        "error": {
            "type": "security_exception",
            "reason": (
                "no permissions for [indices:data/read/search, "
                "indices:data/write/bulk[s,t]] and User [name=a]"
            )
        }
    }
    assert parse_missing_privileges(response) == (
        "indices:data/read/search",
        "indices:data/write/bulk[s,t]",
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("no permissions for [indices:data/read/search", ()),
        (
            "no permissions for [indices:data/read/search]",
            ("indices:data/read/search",),
        ),
    ],
)
def test_reason_parser_handles_bracket_boundary(reason, expected):
    assert (
        parse_missing_privileges({"type": "security_exception", "reason": reason})
        == expected
    )


def test_reason_parser_ignores_reflected_or_untyped_error_text():
    injected = "request contained no permissions for [cluster:admin/*]"
    assert parse_missing_privileges({"type": "security_exception", "reason": injected}) == ()
    assert parse_missing_privileges({"reason": "no permissions for [cluster:admin/*]"}) == ()


def test_malformed_reason_is_reported_as_unresolved_evidence():
    evidence = parse_evidence_document(
        {
            "step_id": "search",
            "response": {
                "type": "security_exception",
                "reason": "no permissions for [indices:data/read/search",
            },
        },
        "malformed.json",
    )
    assert evidence[0].parse_warnings == (
        "malformed no-permissions reason was not parsed",
    )
    _, report = compile_role(workflow(), evidence)
    assert report["parse_warnings"] == [
        {
            "step_id": "search",
            "source": "malformed.json",
            "warning": "malformed no-permissions reason was not parsed",
        }
    ]
    assert report["safe_to_review"] is False


def test_parse_audit_record():
    response = {
        "audit_category": "MISSING_PRIVILEGES",
        "audit_request_privilege": "indices:admin/get",
    }
    assert parse_missing_privileges(response) == ("indices:admin/get",)


def test_empty_permission_is_not_invented():
    response = {
        "error": {
            "type": "security_exception",
            "reason": (
                "no permissions for [] and User "
                "[name=admin, backend_roles=[admin], requestedTenant=null]"
            )
        }
    }
    assert parse_missing_privileges(response) == ()


def test_unexpected_ppl_exception_is_not_treated_as_a_grant():
    response = {
        "error": {
            "reason": (
                "Error occurred in OpenSearch engine: Unexpected exception "
                "cluster:admin/opensearch/ppl"
            )
        }
    }
    assert parse_missing_privileges(response) == ()


def test_workflow_rejects_duplicate_ids():
    document = workflow()
    document["steps"].append(document["steps"][0])
    with pytest.raises(WorkflowError, match="duplicate"):
        validate_workflow(document)


@pytest.mark.parametrize(
    "path",
    ["//evil.example.com/_search", "/_search#fragment"],
)
def test_workflow_rejects_non_root_relative_paths(path):
    document = workflow()
    document["steps"][0]["path"] = path
    with pytest.raises(WorkflowError, match="root-relative"):
        validate_workflow(document)


@pytest.mark.parametrize(
    "path",
    ["/../_search", "/%2e%2e/_search", "/%252e%252e/_search", "/logs\\_search"],
)
def test_workflow_rejects_unsafe_path_segments(path):
    document = workflow()
    document["steps"][0]["path"] = path
    with pytest.raises(WorkflowError, match="unsafe segment"):
        validate_workflow(document)


def test_workflow_rejects_head_body_but_allows_get_body():
    document = workflow()
    document["steps"][0].update({"method": "HEAD", "body": {"query": {}}})
    with pytest.raises(WorkflowError, match="HEAD steps"):
        validate_workflow(document)

    document["steps"][0]["method"] = "GET"
    validate_workflow(document)


def test_compile_partitions_cluster_and_index_actions():
    evidence = [
        Evidence(
            "search", False, ("indices:data/read/search",), "test"
        ),
        Evidence(
            "health", False, ("cluster:monitor/health",), "test"
        ),
    ]
    candidate, report = compile_role(workflow(), evidence)
    role = candidate["reader-observed"]
    assert role["cluster_permissions"] == ["cluster:monitor/health"]
    assert role["index_permissions"][0]["index_patterns"] == ["logs-*"]
    assert role["index_permissions"][0]["allowed_actions"] == [
        "indices:data/read/search"
    ]
    assert report["unobserved_steps"] == ["delete"]
    assert report["permission_evidence"]["indices:data/read/search"] == {
        "steps": ["search"],
        "sources": ["test"],
        "index_patterns": ["logs-*"],
    }


def test_compile_rejects_conflicting_duplicate_evidence_without_unioning():
    evidence = [
        Evidence("search", False, ("indices:data/read/search",), "run-1"),
        Evidence("search", False, ("indices:data/read/msearch",), "run-2"),
    ]

    candidate, report = compile_role(workflow(), evidence)

    role = candidate["reader-observed"]
    assert role["cluster_permissions"] == []
    assert role["index_permissions"] == []
    assert report["conflicting_evidence_steps"] == ["search"]
    assert report["safe_to_review"] is False


def test_compile_accepts_matching_duplicate_evidence_and_tracks_sources():
    evidence = [
        Evidence("search", False, ("indices:data/read/search",), "run-1"),
        Evidence("search", False, ("indices:data/read/search",), "run-2"),
    ]

    candidate, report = compile_role(workflow(), evidence)

    role = candidate["reader-observed"]
    assert role["index_permissions"][0]["allowed_actions"] == [
        "indices:data/read/search"
    ]
    assert report["conflicting_evidence_steps"] == []
    assert report["permission_evidence"]["indices:data/read/search"]["sources"] == [
        "run-1",
        "run-2",
    ]


def test_negative_evidence_never_creates_grant():
    evidence = [
        Evidence("delete", False, ("indices:admin/delete",), "test")
    ]
    candidate, _ = compile_role(workflow(), evidence)
    assert candidate["reader-observed"]["index_permissions"] == []


def test_allowed_negative_probe_is_violation():
    evidence = [Evidence("delete", True, (), "test")]
    _, report = compile_role(workflow(), evidence)
    assert report["negative_probe_violations"] == ["delete"]
    assert report["safe_to_review"] is False


def test_unresolved_negative_probe_stops_review():
    evidence = [Evidence("delete", None, (), "test")]
    _, report = compile_role(workflow(), evidence)
    assert report["unresolved_negative_probes"] == ["delete"]
    assert report["safe_to_review"] is False


@pytest.mark.parametrize("allowed", [True, False, None])
def test_positive_probe_without_derived_privileges_stops_review(allowed):
    evidence = [Evidence("search", allowed, (), "test")]
    candidate, report = compile_role(workflow(), evidence)
    assert candidate["reader-observed"]["index_permissions"] == []
    assert report["non_deriving_positive_probes"] == ["search"]
    assert report["safe_to_review"] is False


def test_unscoped_index_permission_stops_review():
    document = workflow()
    document["steps"][0]["index_patterns"] = []
    evidence = [
        Evidence("search", False, ("indices:data/read/search",), "test")
    ]
    candidate, report = compile_role(document, evidence)
    assert candidate["reader-observed"]["index_permissions"] == []
    assert report["unscoped_index_actions"]
    assert report["safe_to_review"] is False


def test_unknown_evidence_step_stops_review():
    evidence = [Evidence("not-in-workflow", False, ("cluster:monitor/state",), "test")]
    _, report = compile_role(workflow(), evidence)
    assert report["unknown_evidence_steps"] == ["not-in-workflow"]
    assert report["safe_to_review"] is False


def test_parse_evidence_document_requires_step_id():
    with pytest.raises(WorkflowError, match="step_id"):
        parse_evidence_document({"response": {"accessAllowed": True}})


def test_evidence_requires_explicit_response_wrapper():
    with pytest.raises(WorkflowError, match="response is required"):
        parse_evidence_document(
        {
            "step_id": "search",
            "metadata": {"accessAllowed": True},
            "status": 200,
        }
        )


def test_verify_workflow_passes_positive_and_negative_contract():
    evidence = [
        Evidence("search", True, (), "after"),
        Evidence("health", True, (), "after"),
        Evidence("delete", False, ("indices:admin/delete",), "after"),
    ]
    report = verify_workflow(workflow(), evidence)
    assert report["passed"] is True
    assert {item["outcome"] for item in report["results"]} == {"passed"}


def test_verify_workflow_rejects_allowed_negative_probe():
    evidence = [
        Evidence("search", True, (), "after"),
        Evidence("health", True, (), "after"),
        Evidence("delete", True, (), "after"),
    ]
    report = verify_workflow(workflow(), evidence)
    assert report["passed"] is False
    assert report["negative_probe_violations"] == [{"step_id": "delete"}]


def test_verify_workflow_rejects_conflicting_observations():
    evidence = [
        Evidence("search", True, (), "run-1"),
        Evidence("search", False, ("indices:data/read/search",), "run-2"),
        Evidence("health", True, (), "after"),
        Evidence("delete", False, ("indices:admin/delete",), "after"),
    ]
    report = verify_workflow(workflow(), evidence)
    assert report["passed"] is False
    assert report["conflicting_steps"] == ["search"]


def test_permission_check_path_preserves_existing_query():
    path = _permission_check_path("/logs/_search?preference=local")
    query = parse_qs(urlsplit(path).query)
    assert query == {
        "perform_permission_check": ["true"],
        "preference": ["local"],
    }


def test_permission_check_path_preserves_duplicate_query_parameters():
    path = _permission_check_path(
        "/logs/_search?filter_path=hits.total&filter_path=took&perform_permission_check=false"
    )
    query = parse_qs(urlsplit(path).query)
    assert query == {
        "filter_path": ["hits.total", "took"],
        "perform_permission_check": ["true"],
    }


def test_permission_check_path_rejects_authority_and_fragment():
    with pytest.raises(WorkflowError, match="root-relative"):
        _permission_check_path("//evil.example.com/_search")
    with pytest.raises(WorkflowError, match="root-relative"):
        _permission_check_path("/_search#fragment")


@pytest.mark.parametrize(
    "path",
    ["/../_search", "/%2e%2e/_search", "/%252e%252e/_search", "/logs\\_search"],
)
def test_permission_check_path_rejects_unsafe_segments(path):
    with pytest.raises(WorkflowError, match="unsafe segment"):
        _permission_check_path(path)


def test_composed_probe_url_preserves_prefix_and_origin():
    url = _compose_probe_url(
        "https://search.example.com/opensearch",
        "/logs/_search?preference=local",
    )
    assert url.startswith("https://search.example.com/opensearch/logs/_search?")
    assert urlsplit(url).hostname == "search.example.com"
    assert urlsplit(url).path.startswith("/opensearch/")


def test_composed_probe_url_defends_single_slash_boundary(monkeypatch):
    monkeypatch.setattr(
        compiler_cli,
        "_permission_check_path",
        lambda path: "//evil.example.com/_search",
    )
    with pytest.raises(WorkflowError, match="exactly one slash"):
        _compose_probe_url("https://search.example.com", "/_search")


def test_composed_probe_url_rejects_encoded_base_path_traversal():
    with pytest.raises(WorkflowError, match="unsafe segment"):
        _compose_probe_url("https://search.example.com/api%2f..", "/_search")


def test_http_status_alone_does_not_infer_permission_outcome():
    evidence = parse_evidence_document(
        {"step_id": "search", "response": {"status": 200}}
    )
    assert evidence[0].allowed is None


def test_nested_access_allowed_does_not_decide_step_outcome():
    evidence = parse_evidence_document(
        {
            "step_id": "search",
            "response": {
                "checks": [
                    {"accessAllowed": True},
                    {"accessAllowed": False},
                ]
            },
        }
    )
    assert evidence[0].allowed is None


def test_missing_privileges_are_denied_without_http_status_inference():
    evidence = parse_evidence_document(
        {
            "step_id": "search",
            "response": {"missingPrivileges": ["indices:data/read/search"]},
        }
    )
    assert evidence[0].allowed is False


def test_main_module_can_be_imported_without_running_cli():
    module = importlib.import_module("permission_compiler.__main__")
    assert module.main is main


def test_ssl_context_always_verifies_hostname():
    context = _ssl_context(None)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_probe_url_requires_https_except_for_loopback():
    _validate_probe_url("https://search.example.com/opensearch")
    _validate_probe_url("http://127.0.0.1:9200")
    _validate_probe_url("http://127.0.0.2:9200")
    with pytest.raises(WorkflowError, match="non-HTTPS"):
        _validate_probe_url("http://search.example.com:9200")
    with pytest.raises(WorkflowError, match="non-HTTPS"):
        _validate_probe_url("http://localhost:9200")


def test_probe_url_rejects_query_and_fragment():
    with pytest.raises(WorkflowError, match="query or fragment"):
        _validate_probe_url("https://search.example.com?pretty=true")


def test_probe_url_requires_host_and_rejects_userinfo():
    with pytest.raises(WorkflowError, match="include a host"):
        _validate_probe_url("https:///opensearch")
    with pytest.raises(WorkflowError, match="user information"):
        _validate_probe_url("https://user@example.com")


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data",
        "https://[fe80::1]/",
        "https://0.0.0.0/",
        "https://metadata.google.internal/",
    ],
)
def test_probe_url_rejects_metadata_and_special_use_targets(url):
    with pytest.raises(WorkflowError, match="refuses"):
        _validate_probe_url(url)


def test_probe_url_rejects_hostname_resolving_to_private_address(monkeypatch):
    monkeypatch.setattr(
        compiler_cli.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("10.0.0.5", 443),
            )
        ],
    )
    with pytest.raises(WorkflowError, match="private or loopback"):
        _validate_probe_url("https://cluster.internal")


def test_probe_url_allows_explicit_private_https_target(monkeypatch):
    monkeypatch.setattr(
        compiler_cli.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("10.0.0.5", 443),
            )
        ],
    )
    _validate_probe_url("https://cluster.internal", allow_private_target=True)


def test_probe_url_private_opt_in_never_allows_metadata_resolution(monkeypatch):
    monkeypatch.setattr(
        compiler_cli.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("169.254.169.254", 443),
            )
        ],
    )
    with pytest.raises(WorkflowError, match="link-local"):
        _validate_probe_url(
            "https://attacker-controlled.example", allow_private_target=True
        )


def test_pinned_https_connection_preserves_tls_hostname(monkeypatch):
    raw_socket = object()
    wrapped_socket = object()
    observed = {}

    class Context:
        def wrap_socket(self, sock, server_hostname):
            observed["raw_socket"] = sock
            observed["server_hostname"] = server_hostname
            return wrapped_socket

    def connect(address, port, timeout):
        observed["address"] = address
        observed["port"] = port
        observed["timeout"] = timeout
        return raw_socket

    monkeypatch.setattr(compiler_cli, "_connect_pinned_address", connect)
    address = compiler_cli.ipaddress.ip_address("8.8.8.8")
    connection = compiler_cli._PinnedHTTPSConnection(
        "search.example.com", 443, address, 4.0, Context()
    )

    connection.connect()

    assert observed == {
        "address": address,
        "port": 443,
        "timeout": 4.0,
        "raw_socket": raw_socket,
        "server_hostname": "search.example.com",
    }
    assert connection.host == "search.example.com"
    assert connection.sock is wrapped_socket


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("admin:other", "secret"),
        ("admin\n", "secret"),
        ("admin", "secret\rvalue"),
    ],
)
def test_credentials_reject_ambiguous_basic_auth_values(username, password):
    with pytest.raises(WorkflowError):
        _validate_credentials(username, password)


def test_probe_refuses_redirects_before_replaying_credentials():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                }
            )
            if self.path.startswith("/start"):
                self.send_response(302)
                self.send_header(
                    "Location", f"http://127.0.0.1:{self.server.server_port}/target"
                )
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _probe_step(
            base_url=f"http://127.0.0.1:{server.server_port}",
            step={"path": "/start", "method": "GET"},
            username="test-user",
            password="test-password",
            ca_cert=None,
            timeout=2,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response["status"] == 302
    assert response["response_error"] == "probe refuses redirect responses"
    assert len(requests) == 1
    assert requests[0]["authorization"].startswith("Basic ")


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf"])
def test_probe_timeout_must_be_positive_and_finite(value):
    with pytest.raises(argparse.ArgumentTypeError, match="positive finite"):
        _positive_timeout(value)


def test_permission_response_body_is_bounded():
    assert _read_response_body(io.BytesIO(b"{}")) == "{}"
    with pytest.raises(WorkflowError, match="exceeds"):
        _read_response_body(io.BytesIO(b"x" * (1024 * 1024 + 1)))


def test_probe_connection_failure_returns_nonzero_and_keeps_evidence(
    tmp_path, monkeypatch
):
    workflow_path = tmp_path / "workflow.json"
    evidence_path = tmp_path / "evidence.json"
    workflow_path.write_text(json.dumps(workflow()), encoding="utf-8")
    monkeypatch.setenv("OPENSEARCH_USERNAME", "test-user")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "test-password")
    monkeypatch.setattr(
        compiler_cli,
        "_probe_step",
        lambda **kwargs: {"connection_error": "connection refused", "status": 0},
    )

    exit_code = main(
        [
            "probe",
            "--workflow",
            str(workflow_path),
            "--output",
            str(evidence_path),
            "--url",
            "https://search.example.com/opensearch",
        ]
    )

    assert exit_code == 2
    assert len(json.loads(evidence_path.read_text(encoding="utf-8"))) == 3


def test_probe_response_failure_returns_nonzero_and_keeps_evidence(
    tmp_path, monkeypatch
):
    workflow_path = tmp_path / "workflow.json"
    evidence_path = tmp_path / "evidence.json"
    workflow_path.write_text(json.dumps(workflow()), encoding="utf-8")
    monkeypatch.setenv("OPENSEARCH_USERNAME", "test-user")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "test-password")
    monkeypatch.setattr(
        compiler_cli,
        "_probe_step",
        lambda **kwargs: {"response_error": "response too large", "status": 500},
    )

    exit_code = main(
        [
            "probe",
            "--workflow",
            str(workflow_path),
            "--output",
            str(evidence_path),
            "--url",
            "https://search.example.com/opensearch",
        ]
    )

    assert exit_code == 2
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert len(evidence) == 3
    assert all("response_error" in item["response"] for item in evidence)


def test_probe_is_permission_check_and_does_not_persist_credentials(
    tmp_path, monkeypatch
):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("Authorization"),
                    "body": self.rfile.read(length).decode("utf-8"),
                }
            )
            payload = json.dumps(
                {
                    "accessAllowed": False,
                    "missingPrivileges": ["indices:data/read/search"],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        workflow_path = tmp_path / "workflow.json"
        evidence_path = tmp_path / "evidence.json"
        workflow_path.write_text(
            json.dumps(
                {
                    "name": "query",
                    "steps": [
                        {
                            "id": "search",
                            "method": "POST",
                            "path": "/logs/_search",
                            "body": {"query": {"match_all": {}}},
                            "index_patterns": ["logs"],
                            "expect": "allow",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("OPENSEARCH_USERNAME", "test-user")
        monkeypatch.setenv("OPENSEARCH_PASSWORD", "correct-horse")
        exit_code = main(
            [
                "probe",
                "--workflow",
                str(workflow_path),
                "--output",
                str(evidence_path),
                "--url",
                f"http://127.0.0.1:{server.server_port}",
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert exit_code == 0
    assert len(requests) == 1
    query = parse_qs(urlsplit(requests[0]["path"]).query)
    assert query["perform_permission_check"] == ["true"]
    assert requests[0]["authorization"].startswith("Basic ")
    persisted = evidence_path.read_text(encoding="utf-8")
    assert "correct-horse" not in persisted
    assert "test-user" not in persisted
    assert "Authorization" not in persisted
