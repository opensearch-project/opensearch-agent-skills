#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Deterministic CLI for verification-first detection engineering with
OpenSearch Security Analytics.

Workflow: preflight -> inspect -> plan-rule -> validate-rule -> create-rule
-> create-detector -> verify -> cleanup.

Rules carry an explicit evidence state that never overstates what is proven:
DRAFT -> SCHEMA_VALID -> API_ACCEPTED -> REPLAY_VERIFIED (one step at a time).
Each command emits machine-readable JSON to stdout and diagnostics to stderr.
Mutating commands record every created resource in a local run manifest;
cleanup only ever touches resources listed in that manifest.

Connection configuration (endpoint-agnostic, never assumes localhost):
    OPENSEARCH_URL        e.g. https://opensearch.example.com:9200 (or --url)
    OPENSEARCH_USERNAME   optional basic-auth user
    OPENSEARCH_PASSWORD   optional basic-auth password
    OPENSEARCH_SSL_VERIFY "false" to skip TLS verification (self-signed dev clusters)

Usage:
    uv run python scripts/security_analytics.py <command> --help
"""

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import sigma_validation

TEST_PREFIX = "sa-de-test"
EVIDENCE_STATES = ("DRAFT", "SCHEMA_VALID", "API_ACCEPTED", "REPLAY_VERIFIED")
SA_BASE = "/_plugins/_security_analytics"
RESOURCE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]{0,254}$")
DEFAULT_POLL_INTERVAL = 10
DEFAULT_VERIFY_TIMEOUT = 180
_MISSING_HANDLER_TOKENS = ("no handler found", "invalid uri", "unknown route")
_SEMANTIC_404_TOKENS = ("no detectors found",)


class SAError(Exception):
    """Structured failure carrying an HTTP status when one exists."""

    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def redact(text, config):
    """Strip credentials from any outbound text."""
    if not text:
        return text
    out = str(text)
    for secret in (config.get("password"), config.get("auth_header")):
        if secret:
            out = out.replace(secret, "***REDACTED***")
    return out


def endpoint_identifier(url):
    """Endpoint identity safe for manifests/logs: strips userinfo if present."""
    return re.sub(r"//[^@/]+@", "//", url).rstrip("/")


def resolve_config(args):
    url = (getattr(args, "url", None) or os.getenv("OPENSEARCH_URL", "")).strip().rstrip("/")
    if not url:
        raise SAError("No OpenSearch endpoint configured. Set OPENSEARCH_URL or pass --url.")
    if not url.startswith(("http://", "https://")):
        raise SAError(f"Endpoint must be an http(s) URL, got: {endpoint_identifier(url)}")
    username = os.getenv("OPENSEARCH_USERNAME", "")
    password = os.getenv("OPENSEARCH_PASSWORD", "")
    verify_tls = os.getenv("OPENSEARCH_SSL_VERIFY", "true").strip().lower() != "false"
    config = {
        "url": url,
        "username": username,
        "password": password,
        "verify_tls": verify_tls,
        "timeout": int(os.getenv("OPENSEARCH_TIMEOUT", "30")),
    }
    if username and password:
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        config["auth_header"] = f"Basic {token}"
    else:
        config["auth_header"] = None
    return config


def http_request(config, method, path, body=None, content_type="application/json"):
    """Perform one HTTP request. Returns (status_code, parsed_body).

    4xx/5xx responses are returned, not raised, so callers can branch on
    semantics (e.g. the findings API returns 404 when no detectors exist).
    Connection-level failures raise SAError.
    """
    url = config["url"] + path
    data = None
    if body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", content_type)
    if config.get("auth_header"):
        req.add_header("Authorization", config["auth_header"])
    ctx = None
    if url.startswith("https://") and not config.get("verify_tls", True):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(req, timeout=config.get("timeout", 30), context=ctx) as resp:
            return resp.status, _parse_body(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, _parse_body(e.read())
    except urllib.error.URLError as e:
        raise SAError(
            f"Cannot reach OpenSearch at {endpoint_identifier(config['url'])}: "
            f"{redact(getattr(e, 'reason', e), config)}"
        ) from e


def _parse_body(raw):
    text = raw.decode(errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


def _body_text(body):
    return json.dumps(body) if isinstance(body, (dict, list)) else str(body)


def is_auth_failure(status):
    return status in (401, 403)


def is_missing_handler(status, body):
    if status not in (400, 404, 405):
        return False
    lowered = _body_text(body).lower()
    return any(t in lowered for t in _MISSING_HANDLER_TOKENS)


def is_semantic_findings_404(status, body):
    """SA returns 404 'No detectors found' from the findings API on an empty
    cluster. That proves the API exists; it is not a missing plugin."""
    if status != 404:
        return False
    lowered = _body_text(body).lower()
    return any(t in lowered for t in _SEMANTIC_404_TOKENS)


def validate_resource_name(name, kind):
    if not RESOURCE_NAME_RE.match(name or ""):
        raise SAError(
            f"Invalid {kind} name {name!r}: must be lowercase alphanumeric plus '._-', "
            "start with an alphanumeric, max 255 chars."
        )


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def new_manifest(config, index):
    return {
        "run_id": f"{TEST_PREFIX}-{uuid.uuid4().hex[:12]}",
        "created_at": now_iso(),
        "endpoint": endpoint_identifier(config["url"]),
        "index": index,
        "index_created_by_run": False,
        "rule_id": None,
        "detector_id": None,
        "detector_created_at": None,
        "fixture_doc_ids": [],
        "resources_created": [],
        "cleanup": {"status": "not_started", "details": []},
    }


def save_manifest(manifest, path):
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def load_manifest(path):
    if not os.path.exists(path):
        raise SAError(f"Manifest not found at {path}. Run a mutating command first.")
    with open(path) as f:
        manifest = json.load(f)
    if not isinstance(manifest, dict) or "run_id" not in manifest:
        raise SAError(f"File at {path} is not a valid run manifest.")
    return manifest


def record_resource(manifest, kind, resource_id):
    manifest["resources_created"].append(
        {"kind": kind, "id": resource_id, "created_at": now_iso()}
    )


# ---------------------------------------------------------------------------
# Rule provenance (evidence-state ledger)
# ---------------------------------------------------------------------------

def new_provenance(threat_description, index, log_type, rule_path):
    return {
        "run_id": f"{TEST_PREFIX}-plan-{uuid.uuid4().hex[:12]}",
        "threat_description": threat_description,
        "index": index,
        "log_type": log_type,
        "candidate_rule_path": rule_path,
        "fields_referenced": [],
        "mapping_evidence": {},
        "unresolved_fields": [],
        "generated_at": now_iso(),
        "evidence_state": "DRAFT",
        "history": [{"state": "DRAFT", "at": now_iso()}],
    }


def load_provenance(path):
    if not os.path.exists(path):
        raise SAError(f"Provenance record not found at {path}. Run plan-rule first.")
    with open(path) as f:
        prov = json.load(f)
    if not isinstance(prov, dict) or prov.get("evidence_state") not in EVIDENCE_STATES:
        raise SAError(f"File at {path} is not a valid provenance record.")
    return prov


def advance_provenance(prov, new_state, evidence=None):
    """Advance the evidence state by exactly one step; anything else is refused."""
    current = prov["evidence_state"]
    try:
        current_i = EVIDENCE_STATES.index(current)
        new_i = EVIDENCE_STATES.index(new_state)
    except ValueError:
        raise SAError(f"Unknown evidence state {new_state!r}.") from None
    if new_i != current_i + 1:
        raise SAError(
            f"Refusing evidence-state transition {current} -> {new_state}: states "
            "advance one step at a time and never regress or skip."
        )
    prov["evidence_state"] = new_state
    entry = {"state": new_state, "at": now_iso()}
    if evidence:
        entry["evidence"] = evidence
    prov["history"].append(entry)
    return prov


def save_provenance(prov, path):
    with open(path, "w") as f:
        json.dump(prov, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Response parsing (pure, unit-testable)
# ---------------------------------------------------------------------------

def flatten_mapping(props, prefix=""):
    """Flatten an index mapping's properties into dotted paths with types."""
    out = {}
    for name, spec in (props or {}).items():
        path = f"{prefix}{name}"
        if isinstance(spec, dict) and "properties" in spec:
            out.update(flatten_mapping(spec["properties"], path + "."))
        elif isinstance(spec, dict):
            out[path] = spec.get("type", "object")
    return out

