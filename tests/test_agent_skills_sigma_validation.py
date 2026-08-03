"""Slice 2 tests: guarded Sigma authoring, deterministic validation, and
evidence-state transitions for the security-analytics-detection-engineering
skill. No cluster required: HTTP is stubbed by monkeypatching http_request.
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
import sigma_validation as sv  # noqa: E402

FIXTURES = _SCRIPTS_DIR.parent / "assets" / "fixtures"

FIELDS = {"EventID", "CommandLine", "Image", "@timestamp", "test_case_id", "run_id"}

MINIMAL_RULE = """\
title: Encoded PowerShell execution
id: 6f867f60-2f14-4c8d-9c0e-6d4f6c6d0001
status: test
logsource:
  product: windows
  category: process_creation
detection:
  selection:
    EventID: 1
    CommandLine|contains: ' -EncodedCommand '
  condition: selection
level: high
"""


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
    calls = []

    def fake(config, method, path, body=None, content_type="application/json"):
        calls.append((method, path, body))
        for (m, prefix), resp in routes.items():
            if m == method and path.startswith(prefix):
                return resp
        raise AssertionError(f"Unexpected request: {method} {path}")

    fake.calls = calls
    return fake


def _validate(rule_text=MINIMAL_RULE, log_type="windows", fields=FIELDS, **kw):
    return sv.validate_sigma(rule_text, log_type=log_type,
                             resolvable_fields=fields, **kw)


# ---------------------------------------------------------------------------
# validate_sigma: the supported subset
# ---------------------------------------------------------------------------

def test_valid_minimal_rule_is_schema_valid():
    report = _validate()
    assert report["valid"] is True
    assert report["evidence_state"] == "SCHEMA_VALID"
    assert report["unresolved_fields"] == []
    assert set(report["resolved_fields"]) == {"EventID", "CommandLine"}
    assert "modifier:contains" in report["supported_constructs_used"]


def test_malformed_yaml_is_blocking():
    report = _validate("title: [unclosed")
    assert report["valid"] is False
    assert any("YAML parse error" in e for e in report["blocking_errors"])


def test_missing_required_keys():
    report = _validate("title: T\n")
    assert report["valid"] is False
    joined = " ".join(report["blocking_errors"])
    assert "logsource" in joined and "detection" in joined


def test_empty_title_is_blocking():
    report = _validate(MINIMAL_RULE.replace(
        "title: Encoded PowerShell execution", "title: ''"))
    assert any("title" in e for e in report["blocking_errors"])


def test_undefined_condition_selection():
    report = _validate(MINIMAL_RULE.replace(
        "condition: selection", "condition: selection and other"))
    assert report["valid"] is False
    assert any("undefined selection 'other'" in e for e in report["blocking_errors"])


def test_condition_wildcard_matches_defined_selections():
    rule = MINIMAL_RULE.replace("condition: selection", "condition: all of selection*")
    assert _validate(rule)["valid"] is True


def test_unsupported_field_modifier():
    report = _validate(MINIMAL_RULE.replace("CommandLine|contains",
                                            "CommandLine|utf16le"))
    assert report["valid"] is False
    assert any("utf16le" in e for e in report["blocking_errors"])


def test_unresolved_index_field_blocks_schema_valid():
    report = _validate(fields={"EventID", "@timestamp"})
    assert report["valid"] is False
    assert report["unresolved_fields"] == ["CommandLine"]
    assert report["evidence_state"] == "DRAFT"


def test_explicit_alias_or_fixture_field_resolves():
    report = _validate(fields={"EventID"}, extra_fields={"CommandLine"})
    assert report["valid"] is True


def test_mismatched_logsource_and_log_type():
    report = _validate(log_type="linux")
    assert report["valid"] is False
    assert any("does not match detector log type" in e
               for e in report["blocking_errors"])


def test_logsource_service_match_is_compatible():
    rule = MINIMAL_RULE.replace(
        "product: windows\n  category: process_creation",
        "service: cloudtrail")
    assert _validate(rule, log_type="cloudtrail")["valid"] is True


def test_unsupported_aggregation_syntax():
    report = _validate(MINIMAL_RULE.replace(
        "condition: selection", "condition: selection | count() > 5"))
    assert report["valid"] is False
    assert any("Aggregation" in e for e in report["blocking_errors"])


def test_unsupported_correlation_syntax():
    report = _validate(MINIMAL_RULE + "correlation:\n  type: temporal\n")
    assert report["valid"] is False
    assert any("Correlation" in e for e in report["blocking_errors"])


def test_unresolvable_placeholder_is_blocking():
    report = _validate(MINIMAL_RULE.replace(
        "' -EncodedCommand '", "'%Admins_Workstations%'"))
    assert report["valid"] is False
    assert any("Placeholder" in e for e in report["blocking_errors"])


def test_malformed_rule_uuid_is_blocking():
    report = _validate(MINIMAL_RULE.replace(
        "id: 6f867f60-2f14-4c8d-9c0e-6d4f6c6d0001", "id: not-a-uuid"))
    assert any("well-formed UUID" in e for e in report["blocking_errors"])


def test_unsupported_level_is_blocking():
    report = _validate(MINIMAL_RULE.replace("level: high", "level: apocalyptic"))
    assert any("Unsupported level" in e for e in report["blocking_errors"])


def test_duplicate_title_is_refused():
    report = _validate(existing_titles=["Encoded PowerShell execution"])
    assert report["valid"] is False
    assert any("already exists" in e for e in report["blocking_errors"])


def test_embedded_secret_is_blocking():
    report = _validate(MINIMAL_RULE.replace(
        "' -EncodedCommand '", "'AKIAIOSFODNN7EXAMPLE'"))
    assert report["valid"] is False
    assert any("embedded secret" in e for e in report["blocking_errors"])


def test_credential_looking_detection_content_is_warning_not_blocking():
    report = _validate(MINIMAL_RULE.replace(
        "' -EncodedCommand '", "'password=SuperSecretValue123'"))
    assert report["valid"] is True
    assert report["warnings"]


# ---------------------------------------------------------------------------
# Evidence-state ledger
# ---------------------------------------------------------------------------

def test_evidence_states_advance_one_step_only():
    prov = sa.new_provenance("t", "i", "windows", "r.yml")
    assert prov["evidence_state"] == "DRAFT"
    sa.advance_provenance(prov, "SCHEMA_VALID")
    sa.advance_provenance(prov, "API_ACCEPTED")
    sa.advance_provenance(prov, "REPLAY_VERIFIED")
    assert [h["state"] for h in prov["history"]] == list(sa.EVIDENCE_STATES)


@pytest.mark.parametrize("target", ["API_ACCEPTED", "REPLAY_VERIFIED", "DRAFT"])
def test_evidence_state_skips_and_regressions_are_refused(target):
    prov = sa.new_provenance("t", "i", "windows", "r.yml")
    with pytest.raises(sa.SAError, match="one step at a time"):
        sa.advance_provenance(prov, target)


def test_create_rule_refuses_api_accepted_before_schema_valid(tmp_path):
    prov = sa.new_provenance("t", "i", "windows", "r.yml")
    prov_path = tmp_path / "prov.json"
    sa.save_provenance(prov, str(prov_path))
    rule = tmp_path / "r.yml"
    rule.write_text(MINIMAL_RULE)
    manifest = sa.new_manifest(_config(), "i")
    args = SimpleNamespace(sigma_file=str(rule), category="windows", apply=True,
                           provenance=str(prov_path))
    with pytest.raises(sa.SAError, match="not SCHEMA_VALID"):
        sa.cmd_create_rule(_config(), args, manifest, str(tmp_path / "m.json"))


def test_create_rule_dry_run_never_advances_state(monkeypatch, tmp_path):
    fake = _route({})
    monkeypatch.setattr(sa, "http_request", fake)
    prov = sa.new_provenance("t", "i", "windows", "r.yml")
    sa.advance_provenance(prov, "SCHEMA_VALID")
    prov_path = tmp_path / "prov.json"
    sa.save_provenance(prov, str(prov_path))
    rule = tmp_path / "r.yml"
    rule.write_text(MINIMAL_RULE)
    manifest = sa.new_manifest(_config(), "i")
    args = SimpleNamespace(sigma_file=str(rule), category="windows", apply=False,
                           provenance=str(prov_path))
    code, result = sa.cmd_create_rule(_config(), args, manifest, str(tmp_path / "m.json"))
    assert code == 0 and result["dry_run"] is True
    assert fake.calls == []
    assert json.loads(prov_path.read_text())["evidence_state"] == "SCHEMA_VALID"


def test_create_rule_apply_advances_to_api_accepted(monkeypatch, tmp_path):
    fake = _route({("POST", f"{sa.SA_BASE}/rules?category="): (
        201, {"_id": "rule-1", "rule": {"category": "windows", "title": "T",
                                        "log_source": "process_creation"}})})
    monkeypatch.setattr(sa, "http_request", fake)
    prov = sa.new_provenance("t", "i", "windows", "r.yml")
    sa.advance_provenance(prov, "SCHEMA_VALID")
    prov_path = tmp_path / "prov.json"
    sa.save_provenance(prov, str(prov_path))
    rule = tmp_path / "r.yml"
    rule.write_text(MINIMAL_RULE)
    manifest = sa.new_manifest(_config(), "i")
    args = SimpleNamespace(sigma_file=str(rule), category="windows", apply=True,
                           provenance=str(prov_path))
    code, result = sa.cmd_create_rule(_config(), args, manifest, str(tmp_path / "m.json"))
    assert code == 0
    assert result["evidence_state"] == "API_ACCEPTED"
    saved = json.loads(prov_path.read_text())
    assert saved["history"][-1]["evidence"]["rule_id"] == "rule-1"


def test_verify_refuses_replay_verified_without_api_accepted(tmp_path):
    prov = sa.new_provenance("t", "i", "windows", "r.yml")
    sa.advance_provenance(prov, "SCHEMA_VALID")
    prov_path = tmp_path / "prov.json"
    sa.save_provenance(prov, str(prov_path))
    manifest = sa.new_manifest(_config(), "sa-de-test-idx")
    manifest.update(rule_id="r1", detector_id="d1",
                    index="sa-de-test-idx", detector_created_at="2026-01-01T00:00:00Z")
    args = SimpleNamespace(provenance=str(prov_path))
    with pytest.raises(sa.SAError, match="not API_ACCEPTED"):
        sa.cmd_verify(_config(), args, manifest, str(tmp_path / "m.json"))


# ---------------------------------------------------------------------------
# plan-rule / validate-rule commands
# ---------------------------------------------------------------------------

_MAPPING_OK = (200, {"idx": {"mappings": {"properties": {
    "EventID": {"type": "integer"},
    "CommandLine": {"type": "text"},
    "process": {"properties": {"executable": {"type": "keyword"}}},
    "@timestamp": {"type": "date"},
    "test_case_id": {"type": "keyword"},
    "run_id": {"type": "keyword"},
}}}})


def test_plan_rule_grounds_fields_and_writes_draft(monkeypatch, tmp_path):
    fake = _route({
        ("GET", "/idx/_mapping"): _MAPPING_OK,
        ("GET", f"{sa.SA_BASE}/mappings/view"): (200, {"properties": {}}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    rule = tmp_path / "r.yml"
    rule.write_text(MINIMAL_RULE)
    prov_path = tmp_path / "prov.json"
    args = SimpleNamespace(
        threat_description="Detect encoded PowerShell", index="idx",
        log_type="windows", sigma_file=str(rule), provenance=str(prov_path),
        positive_fixture=None, negative_fixture=None, base_rule=None,
        extra_field=None, overwrite_provenance=False)
    code, result = sa.cmd_plan_rule(_config(), args)
    assert code == 0
    assert result["evidence_state"] == "DRAFT"
    assert result["unresolved_fields"] == []
    saved = json.loads(prov_path.read_text())
    assert saved["mapping_evidence"]["field_types"]["CommandLine"] == "text"
    assert saved["threat_description"] == "Detect encoded PowerShell"


def test_plan_rule_reports_unresolved_and_refuses_overwrite(monkeypatch, tmp_path):
    mapping = (200, {"idx": {"mappings": {"properties": {
        "@timestamp": {"type": "date"}}}}})
    fake = _route({
        ("GET", "/idx/_mapping"): mapping,
        ("GET", f"{sa.SA_BASE}/mappings/view"): (200, {"properties": {}}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    rule = tmp_path / "r.yml"
    rule.write_text(MINIMAL_RULE)
    prov_path = tmp_path / "prov.json"
    args = SimpleNamespace(
        threat_description="t", index="idx", log_type="windows",
        sigma_file=str(rule), provenance=str(prov_path),
        positive_fixture=None, negative_fixture=None, base_rule=None,
        extra_field=None, overwrite_provenance=False)
    code, result = sa.cmd_plan_rule(_config(), args)
    assert set(result["unresolved_fields"]) == {"EventID", "CommandLine"}
    with pytest.raises(sa.SAError, match="refusing to overwrite"):
        sa.cmd_plan_rule(_config(), args)


def test_validate_rule_advances_draft_to_schema_valid(monkeypatch, tmp_path):
    fake = _route({
        ("GET", "/idx/_mapping"): _MAPPING_OK,
        ("GET", f"{sa.SA_BASE}/mappings/view"): (200, {"properties": {}}),
        ("POST", f"{sa.SA_BASE}/rules/_search"): (200, {"hits": {"hits": []}}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    rule = tmp_path / "r.yml"
    rule.write_text(MINIMAL_RULE)
    prov = sa.new_provenance("t", "idx", "windows", str(rule))
    prov_path = tmp_path / "prov.json"
    sa.save_provenance(prov, str(prov_path))
    args = SimpleNamespace(provenance=str(prov_path), skip_duplicate_check=False)
    code, result = sa.cmd_validate_rule(_config(), args)
    assert code == 0
    assert result["valid"] is True
    assert result["evidence_state"] == "SCHEMA_VALID"
    assert json.loads(prov_path.read_text())["evidence_state"] == "SCHEMA_VALID"


def test_validate_rule_duplicate_title_on_cluster_blocks(monkeypatch, tmp_path):
    fake = _route({
        ("GET", "/idx/_mapping"): _MAPPING_OK,
        ("GET", f"{sa.SA_BASE}/mappings/view"): (200, {"properties": {}}),
        ("POST", f"{sa.SA_BASE}/rules/_search"): (200, {"hits": {"hits": [
            {"_source": {"title": "Encoded PowerShell execution"}}]}}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    rule = tmp_path / "r.yml"
    rule.write_text(MINIMAL_RULE)
    prov = sa.new_provenance("t", "idx", "windows", str(rule))
    prov_path = tmp_path / "prov.json"
    sa.save_provenance(prov, str(prov_path))
    args = SimpleNamespace(provenance=str(prov_path), skip_duplicate_check=False)
    code, result = sa.cmd_validate_rule(_config(), args)
    assert code == 7
    assert result["valid"] is False
    assert json.loads(prov_path.read_text())["evidence_state"] == "DRAFT"


# ---------------------------------------------------------------------------
# Regressions and mapping helpers
# ---------------------------------------------------------------------------

def test_findings_polling_uses_snake_case_detector_id(monkeypatch, tmp_path):
    finding = {"id": "f1", "detectorId": "d1",
               "related_doc_ids": [], "queries": [{"id": "r1"}]}
    fake = _route({
        ("PUT", "/sa-de-test-idx/_doc/"): (201, {"_seq_no": 1}),
        ("GET", f"{sa.SA_BASE}/findings/_search"): (200, {"findings": [finding]}),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    manifest = sa.new_manifest(_config(), "sa-de-test-idx")
    manifest.update(rule_id="r1", detector_id="d1", index="sa-de-test-idx",
                    detector_created_at="2026-01-01T00:00:00Z")
    pos = tmp_path / "p.json"
    neg = tmp_path / "n.json"
    pos.write_text("{}")
    neg.write_text("{}")
    clock_state = {"t": 0.0}

    def clock():
        clock_state["t"] += 20
        return clock_state["t"]

    args = SimpleNamespace(positive_fixture=str(pos), negative_fixture=str(neg),
                           timeout=60, poll_interval=1, schedule_minutes=1,
                           provenance=None)
    sa.cmd_verify(_config(), args, manifest, str(tmp_path / "m.json"),
                  sleep=lambda s: None, clock=clock)
    findings_calls = [p for (m, p, b) in fake.calls if "findings/_search" in p]
    assert findings_calls, "verify never polled the findings API"
    assert all("detector_id=" in p for p in findings_calls)
    assert all("detectorId=" not in p for p in findings_calls)


def test_flatten_mapping_produces_dotted_paths():
    flat = sa.flatten_mapping({
        "process": {"properties": {"command_line": {"type": "text"},
                                   "parent": {"properties": {
                                       "executable": {"type": "keyword"}}}}},
        "@timestamp": {"type": "date"},
    })
    assert flat == {"process.command_line": "text",
                    "process.parent.executable": "keyword",
                    "@timestamp": "date"}


def test_inspect_reports_types_aliases_and_timestamps(monkeypatch):
    fake = _route({
        ("GET", "/idx/_mapping"): _MAPPING_OK,
        ("GET", f"{sa.SA_BASE}/mappings/view"): (200, {
            "properties": {"win-EventID": {"type": "alias", "path": "EventID"}},
            "unmapped_index_fields": ["run_id"],
        }),
    })
    monkeypatch.setattr(sa, "http_request", fake)
    args = SimpleNamespace(index="idx", sigma_file=None, log_type="windows")
    code, result = sa.cmd_inspect(_config(), args)
    assert code == 0
    assert result["field_types"]["process.executable"] == "keyword"
    assert result["timestamp_fields"] == ["@timestamp"]
    assert result["sa_aliases"] == {"win-EventID": "EventID"}
    assert result["index_is_alias_or_pattern"] is False
    assert result["mutations"] == "none"


def test_inspect_flags_alias_resolution(monkeypatch):
    body = (200, {"concrete-000001": _MAPPING_OK[1]["idx"]})
    fake = _route({("GET", "/logs-alias/_mapping"): body})
    monkeypatch.setattr(sa, "http_request", fake)
    args = SimpleNamespace(index="logs-alias", sigma_file=None, log_type=None)
    code, result = sa.cmd_inspect(_config(), args)
    assert result["index_is_alias_or_pattern"] is True
    assert result["resolved_concrete_indices"] == ["concrete-000001"]


def test_provenance_load_rejects_invalid_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"not": "provenance"}')
    with pytest.raises(sa.SAError, match="not a valid provenance record"):
        sa.load_provenance(str(bad))


def test_pyyaml_declared_as_pep723_runtime_dependency():
    """Regression: PyYAML is a runtime dependency of the CLI (sigma_validation
    imports it), so it must be declared in the entrypoint's PEP 723 script
    block rather than relying on the repository dev dependency group."""
    script = (_SCRIPTS_DIR / "security_analytics.py").read_text()
    lines = script.splitlines()
    start = lines.index("# /// script")
    end = lines.index("# ///", start)
    block = "\n".join(lines[start:end + 1])
    assert "pyyaml" in block.lower()
