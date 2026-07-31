"""Deterministic compiler for OpenSearch permission evidence.

The compiler deliberately does not ask an LLM to invent permissions. It turns
permissions observed through OpenSearch's own permission-check responses and
audit records into a narrow, reviewable role candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit


class WorkflowError(ValueError):
    """Raised when a workflow cannot be compiled safely."""


@dataclass(frozen=True)
class Step:
    step_id: str
    method: str
    path: str
    expect: str
    index_patterns: tuple[str, ...]


@dataclass(frozen=True)
class Evidence:
    step_id: str
    allowed: bool | None
    missing_privileges: tuple[str, ...]
    source: str


def _path_has_unsafe_segments(path: str) -> bool:
    decoded = path
    for _ in range(2):
        decoded = unquote(decoded)
    return "\\" in decoded or any(
        segment in {".", ".."} for segment in decoded.split("/")
    )


def validate_workflow(document: dict[str, Any]) -> dict[str, Step]:
    """Validate a workflow and return steps keyed by their stable IDs."""
    if not isinstance(document, dict):
        raise WorkflowError("workflow must be a JSON object")
    if not isinstance(document.get("name"), str) or not document["name"].strip():
        raise WorkflowError("workflow.name must be a non-empty string")
    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowError("workflow.steps must be a non-empty array")

    steps: dict[str, Step] = {}
    for position, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise WorkflowError(f"steps[{position}] must be an object")
        step_id = raw.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise WorkflowError(f"steps[{position}].id must be a non-empty string")
        if step_id in steps:
            raise WorkflowError(f"duplicate step id: {step_id}")
        method = str(raw.get("method", "GET")).upper()
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            raise WorkflowError(f"{step_id}: unsupported HTTP method {method}")
        path = raw.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            raise WorkflowError(f"{step_id}: path must start with '/'")
        path_parts = urlsplit(path)
        if path_parts.scheme or path_parts.netloc or path_parts.fragment:
            raise WorkflowError(
                f"{step_id}: path must be root-relative and contain no fragment"
            )
        if _path_has_unsafe_segments(path_parts.path):
            raise WorkflowError(f"{step_id}: path contains an unsafe segment")
        if method == "HEAD" and raw.get("body") is not None:
            raise WorkflowError(f"{step_id}: HEAD steps must not contain a body")
        expect = str(raw.get("expect", "allow")).lower()
        if expect not in {"allow", "deny"}:
            raise WorkflowError(f"{step_id}: expect must be 'allow' or 'deny'")
        patterns = raw.get("index_patterns", [])
        if not isinstance(patterns, list) or not all(
            isinstance(item, str) and item.strip() for item in patterns
        ):
            raise WorkflowError(f"{step_id}: index_patterns must be an array of strings")
        steps[step_id] = Step(
            step_id=step_id,
            method=method,
            path=path,
            expect=expect,
            index_patterns=tuple(patterns),
        )
    return steps


def _missing_from_reason(reason: str) -> list[str]:
    marker = "no permissions for ["
    start = reason.find(marker)
    if start < 0:
        return []
    start += len(marker)
    depth = 1
    end = start
    while end < len(reason) and depth:
        if reason[end] == "[":
            depth += 1
        elif reason[end] == "]":
            depth -= 1
        end += 1
    if depth:
        return []
    payload = reason[start : end - 1].strip()
    if not payload:
        return []

    actions: list[str] = []
    action_start = 0
    nested_depth = 0
    for position, character in enumerate(payload):
        if character == "[":
            nested_depth += 1
        elif character == "]" and nested_depth:
            nested_depth -= 1
        elif character == "," and nested_depth == 0:
            action = payload[action_start:position].strip()
            if action:
                actions.append(action)
            action_start = position + 1
    final_action = payload[action_start:].strip()
    if final_action:
        actions.append(final_action)
    return actions


def _walk_json(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def parse_missing_privileges(response: Any) -> tuple[str, ...]:
    """Extract exact missing action names from supported OpenSearch responses."""
    found: set[str] = set()
    for value in _walk_json(response):
        if not isinstance(value, dict):
            continue
        direct = value.get("missingPrivileges")
        if isinstance(direct, list):
            found.update(
                item.strip() for item in direct if isinstance(item, str) and item.strip()
            )
        privilege = value.get("audit_request_privilege")
        category = str(value.get("audit_category", "")).upper()
        if category == "MISSING_PRIVILEGES" and isinstance(privilege, str):
            if privilege.strip():
                found.add(privilege.strip())
        reason = value.get("reason")
        if isinstance(reason, str):
            found.update(_missing_from_reason(reason))
    return tuple(sorted(found))


def _infer_allowed(response: Any) -> bool | None:
    observed: set[bool] = set()
    for value in _walk_json(response):
        if isinstance(value, dict) and isinstance(value.get("accessAllowed"), bool):
            observed.add(value["accessAllowed"])
    if False in observed:
        return False
    if True in observed:
        return True
    return None


def parse_evidence_document(document: Any, source: str = "evidence") -> list[Evidence]:
    """Parse one evidence document.

    Accepted forms are a single record or a list of records. Each record must
    include ``step_id`` and a nested ``response`` object. Requiring the wrapper
    prevents record metadata from being interpreted as permission evidence.
    """
    records = document if isinstance(document, list) else [document]
    parsed: list[Evidence] = []
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise WorkflowError(f"{source}[{position}] must be an object")
        step_id = record.get("step_id")
        if not isinstance(step_id, str) or not step_id.strip():
            raise WorkflowError(f"{source}[{position}].step_id is required")
        if "response" not in record:
            raise WorkflowError(f"{source}[{position}].response is required")
        response = record["response"]
        missing_privileges = parse_missing_privileges(response)
        allowed = _infer_allowed(response)
        if allowed is None and missing_privileges:
            allowed = False
        parsed.append(
            Evidence(
                step_id=step_id,
                allowed=allowed,
                missing_privileges=missing_privileges,
                source=source,
            )
        )
    return parsed


def _is_index_action(action: str) -> bool:
    return action.startswith("indices:")


def _contains_wildcard(value: str) -> bool:
    return "*" in value or value == "_all"


def _permission_review_risks(
    cluster_permissions: set[str],
    index_permissions: dict[tuple[str, ...], set[str]],
) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    destructive_fragments = (
        "/delete",
        "/write",
        "/reroute",
        "/settings/update",
        "/close",
        "/open",
    )
    for action in sorted(cluster_permissions):
        if _contains_wildcard(action):
            risks.append(
                {
                    "severity": "high",
                    "kind": "wildcard-action",
                    "value": action,
                    "message": "Wildcard cluster action requires explicit review.",
                }
            )
        if action.startswith("restapi:admin/"):
            risks.append(
                {
                    "severity": "high",
                    "kind": "security-administration",
                    "value": action,
                    "message": "This action can administer Security plugin resources.",
                }
            )
        if any(fragment in action for fragment in destructive_fragments):
            risks.append(
                {
                    "severity": "medium",
                    "kind": "state-changing-action",
                    "value": action,
                    "message": "This action can change cluster or resource state.",
                }
            )
    for patterns, actions in sorted(index_permissions.items()):
        for pattern in patterns:
            if _contains_wildcard(pattern):
                risks.append(
                    {
                        "severity": "review",
                        "kind": "wildcard-index-scope",
                        "value": pattern,
                        "message": "Confirm that this wildcard is the intended data boundary.",
                    }
                )
        for action in sorted(actions):
            if _contains_wildcard(action):
                risks.append(
                    {
                        "severity": "high",
                        "kind": "wildcard-action",
                        "value": action,
                        "message": "Wildcard index action requires explicit review.",
                    }
                )
            if any(fragment in action for fragment in destructive_fragments):
                risks.append(
                    {
                        "severity": "medium",
                        "kind": "state-changing-action",
                        "value": action,
                        "message": "This action can change indexed data or index state.",
                    }
                )
    return risks


def compile_role(
    workflow: dict[str, Any], evidence: Iterable[Evidence]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile a role candidate and an evidence/coverage report."""
    steps = validate_workflow(workflow)
    role_name = workflow.get("role_name") or f"{workflow['name']}-observed"
    if not isinstance(role_name, str) or not role_name.strip():
        raise WorkflowError("workflow.role_name must be a non-empty string")

    cluster_permissions: set[str] = set()
    index_permissions: dict[tuple[str, ...], set[str]] = {}
    observed: set[str] = set()
    negative_violations: list[str] = []
    unresolved_negative_probes: list[str] = []
    non_deriving_positive_probes: list[str] = []
    unknown_steps: list[str] = []
    unscoped_index_actions: list[dict[str, str]] = []
    provenance: dict[str, dict[str, set[str]]] = {}

    for item in evidence:
        step = steps.get(item.step_id)
        if step is None:
            unknown_steps.append(item.step_id)
            continue
        observed.add(item.step_id)
        if step.expect == "deny" and item.allowed is True:
            negative_violations.append(item.step_id)
        if step.expect == "deny":
            if item.allowed is None:
                unresolved_negative_probes.append(item.step_id)
            # Denied probes are assertions, never permission sources.
            continue
        if not item.missing_privileges:
            non_deriving_positive_probes.append(item.step_id)
        for action in item.missing_privileges:
            trace = provenance.setdefault(
                action, {"steps": set(), "sources": set(), "index_patterns": set()}
            )
            trace["steps"].add(step.step_id)
            trace["sources"].add(item.source)
            if _is_index_action(action):
                if not step.index_patterns:
                    unscoped_index_actions.append(
                        {"step_id": step.step_id, "action": action}
                    )
                    continue
                trace["index_patterns"].update(step.index_patterns)
                key = tuple(sorted(set(step.index_patterns)))
                index_permissions.setdefault(key, set()).add(action)
            else:
                cluster_permissions.add(action)

    candidate = {
        role_name: {
            "cluster_permissions": sorted(cluster_permissions),
            "index_permissions": [
                {
                    "index_patterns": list(patterns),
                    "allowed_actions": sorted(actions),
                    "dls": "",
                    "fls": [],
                    "masked_fields": [],
                }
                for patterns, actions in sorted(index_permissions.items())
            ],
            "tenant_permissions": workflow.get("tenant_permissions", []),
        }
    }

    all_values = list(cluster_permissions)
    for patterns, actions in index_permissions.items():
        all_values.extend(patterns)
        all_values.extend(actions)
    report = {
        "workflow": workflow["name"],
        "candidate_role": role_name,
        "evidence_model": "observed-minimum, not mathematically minimal",
        "observed_steps": sorted(observed),
        "unobserved_steps": sorted(set(steps) - observed),
        "unknown_evidence_steps": sorted(set(unknown_steps)),
        "negative_probe_violations": sorted(set(negative_violations)),
        "unresolved_negative_probes": sorted(set(unresolved_negative_probes)),
        "non_deriving_positive_probes": sorted(
            set(non_deriving_positive_probes)
        ),
        "unscoped_index_actions": unscoped_index_actions,
        "wildcards": sorted({value for value in all_values if _contains_wildcard(value)}),
        "permission_evidence": {
            action: {
                "steps": sorted(trace["steps"]),
                "sources": sorted(trace["sources"]),
                "index_patterns": sorted(trace["index_patterns"]),
            }
            for action, trace in sorted(provenance.items())
        },
        "review_risks": _permission_review_risks(
            cluster_permissions, index_permissions
        ),
        "safe_to_review": not (
            unknown_steps
            or negative_violations
            or unresolved_negative_probes
            or non_deriving_positive_probes
            or unscoped_index_actions
        ),
    }
    return candidate, report


