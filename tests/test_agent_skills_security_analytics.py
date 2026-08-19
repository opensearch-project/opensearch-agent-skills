"""Tests for the security-analytics-detection-engineering skill CLI.

No cluster required: HTTP is stubbed by monkeypatching http_request.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills" / "opensearch-skills" / "security"
    / "security-analytics-detection-engineering" / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

import security_analytics as sa  # noqa: E402

FIXTURES = _SCRIPTS_DIR.parent / "assets" / "fixtures"


def _config(url="https://example.com:9200", password=""):
    return {
        "url": url,
        "username": "admin" if password else "",
        "password": password,
        "auth_header": "Basic c2VjcmV0" if password else None,
        "verify_tls": True,
        "timeout": 5,
    }


def _route(routes):
    """Build a fake http_request from {(method, path_prefix): (status, body)}."""
    calls = []

    def fake(config, method, path, body=None, content_type="application/json"):
        calls.append((method, path, body))
        for (m, prefix), resp in routes.items():
            if m == method and path.startswith(prefix):
                return resp
        raise AssertionError(f"Unexpected request: {method} {path}")

    fake.calls = calls
    return fake


_ROOT_OK = (200, {"version": {"number": "2.19.1", "distribution": "opensearch"}})
_SEMANTIC_404 = (404, {"error": {"reason": "No detectors found "}, "status": 404})


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

def test_preflight_success(monkeypatch):
    fake = _route({
        ("GET", "/"): _ROOT_OK,
        ("POST", f"{sa.SA_BASE}/rules/_search"): (200, {"hits": {}}),
        ("POST", f"{sa.SA_BASE}/detectors/_search"): (200, {"hits": {}}),
        ("GET", f"{sa.SA_BASE}/findings/_search"): _SEMANTIC_404,
    })
    monkeypatch.setattr(sa, "http_request", fake)
    code, result = sa.cmd_preflight(_config(), SimpleNamespace())
    assert code == 0
    assert result["opensearch_version"] == "2.19.1"
    assert result["security_analytics_available"] is True
    assert result["apis"]["findings"]["available"] is True  # semantic 404 counts


def test_preflight_missing_security_analytics(monkeypatch):
    fake = _route({
        ("GET", "/"): _ROOT_OK,
        ("POST", f"{sa.SA_BASE}/rules/_search"): (
            400, {"error": "no handler found for uri [/_plugins/_security_analytics/rules/_search]"}
        ),
        ("POST", f"{sa.SA_BASE}/detectors/_search"): (400, {"error": "no handler found"}),
        ("GET", f"{sa.SA_BASE}/findings/_search"): (400, {"error": "no handler found"}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    code, result = sa.cmd_preflight(_config(), SimpleNamespace())
    assert code != 0
    assert result["security_analytics_available"] is False


def test_preflight_auth_failure(monkeypatch):
    fake = _route({("GET", "/"): (401, {"error": "Unauthorized"})})
    monkeypatch.setattr(sa, "http_request", fake)
    with pytest.raises(sa.SAError) as e:
        sa.cmd_preflight(_config(password="hunter2"), SimpleNamespace())
    assert e.value.status == 401
    assert "hunter2" not in str(e.value)


# ---------------------------------------------------------------------------
# response parsing
# ---------------------------------------------------------------------------

def test_parse_rule_response():
    parsed = sa.parse_rule_response(201, {
        "_id": "rule-abc", "_version": 1,
        "rule": {"category": "windows", "title": "T", "log_source": "process_creation"},
    })
    assert parsed["rule_id"] == "rule-abc"
    assert parsed["category"] == "windows"


def test_parse_rule_response_failure():
    with pytest.raises(sa.SAError) as e:
        sa.parse_rule_response(400, {"error": "Sigma rule must be non-empty"})
    assert e.value.status == 400


def test_parse_detector_response():
    parsed = sa.parse_detector_response(201, {
        "_id": "det-xyz",
        "detector": {"enabled": True, "enabled_time": "t", "name": "n",
                     "schedule": {"period": {"interval": 1, "unit": "MINUTES"}}},
    })
    assert parsed["detector_id"] == "det-xyz"
    assert parsed["enabled"] is True
    assert parsed["schedule"]["period"]["interval"] == 1


def test_parse_detector_response_failure():
    with pytest.raises(sa.SAError):
        sa.parse_detector_response(500, "internal error")


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def test_manifest_roundtrip(tmp_path):
    path = str(tmp_path / "manifest.json")
    manifest = sa.new_manifest(_config(), "sa-de-test-x")
    assert manifest["run_id"].startswith(sa.TEST_PREFIX)
    assert manifest["endpoint"] == "https://example.com:9200"
    sa.record_resource(manifest, "rule", "rule-1")
    sa.save_manifest(manifest, path)
    loaded = sa.load_manifest(path)
    assert loaded == manifest
    assert loaded["resources_created"][0]["kind"] == "rule"


def test_load_manifest_missing(tmp_path):
    with pytest.raises(sa.SAError):
        sa.load_manifest(str(tmp_path / "nope.json"))


def test_manifest_endpoint_strips_userinfo():
    manifest = sa.new_manifest(_config(url="https://admin:secret@example.com:9200"), "i")
    assert "secret" not in manifest["endpoint"]


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

def _cleanup_args(force=False):
    return SimpleNamespace(force=force)


def test_cleanup_refuses_unrecorded_resources(monkeypatch, tmp_path):
    """Empty manifest -> no delete calls at all, index explicitly skipped."""
    fake = _route({})
    monkeypatch.setattr(sa, "http_request", fake)
    manifest = sa.new_manifest(_config(), "user-index")
    manifest["index"] = "user-index"  # exists but NOT created by run
    path = str(tmp_path / "m.json")
    code, result = sa.cmd_cleanup(_config(), _cleanup_args(), manifest, path)
    assert code == 0
    assert fake.calls == []
    kinds = {d["kind"]: d["status"] for d in result["details"]}
    assert kinds["index"] == "skipped"
    assert kinds["detector"] == "not_created_by_run"


def test_cleanup_normal(monkeypatch, tmp_path):
    fake = _route({
        ("DELETE", f"{sa.SA_BASE}/detectors/det-1"): (200, {}),
        ("DELETE", f"{sa.SA_BASE}/rules/rule-1"): (200, {}),
        ("DELETE", "/sa-de-test-i"): (200, {"acknowledged": True}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    manifest = sa.new_manifest(_config(), "sa-de-test-i")
    manifest.update(index="sa-de-test-i", index_created_by_run=True,
                    rule_id="rule-1", detector_id="det-1")
    code, result = sa.cmd_cleanup(_config(), _cleanup_args(), manifest, str(tmp_path / "m.json"))
    assert code == 0
    assert result["status"] == "complete"
    assert all(d["status"] == "deleted" for d in result["details"])


def test_cleanup_idempotent_on_absent_resources(monkeypatch, tmp_path):
    fake = _route({
        ("DELETE", f"{sa.SA_BASE}/detectors/det-1"): (404, {}),
        ("DELETE", f"{sa.SA_BASE}/rules/rule-1"): (404, {}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    manifest = sa.new_manifest(_config(), None)
    manifest.update(rule_id="rule-1", detector_id="det-1")
    code, result = sa.cmd_cleanup(_config(), _cleanup_args(), manifest, str(tmp_path / "m.json"))
    assert code == 0
    statuses = [d["status"] for d in result["details"] if d["kind"] in ("rule", "detector")]
    assert statuses == ["already_absent", "already_absent"]


def test_forced_cleanup_requires_flag(monkeypatch, tmp_path):
    fake = _route({
        ("DELETE", f"{sa.SA_BASE}/rules/rule-1?forced=true"): (200, {}),
        ("DELETE", f"{sa.SA_BASE}/rules/rule-1"): (500, {"error": "rule in use"}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    manifest = sa.new_manifest(_config(), None)
    manifest["rule_id"] = "rule-1"

    code, result = sa.cmd_cleanup(_config(), _cleanup_args(force=False), manifest,
                                  str(tmp_path / "m1.json"))
    assert code != 0
    rule_detail = next(d for d in result["details"] if d["kind"] == "rule")
    assert rule_detail["status"] == "failed"
    assert "forced" not in str(fake.calls)

    code, result = sa.cmd_cleanup(_config(), _cleanup_args(force=True), manifest,
                                  str(tmp_path / "m2.json"))
    assert code == 0
    rule_detail = next(d for d in result["details"] if d["kind"] == "rule")
    assert rule_detail["status"] == "force_deleted"


# ---------------------------------------------------------------------------
# rule / index creation guards
# ---------------------------------------------------------------------------

def test_create_rule_dry_run_makes_no_requests(monkeypatch, tmp_path):
    fake = _route({})
    monkeypatch.setattr(sa, "http_request", fake)
    manifest = sa.new_manifest(_config(), "i")
    args = SimpleNamespace(sigma_file=str(FIXTURES / "sigma-encoded-powershell.yml"),
                           category="windows", apply=False)
    code, result = sa.cmd_create_rule(_config(), args, manifest, str(tmp_path / "m.json"))
    assert code == 0
    assert result["dry_run"] is True
    assert fake.calls == []
    assert "EventID" in result["sigma_candidate_fields"]
    assert "CommandLine" in result["sigma_candidate_fields"]


def test_create_rule_refuses_second_rule(monkeypatch, tmp_path):
    manifest = sa.new_manifest(_config(), "i")
    manifest["rule_id"] = "existing"
    args = SimpleNamespace(sigma_file=str(FIXTURES / "sigma-encoded-powershell.yml"),
                           category="windows", apply=True)
    with pytest.raises(sa.SAError, match="already created rule"):
        sa.cmd_create_rule(_config(), args, manifest, str(tmp_path / "m.json"))


def test_create_index_requires_test_prefix(monkeypatch, tmp_path):
    manifest = sa.new_manifest(_config(), None)
    args = SimpleNamespace(index="production-logs",
                           mapping_file=str(FIXTURES / "test-index-mapping.json"))
    with pytest.raises(sa.SAError, match="test prefix"):
        sa.cmd_create_index(_config(), args, manifest, str(tmp_path / "m.json"))


def test_validate_resource_name_rejects_injection():
    for bad in ("../other", "a index", "UPPER", "", "-lead", "a/b?x=1"):
        with pytest.raises(sa.SAError):
            sa.validate_resource_name(bad, "index")
    sa.validate_resource_name("sa-de-test-abc123", "index")


# ---------------------------------------------------------------------------
# verify: polling, attribution, timeout
# ---------------------------------------------------------------------------

def _verify_manifest():
    manifest = sa.new_manifest(_config(), "sa-de-test-i")
    manifest.update(index="sa-de-test-i", index_created_by_run=True,
                    rule_id="rule-1", detector_id="det-1",
                    detector_created_at="2026-08-03T00:00:00.000000Z")
    return manifest


def _verify_args(timeout=30):
    return SimpleNamespace(
        positive_fixture=str(FIXTURES / "positive-event.json"),
        negative_fixture=str(FIXTURES / "negative-event.json"),
        timeout=timeout, poll_interval=1, schedule_minutes=1,
    )


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def _finding(doc_id, rule_id="rule-1"):
    return {
        "id": "finding-1", "detectorId": "det-1", "related_doc_ids": [doc_id],
        "queries": [{"id": rule_id, "query": "(winlog.event_id: 1)"}],
    }


def test_verify_positive_attribution(monkeypatch, tmp_path):
    manifest = _verify_manifest()
    state = {"positive_id": None}

    def fake(config, method, path, body=None, content_type="application/json"):
        if method == "PUT" and "/_doc/" in path:
            doc_id = path.split("/_doc/")[1].split("?")[0]
            if doc_id.endswith("-positive"):
                state["positive_id"] = doc_id
            return 201, {"_id": doc_id, "_seq_no": 0 if doc_id.endswith("-positive") else 1}
        if method == "GET" and "/findings/_search" in path:
            return 200, {"total_findings": 1, "findings": [_finding(state["positive_id"])]}
        raise AssertionError(f"Unexpected: {method} {path}")

    monkeypatch.setattr(sa, "http_request", fake)
    clock = _FakeClock()
    code, result = sa.cmd_verify(_config(), _verify_args(), manifest,
                                 str(tmp_path / "m.json"), sleep=clock.sleep, clock=clock)
    assert code == 0
    assert result["verified"] is True
    assert result["positive"]["finding_id"] == "finding-1"
    assert "rule-1" in result["positive"]["rule_ids_in_finding"]
    assert result["negative"]["findings_attributed"] == 0
    assert result["eligibility"]["both_indexed_after_detector_creation"] is True


def test_verify_detects_negative_control_finding(monkeypatch, tmp_path):
    """A finding attributed to the negative fixture must fail verification."""
    manifest = _verify_manifest()
    ids = {}

    def fake(config, method, path, body=None, content_type="application/json"):
        if method == "PUT" and "/_doc/" in path:
            doc_id = path.split("/_doc/")[1].split("?")[0]
            ids["negative" if doc_id.endswith("-negative") else "positive"] = doc_id
            return 201, {"_id": doc_id, "_seq_no": len(ids)}
        if method == "GET" and "/findings/_search" in path:
            findings = [_finding(ids["positive"]), _finding(ids["negative"])]
            return 200, {"total_findings": 2, "findings": findings}
        raise AssertionError(f"Unexpected: {method} {path}")

    monkeypatch.setattr(sa, "http_request", fake)
    clock = _FakeClock()
    code, result = sa.cmd_verify(_config(), _verify_args(), manifest,
                                 str(tmp_path / "m.json"), sleep=clock.sleep, clock=clock)
    assert code != 0
    assert result["verified"] is False
    assert result["negative"]["findings_attributed"] == 1


def test_verify_bounded_timeout(monkeypatch, tmp_path):
    """Findings never arrive -> bounded poll count, structured timeout result."""
    manifest = _verify_manifest()
    poll_count = {"n": 0}

    def fake(config, method, path, body=None, content_type="application/json"):
        if method == "PUT" and "/_doc/" in path:
            return 201, {"_seq_no": 1}
        if method == "GET" and "/findings/_search" in path:
            poll_count["n"] += 1
            return 200, {"total_findings": 0, "findings": []}
        raise AssertionError(f"Unexpected: {method} {path}")

    monkeypatch.setattr(sa, "http_request", fake)
    clock = _FakeClock()
    code, result = sa.cmd_verify(_config(), _verify_args(timeout=10), manifest,
                                 str(tmp_path / "m.json"), sleep=clock.sleep, clock=clock)
    assert code != 0
    assert result["verified"] is False
    assert "10s" in result["reason"]
    assert poll_count["n"] <= 11


def test_verify_requires_detector(monkeypatch, tmp_path):
    manifest = sa.new_manifest(_config(), "sa-de-test-i")
    with pytest.raises(sa.SAError, match="rule_id, detector_id and index"):
        sa.cmd_verify(_config(), _verify_args(), manifest, str(tmp_path / "m.json"))


def test_match_findings_requires_both_keys():
    findings = [
        {"related_doc_ids": ["doc-1"], "queries": [{"id": "other-rule"}]},
        {"related_doc_ids": ["other-doc"], "queries": [{"id": "rule-1"}]},
        {"related_doc_ids": ["doc-1"], "queries": [{"id": "rule-1"}]},
    ]
    assert len(sa.match_findings(findings, "rule-1", "doc-1")) == 1


# ---------------------------------------------------------------------------
# secrets and structured errors
# ---------------------------------------------------------------------------

def test_redact_removes_secrets():
    config = _config(password="s3cr3t-pw")
    config["auth_header"] = "Basic QWxhZGRpbjpvcGVuc2VzYW1l"
    msg = "auth failed: s3cr3t-pw header Basic QWxhZGRpbjpvcGVuc2VzYW1l"
    out = sa.redact(msg, config)
    assert "s3cr3t-pw" not in out
    assert "QWxhZGRpbjpvcGVuc2VzYW1l" not in out
    assert "***REDACTED***" in out


def test_structured_error_output_and_exit_code(monkeypatch, capsys):
    monkeypatch.delenv("OPENSEARCH_URL", raising=False)
    code = sa.main(["preflight"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] is True
    assert "OPENSEARCH_URL" in payload["message"]


def test_semantic_findings_404_detection():
    assert sa.is_semantic_findings_404(404, {"error": {"reason": "No detectors found "}})
    assert not sa.is_semantic_findings_404(404, {"error": "no handler found for uri"})
    assert not sa.is_semantic_findings_404(200, {})


def test_extract_sigma_fields():
    sigma = (FIXTURES / "sigma-encoded-powershell.yml").read_text()
    fields = sa.extract_sigma_fields(sigma)
    assert fields == ["EventID", "CommandLine"]