def parse_rule_response(status, body):
    if status not in (200, 201) or not isinstance(body, dict) or "_id" not in body:
        raise SAError(
            f"Rule creation failed (HTTP {status}): {_body_text(body)[:500]}",
            status=status, body=body,
        )
    rule = body.get("rule", {})
    return {
        "rule_id": body["_id"],
        "category": rule.get("category"),
        "title": rule.get("title"),
        "log_source": rule.get("log_source"),
    }


def parse_detector_response(status, body):
    if status not in (200, 201) or not isinstance(body, dict) or "_id" not in body:
        raise SAError(
            f"Detector creation failed (HTTP {status}): {_body_text(body)[:500]}",
            status=status, body=body,
        )
    detector = body.get("detector", {})
    return {
        "detector_id": body["_id"],
        "enabled": detector.get("enabled"),
        "enabled_time": detector.get("enabled_time"),
        "schedule": detector.get("schedule"),
        "name": detector.get("name"),
    }


def extract_sigma_fields(sigma_text):
    """Best-effort extraction of field names from a Sigma detection block.

    Deliberately lightweight (no YAML dependency): collects `Field:` and
    `Field|modifier:` keys inside the detection section, excluding structural
    keys. Report these as candidates only; never invent mappings from them.
    """
    fields = []
    in_detection = False
    for line in sigma_text.splitlines():
        if re.match(r"^detection:", line):
            in_detection = True
            continue
        if in_detection and re.match(r"^[A-Za-z]", line):
            break
        if not in_detection:
            continue
        m = re.match(r"^\s+([A-Za-z0-9_.]+)(\|[a-z_|]+)?:\s*(.*)$", line)
        if m:
            key, _, value = m.groups()
            if key == "condition":
                continue
            if value == "" and "." not in key and not m.group(2):
                continue  # structural key like `selection:`
            if key not in fields:
                fields.append(key)
    return fields