def verify_workflow(
    workflow: dict[str, Any], evidence: Iterable[Evidence]
) -> dict[str, Any]:
    """Verify that allowed steps pass and denied steps remain blocked.

    Multiple observations for a step must agree. Conflicting observations are
    reported rather than resolved optimistically.
    """
    steps = validate_workflow(workflow)
    observations: dict[str, list[Evidence]] = {step_id: [] for step_id in steps}
    unknown_steps: set[str] = set()
    for item in evidence:
        if item.step_id not in steps:
            unknown_steps.add(item.step_id)
            continue
        observations[item.step_id].append(item)

    positive_failures: list[dict[str, Any]] = []
    negative_violations: list[dict[str, Any]] = []
    unresolved_steps: list[str] = []
    conflicting_steps: list[str] = []
    results: list[dict[str, Any]] = []

    for step_id, step in steps.items():
        records = observations[step_id]
        statuses = {record.allowed for record in records}
        missing = sorted(
            {
                action
                for record in records
                for action in record.missing_privileges
            }
        )
        if not records or statuses == {None}:
            outcome = "unresolved"
            unresolved_steps.append(step_id)
        elif len(statuses) > 1:
            outcome = "conflicting"
            conflicting_steps.append(step_id)
        else:
            allowed = next(iter(statuses))
            if step.expect == "allow" and allowed is not True:
                outcome = "failed-required"
                positive_failures.append(
                    {"step_id": step_id, "missing_privileges": missing}
                )
            elif step.expect == "deny" and allowed is not False:
                outcome = "allowed-forbidden"
                negative_violations.append({"step_id": step_id})
            else:
                outcome = "passed"
        results.append(
            {
                "step_id": step_id,
                "expect": step.expect,
                "outcome": outcome,
                "observations": len(records),
                "missing_privileges": missing,
            }
        )

    passed = not (
        positive_failures
        or negative_violations
        or unresolved_steps
        or conflicting_steps
        or unknown_steps
    )
    return {
        "workflow": workflow["name"],
        "passed": passed,
        "results": results,
        "positive_failures": positive_failures,
        "negative_probe_violations": negative_violations,
        "unresolved_steps": sorted(unresolved_steps),
        "conflicting_steps": sorted(conflicting_steps),
        "unknown_evidence_steps": sorted(unknown_steps),
    }