def match_findings(findings, rule_id, doc_id):
    """Findings that reference rule_id AND doc_id (attribution join)."""
    matched = []
    for f in findings:
        doc_ids = f.get("related_doc_ids", [])
        query_ids = [q.get("id") for q in f.get("queries", [])]
        if doc_id in doc_ids and rule_id in query_ids:
            matched.append(f)
    return matched


def findings_for_doc(findings, doc_id):
    return [f for f in findings if doc_id in f.get("related_doc_ids", [])]


# ---------------------------------------------------------------------------
# Commands — each takes (config, args), returns (exit_code, result_dict)
# ---------------------------------------------------------------------------

def cmd_preflight(config, args):
    status, body = http_request(config, "GET", "/")
    if is_auth_failure(status):
        raise SAError(
            f"Authentication failed against {endpoint_identifier(config['url'])} "
            f"(HTTP {status}). Check OPENSEARCH_USERNAME/OPENSEARCH_PASSWORD.",
            status=status,
        )
    if status != 200 or not isinstance(body, dict):
        raise SAError(f"Cluster root endpoint returned HTTP {status}.", status=status, body=body)
    version = body.get("version", {}).get("number", "unknown")
    distribution = body.get("version", {}).get("distribution", "unknown")

    apis = {}
    checks = [
        ("rules", "POST", f"{SA_BASE}/rules/_search?pre_packaged=true",
         {"from": 0, "size": 1, "query": {"match_all": {}}}),
        ("detectors", "POST", f"{SA_BASE}/detectors/_search",
         {"size": 1, "query": {"match_all": {}}}),
        ("findings", "GET", f"{SA_BASE}/findings/_search?size=1", None),
    ]
    plugin_missing = False
    for name, method, path, req_body in checks:
        s, b = http_request(config, method, path, req_body)
        if is_auth_failure(s):
            raise SAError(
                f"Security Analytics {name} API denied (HTTP {s}). "
                "The configured user lacks security_analytics permissions.",
                status=s,
            )
        if is_missing_handler(s, b):
            apis[name] = {"available": False, "status": s}
            plugin_missing = True
        elif s == 200 or is_semantic_findings_404(s, b):
            apis[name] = {"available": True, "status": s}
        else:
            apis[name] = {"available": False, "status": s, "detail": _body_text(b)[:300]}
            plugin_missing = True

    result = {
        "command": "preflight",
        "endpoint": endpoint_identifier(config["url"]),
        "opensearch_version": version,
        "distribution": distribution,
        "auth_mode": "basic" if config.get("auth_header") else "none",
        "security_analytics_available": not plugin_missing,
        "apis": apis,
        "mutations": "none",
    }
    if plugin_missing:
        result["error"] = "Security Analytics plugin APIs are missing or unusable on this cluster."
        return 2, result
    return 0, result


def fetch_field_evidence(config, index, log_type=None):
    """Read-only mapping evidence for an index: concrete indices, dotted field
    paths with types, date fields, and SA alias resolution when a log type is
    given. Never invents mappings."""
    status, body = http_request(config, "GET", f"/{index}/_mapping")
    if status == 404:
        raise SAError(f"Index {index!r} does not exist.", status=404)
    if status != 200:
        raise SAError(f"Mapping fetch failed (HTTP {status}).", status=status, body=body)
    concrete = sorted(body.keys()) if isinstance(body, dict) else []
    field_types = {}
    for concrete_index in concrete:
        props = body.get(concrete_index, {}).get("mappings", {}).get("properties", {})
        field_types.update(flatten_mapping(props))

    evidence = {
        "index": index,
        "resolved_concrete_indices": concrete,
        "index_is_alias_or_pattern": concrete != [index],
        "field_types": field_types,
        "timestamp_fields": sorted(
            f for f, t in field_types.items() if t == "date"
        ),
        "sa_aliases": {},
        "sa_unmapped_index_fields": [],
    }
    if log_type:
        s, view = http_request(
            config, "GET",
            f"{SA_BASE}/mappings/view?index_name={index}&rule_topic={log_type}",
        )
        if s == 200 and isinstance(view, dict):
            aliases = {}
            for alias, spec in (view.get("properties") or {}).items():
                target = spec.get("path") if isinstance(spec, dict) else None
                aliases[alias] = target
            evidence["sa_aliases"] = aliases
            evidence["sa_unmapped_index_fields"] = view.get("unmapped_index_fields", [])
        else:
            evidence["sa_mappings_view_error"] = f"HTTP {s}"
    return evidence


def resolvable_field_universe(evidence):
    return set(evidence.get("field_types", {})) | set(evidence.get("sa_aliases", {}))


def cmd_inspect(config, args):
    validate_resource_name(args.index, "index")
    evidence = fetch_field_evidence(config, args.index, args.log_type)

    result = {
        "command": "inspect",
        "index": args.index,
        "resolved_concrete_indices": evidence["resolved_concrete_indices"],
        "index_is_alias_or_pattern": evidence["index_is_alias_or_pattern"],
        "field_types": evidence["field_types"],
        "index_fields": sorted(evidence["field_types"]),
        "timestamp_fields": evidence["timestamp_fields"],
        "target_log_type": args.log_type,
        "mutations": "none",
        "note": "Mapping inspection only; raw documents are never sampled.",
    }
    if args.log_type:
        result["sa_aliases"] = evidence["sa_aliases"]
        result["sa_unmapped_index_fields"] = evidence["sa_unmapped_index_fields"]
        if "sa_mappings_view_error" in evidence:
            result["sa_mappings_view_error"] = evidence["sa_mappings_view_error"]
    if args.sigma_file:
        with open(args.sigma_file) as f:
            sigma_text = f.read()
        candidates = extract_sigma_fields(sigma_text)
        universe = resolvable_field_universe(evidence)
        result["sigma_candidate_fields"] = candidates
        result["fields_present_in_index"] = [c for c in candidates if c in universe]
        result["fields_missing_from_index"] = [c for c in candidates if c not in universe]
    return 0, result


def cmd_plan_rule(config, args):
    """Ground a host-agent-authored candidate rule in mapping evidence and
    open its provenance record at evidence state DRAFT. Read-only."""
    validate_resource_name(args.index, "index")
    if not os.path.exists(args.sigma_file):
        raise SAError(
            f"Candidate rule {args.sigma_file!r} does not exist. The host agent "
            "authors the Sigma YAML; plan-rule only grounds and records it."
        )
    if os.path.exists(args.provenance) and not args.overwrite_provenance:
        raise SAError(
            f"Provenance record {args.provenance!r} already exists; refusing to "
            "overwrite silently. Pass --overwrite-provenance to start over."
        )
    with open(args.sigma_file) as f:
        sigma_text = f.read()

    evidence = fetch_field_evidence(config, args.index, args.log_type)
    universe = resolvable_field_universe(evidence)
    extra = list(args.extra_field or [])
    referenced = extract_sigma_fields(sigma_text)
    unresolved = [f for f in referenced if f not in universe and f not in extra]

    prov = new_provenance(args.threat_description, args.index, args.log_type,
                          args.sigma_file)
    prov["fields_referenced"] = referenced
    prov["unresolved_fields"] = unresolved
    prov["declared_fixture_fields"] = extra
    prov["mapping_evidence"] = {
        "resolved_concrete_indices": evidence["resolved_concrete_indices"],
        "field_types": {f: evidence["field_types"][f]
                        for f in referenced if f in evidence["field_types"]},
        "sa_aliases": {f: evidence["sa_aliases"][f]
                       for f in referenced if f in evidence["sa_aliases"]},
        "timestamp_fields": evidence["timestamp_fields"],
    }
    if args.positive_fixture:
        prov["positive_fixture"] = args.positive_fixture
    if args.negative_fixture:
        prov["negative_fixture"] = args.negative_fixture
    if args.base_rule:
        prov["modified_from"] = args.base_rule
    save_provenance(prov, args.provenance)
    return 0, {
        "command": "plan-rule",
        "evidence_state": "DRAFT",
        "provenance": args.provenance,
        "fields_referenced": referenced,
        "unresolved_fields": unresolved,
        "mutations": "none",
        "next_action": ("Run validate-rule to attempt SCHEMA_VALID."
                        if not unresolved else
                        "Rewrite the candidate rule using only resolved fields, "
                        "then re-run plan-rule."),
    }


def cmd_validate_rule(config, args):
    """Deterministic Sigma-subset validation; advances DRAFT -> SCHEMA_VALID."""
    prov = load_provenance(args.provenance)
    with open(prov["candidate_rule_path"]) as f:
        sigma_text = f.read()

    evidence = fetch_field_evidence(config, prov["index"], prov["log_type"])
    existing_titles = []
    if not args.skip_duplicate_check:
        s, b = http_request(
            config, "POST", f"{SA_BASE}/rules/_search?pre_packaged=false",
            {"from": 0, "size": 500, "query": {"match_all": {}}},
        )
        if s == 200 and isinstance(b, dict):
            for hit in b.get("hits", {}).get("hits", []):
                title = (hit.get("_source") or {}).get("title")
                if title:
                    existing_titles.append(title)
        else:
            raise SAError(
                f"Could not list existing custom rules for the duplicate-identity "
                f"check (HTTP {s}). Pass --skip-duplicate-check to proceed without it.",
                status=s,
            )

    report = sigma_validation.validate_sigma(
        sigma_text,
        log_type=prov["log_type"],
        resolvable_fields=resolvable_field_universe(evidence),
        extra_fields=prov.get("declared_fixture_fields", []),
        existing_titles=existing_titles,
    )
    result = {"command": "validate-rule", "provenance": args.provenance,
              "mutations": "none", **report}
    if not report["valid"]:
        result["evidence_state"] = prov["evidence_state"]
        return 7, result
    if prov["evidence_state"] == "DRAFT":
        advance_provenance(prov, "SCHEMA_VALID", {
            "resolved_fields": report["resolved_fields"],
            "supported_constructs_used": report["supported_constructs_used"],
            "duplicate_check": "performed" if not args.skip_duplicate_check
                               else "skipped",
        })
        save_provenance(prov, args.provenance)
    result["evidence_state"] = prov["evidence_state"]
    return 0, result


def cmd_create_rule(config, args, manifest, manifest_path):
    with open(args.sigma_file) as f:
        sigma_text = f.read()
    candidates = extract_sigma_fields(sigma_text)

    prov = None
    if getattr(args, "provenance", None):
        prov = load_provenance(args.provenance)
        if prov["evidence_state"] != "SCHEMA_VALID":
            raise SAError(
                f"Provenance is at {prov['evidence_state']}, not SCHEMA_VALID. "
                "A rule cannot be marked API_ACCEPTED before deterministic "
                "validation passes; run validate-rule first."
            )

    if not args.apply:
        return 0, {
            "command": "create-rule",
            "dry_run": True,
            "would_create_rule_in_category": args.category,
            "sigma_candidate_fields": candidates,
            "note": ("OpenSearch Security Analytics cannot pre-validate raw Sigma "
                     "content without creating the rule (rules/validate only checks "
                     "already-created rule ids against an index); this preview is "
                     "local static analysis, not OpenSearch API acceptance."),
            "mutations": "none (pass --apply to create)",
        }

    if manifest.get("rule_id"):
        raise SAError(
            f"This run already created rule {manifest['rule_id']}; refusing to create "
            "another. Start a new run (new manifest) or clean up first."
        )
    status, body = http_request(
        config, "POST", f"{SA_BASE}/rules?category={args.category}", sigma_text
    )
    parsed = parse_rule_response(status, body)
    manifest["rule_id"] = parsed["rule_id"]
    record_resource(manifest, "rule", parsed["rule_id"])
    save_manifest(manifest, manifest_path)
    if prov is not None:
        advance_provenance(prov, "API_ACCEPTED", {
            "rule_id": parsed["rule_id"], "http_accepted": True,
        })
        save_provenance(prov, args.provenance)
    result = {"command": "create-rule", "dry_run": False, **parsed,
              "manifest": manifest_path}
    if prov is not None:
        result["evidence_state"] = prov["evidence_state"]
        result["provenance"] = args.provenance
    return 0, result


def cmd_create_detector(config, args, manifest, manifest_path, sleep=time.sleep):
    validate_resource_name(args.index, "index")
    rule_id = manifest.get("rule_id")
    if not rule_id:
        raise SAError("Manifest has no rule_id. Run create-rule --apply first.")
    if manifest.get("detector_id"):
        raise SAError(
            f"This run already created detector {manifest['detector_id']}; refusing to "
            "create another."
        )

    s, b = http_request(
        config, "POST", f"{SA_BASE}/mappings",
        {"index_name": args.index, "rule_topic": args.log_type, "partial": True},
    )
    if s != 200:
        raise SAError(f"SA field-mapping creation failed (HTTP {s}): {_body_text(b)[:300]}",
                      status=s, body=b)
    record_resource(manifest, "sa_field_mapping", f"{args.index}:{args.log_type}")

    name = args.name or f"{manifest['run_id']}-detector"
    detector_body = {
        "name": name,
        "detector_type": args.log_type,
        "enabled": True,
        "schedule": {"period": {"interval": args.schedule_minutes, "unit": "MINUTES"}},
        "inputs": [{
            "detector_input": {
                "description": f"Detection-engineering verification run {manifest['run_id']}",
                "indices": [args.index],
                "custom_rules": [{"id": rule_id}],
                "pre_packaged_rules": [],
            }
        }],
        "triggers": [],
    }
    status, body = http_request(config, "POST", f"{SA_BASE}/detectors", detector_body)
    parsed = parse_detector_response(status, body)
    manifest["detector_id"] = parsed["detector_id"]
    manifest["detector_created_at"] = now_iso()
    record_resource(manifest, "detector", parsed["detector_id"])
    save_manifest(manifest, manifest_path)

    ready = bool(parsed.get("enabled"))
    for _ in range(6):
        if ready:
            break
        sleep(5)
        s, b = http_request(
            config, "POST", f"{SA_BASE}/detectors/_search",
            {"query": {"terms": {"_id": [parsed["detector_id"]]}}},
        )
        hits = b.get("hits", {}).get("hits", []) if isinstance(b, dict) else []
        if hits and hits[0].get("_source", {}).get("enabled"):
            ready = True

    return (0 if ready else 3), {
        "command": "create-detector",
        **parsed,
        "ready": ready,
        "invariant": "Detectors only evaluate documents indexed AFTER detector creation "
                     "(sequence-number based). Index verification fixtures after this point.",
        "manifest": manifest_path,
    }


def cmd_verify(config, args, manifest, manifest_path, sleep=time.sleep, clock=time.monotonic):
    rule_id = manifest.get("rule_id")
    detector_id = manifest.get("detector_id")
    index = manifest.get("index")
    if not (rule_id and detector_id and index):
        raise SAError("Manifest must contain rule_id, detector_id and index before verify.")
    if not manifest.get("detector_created_at"):
        raise SAError("Manifest missing detector_created_at; cannot prove fixture eligibility.")

    prov = None
    if getattr(args, "provenance", None):
        prov = load_provenance(args.provenance)
        if prov["evidence_state"] != "API_ACCEPTED":
            raise SAError(
                f"Provenance is at {prov['evidence_state']}, not API_ACCEPTED. "
                "REPLAY_VERIFIED requires an API-accepted rule; run create-rule "
                "--apply with this provenance record first."
            )

    run_id = manifest["run_id"]
    with open(args.positive_fixture) as f:
        positive = json.load(f)
    with open(args.negative_fixture) as f:
        negative = json.load(f)

    docs = {}
    for label, doc in (("positive", positive), ("negative", negative)):
        doc_id = f"{run_id}-{label}"
        doc = dict(doc)
        doc["test_case_id"] = doc_id
        doc["run_id"] = run_id
        doc["@timestamp"] = now_iso()
        s, b = http_request(config, "PUT", f"/{index}/_doc/{doc_id}?refresh=true", doc)
        if s not in (200, 201):
            raise SAError(f"Indexing {label} fixture failed (HTTP {s}).", status=s, body=b)
        docs[label] = {
            "doc_id": doc_id,
            "seq_no": b.get("_seq_no") if isinstance(b, dict) else None,
            "indexed_at": now_iso(),
        }
        manifest["fixture_doc_ids"].append(doc_id)
        record_resource(manifest, "document", f"{index}/{doc_id}")
    save_manifest(manifest, manifest_path)

    eligibility = {
        "detector_created_at": manifest["detector_created_at"],
        "positive_indexed_at": docs["positive"]["indexed_at"],
        "negative_indexed_at": docs["negative"]["indexed_at"],
        "both_indexed_after_detector_creation": (
            docs["positive"]["indexed_at"] > manifest["detector_created_at"]
            and docs["negative"]["indexed_at"] > manifest["detector_created_at"]
        ),
    }

    deadline = clock() + args.timeout
    positive_findings = []
    all_findings = []
    polls = 0
    while clock() < deadline:
        polls += 1
        s, b = http_request(
            config, "GET", f"{SA_BASE}/findings/_search?detector_id={detector_id}&size=100"
        )
        if s == 200 and isinstance(b, dict):
            all_findings = b.get("findings", [])
            positive_findings = match_findings(all_findings, rule_id, docs["positive"]["doc_id"])
            if positive_findings:
                break
        elif not is_semantic_findings_404(s, b):
            print(f"[verify] findings poll HTTP {s}", file=sys.stderr)
        sleep(args.poll_interval)

    if not positive_findings:
        return 4, {
            "command": "verify",
            "verified": False,
            "reason": f"No finding attributed the positive fixture within {args.timeout}s "
                      f"({polls} polls).",
            "eligibility": eligibility,
            "findings_observed": len(all_findings),
        }

    grace = args.schedule_minutes * 60 + 15
    grace_deadline = min(clock() + grace, deadline + grace)
    while clock() < grace_deadline:
        sleep(args.poll_interval)
        s, b = http_request(
            config, "GET", f"{SA_BASE}/findings/_search?detector_id={detector_id}&size=100"
        )
        if s == 200 and isinstance(b, dict):
            all_findings = b.get("findings", [])

    negative_findings = findings_for_doc(all_findings, docs["negative"]["doc_id"])
    finding = positive_findings[0]
    result = {
        "command": "verify",
        "verified": not negative_findings,
        "positive": {
            "doc_id": docs["positive"]["doc_id"],
            "finding_id": finding.get("id"),
            "detector_id": finding.get("detectorId"),
            "rule_ids_in_finding": [q.get("id") for q in finding.get("queries", [])],
            "related_doc_ids": finding.get("related_doc_ids"),
            "translated_query": (finding.get("queries") or [{}])[0].get("query"),
        },
        "negative": {
            "doc_id": docs["negative"]["doc_id"],
            "findings_attributed": len(negative_findings),
            "was_eligible_for_evaluation": eligibility["both_indexed_after_detector_creation"],
        },
        "eligibility": eligibility,
        "note": "One negative fixture proves this rule did not match this document; "
                "it is not a general false-positive rate.",
    }
    if negative_findings:
        result["error"] = "Negative fixture produced a finding — the rule matches more than intended."
        return 5, result
    if prov is not None and eligibility["both_indexed_after_detector_creation"]:
        advance_provenance(prov, "REPLAY_VERIFIED", {
            "finding_id": finding.get("id"),
            "positive_doc_id": docs["positive"]["doc_id"],
            "negative_doc_id": docs["negative"]["doc_id"],
            "negative_findings_attributed": 0,
            "eligibility": eligibility,
        })
        save_provenance(prov, args.provenance)
        result["evidence_state"] = prov["evidence_state"]
        result["provenance"] = args.provenance
    return 0, result


def cmd_cleanup(config, args, manifest, manifest_path):
    details = []
    failures = 0

    def delete(kind, path, forced_path=None):
        nonlocal failures
        s, b = http_request(config, "DELETE", path)
        if s in (200, 204):
            details.append({"kind": kind, "status": "deleted"})
        elif s == 404:
            details.append({"kind": kind, "status": "already_absent"})
        elif forced_path and args.force:
            s2, b2 = http_request(config, "DELETE", forced_path)
            if s2 in (200, 204):
                details.append({"kind": kind, "status": "force_deleted",
                                "normal_delete_error": f"HTTP {s}"})
            else:
                failures += 1
                details.append({"kind": kind, "status": "failed",
                                "detail": f"HTTP {s} then forced HTTP {s2}"})
        else:
            failures += 1
            detail = {"kind": kind, "status": "failed", "detail": f"HTTP {s}"}
            if forced_path and not args.force:
                detail["hint"] = "re-run cleanup with --force to attempt forced deletion"
            details.append(detail)

    if manifest.get("detector_id"):
        delete("detector", f"{SA_BASE}/detectors/{manifest['detector_id']}")
    else:
        details.append({"kind": "detector", "status": "not_created_by_run"})

    if manifest.get("rule_id"):
        rid = manifest["rule_id"]
        delete("rule", f"{SA_BASE}/rules/{rid}", forced_path=f"{SA_BASE}/rules/{rid}?forced=true")
    else:
        details.append({"kind": "rule", "status": "not_created_by_run"})

    if manifest.get("index_created_by_run") and manifest.get("index"):
        delete("index", f"/{manifest['index']}")
    else:
        details.append({
            "kind": "index", "status": "skipped",
            "reason": "index was not created by this run; refusing to delete user data",
        })

    manifest["cleanup"] = {
        "status": "complete" if failures == 0 else "partial",
        "finished_at": now_iso(),
        "details": details,
    }
    save_manifest(manifest, manifest_path)
    return (0 if failures == 0 else 6), {
        "command": "cleanup",
        "status": manifest["cleanup"]["status"],
        "details": details,
        "manifest": manifest_path,
    }


def cmd_create_index(config, args, manifest, manifest_path):
    """Create the clean, uniquely-named test index for this run."""
    validate_resource_name(args.index, "index")
    if not args.index.startswith(TEST_PREFIX):
        raise SAError(
            f"Refusing to create index {args.index!r}: run-created indices must start "
            f"with the test prefix {TEST_PREFIX!r} so cleanup can never touch user data."
        )
    with open(args.mapping_file) as f:
        body = json.load(f)
    status, resp = http_request(config, "PUT", f"/{args.index}", body)
    if status != 200:
        raise SAError(f"Index creation failed (HTTP {status}): {_body_text(resp)[:300]}",
                      status=status, body=resp)
    manifest["index"] = args.index
    manifest["index_created_by_run"] = True
    record_resource(manifest, "index", args.index)
    save_manifest(manifest, manifest_path)
    return 0, {"command": "create-index", "index": args.index, "created": True,
               "manifest": manifest_path}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="security_analytics.py",
        description="Verification-first detection engineering for OpenSearch Security Analytics.",
    )
    p.add_argument("--url", help="OpenSearch endpoint (default: $OPENSEARCH_URL)")
    p.add_argument("--manifest", default="sa-run-manifest.json",
                   help="Path to the run manifest (default: sa-run-manifest.json)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="Check cluster + Security Analytics APIs (read-only)")

    sp = sub.add_parser("inspect", help="Inspect an index's mappings (read-only)")
    sp.add_argument("--index", required=True)
    sp.add_argument("--sigma-file", help="Sigma YAML to cross-check fields against")
    sp.add_argument("--log-type", help="SA log type for the mappings/view check")

    sp = sub.add_parser(
        "plan-rule",
        help="Ground a host-authored candidate rule in mapping evidence (read-only)")
    sp.add_argument("--threat-description", required=True,
                    help="Natural-language detection objective being addressed")
    sp.add_argument("--index", required=True)
    sp.add_argument("--log-type", required=True)
    sp.add_argument("--sigma-file", required=True,
                    help="Candidate Sigma YAML authored by the host agent")
    sp.add_argument("--provenance", default="sa-rule-provenance.json")
    sp.add_argument("--positive-fixture")
    sp.add_argument("--negative-fixture")
    sp.add_argument("--base-rule", help="Existing Sigma rule this candidate modifies")
    sp.add_argument("--extra-field", action="append",
                    help="Explicitly declared synthetic fixture field (repeatable)")
    sp.add_argument("--overwrite-provenance", action="store_true")

    sp = sub.add_parser(
        "validate-rule",
        help="Deterministic Sigma-subset validation; DRAFT -> SCHEMA_VALID")
    sp.add_argument("--provenance", default="sa-rule-provenance.json")
    sp.add_argument("--skip-duplicate-check", action="store_true",
                    help="Skip the live duplicate-title check against custom rules")

    sp = sub.add_parser("create-index", help="Create a clean uniquely-named test index")
    sp.add_argument("--index", required=True)
    sp.add_argument("--mapping-file", required=True)

    sp = sub.add_parser("create-rule", help="Create a custom Sigma rule")
    sp.add_argument("--sigma-file", required=True)
    sp.add_argument("--category", required=True, help="SA rule category, e.g. windows")
    sp.add_argument("--apply", action="store_true",
                    help="Actually create the rule (omit for dry-run)")
    sp.add_argument("--provenance",
                    help="Provenance record; requires SCHEMA_VALID, advances to "
                         "API_ACCEPTED on success")

    sp = sub.add_parser("create-detector", help="Create a detector for this run's rule")
    sp.add_argument("--index", required=True)
    sp.add_argument("--log-type", required=True)
    sp.add_argument("--name")
    sp.add_argument("--schedule-minutes", type=int, default=1)

    sp = sub.add_parser("verify", help="Index post-detector fixtures and verify findings")
    sp.add_argument("--positive-fixture", required=True)
    sp.add_argument("--negative-fixture", required=True)
    sp.add_argument("--timeout", type=int, default=DEFAULT_VERIFY_TIMEOUT)
    sp.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    sp.add_argument("--schedule-minutes", type=int, default=1)
    sp.add_argument("--provenance",
                    help="Provenance record; requires API_ACCEPTED, advances to "
                         "REPLAY_VERIFIED on success")

    sp = sub.add_parser("cleanup", help="Delete resources recorded in the run manifest")
    sp.add_argument("--force", action="store_true",
                    help="Retry failed deletions with forced=true")

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        config = resolve_config(args)
        manifest_path = args.manifest
        if args.command == "preflight":
            code, result = cmd_preflight(config, args)
        elif args.command == "inspect":
            code, result = cmd_inspect(config, args)
        elif args.command == "plan-rule":
            code, result = cmd_plan_rule(config, args)
        elif args.command == "validate-rule":
            code, result = cmd_validate_rule(config, args)
        else:
            if args.command in ("create-index", "create-rule") and not os.path.exists(manifest_path):
                manifest = new_manifest(config, getattr(args, "index", None))
            else:
                manifest = load_manifest(manifest_path)
            if args.command == "create-index":
                code, result = cmd_create_index(config, args, manifest, manifest_path)
            elif args.command == "create-rule":
                code, result = cmd_create_rule(config, args, manifest, manifest_path)
            elif args.command == "create-detector":
                code, result = cmd_create_detector(config, args, manifest, manifest_path)
            elif args.command == "verify":
                code, result = cmd_verify(config, args, manifest, manifest_path)
            elif args.command == "cleanup":
                code, result = cmd_cleanup(config, args, manifest, manifest_path)
            else:
                raise SAError(f"Unknown command {args.command!r}")
    except SAError as e:
        payload = {"error": True, "message": redact(e.message, locals().get("config", {})),
                   "status": e.status}
        print(json.dumps(payload, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
