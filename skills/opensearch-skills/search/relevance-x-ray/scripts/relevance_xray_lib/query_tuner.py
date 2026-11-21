"""Generate and validate small query changes from pairwise judgments."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .relevance_diagnostics import flatten_mapping, inspect_query

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_FIELD_RE = re.compile(r"^(?P<field>.+?)(?:\^(?P<boost>[0-9.]+))?$")
_TEXT_FIELD_TYPES = {"text", "match_only_text", "search_as_you_type"}


@dataclass(frozen=True)
class QueryCandidate:
    name: str
    search_body: dict
    changes: tuple[str, ...]
    rationale: str


def query_fingerprint(search_body: dict) -> str:
    """Return a stable identity for the exact baseline search body."""
    encoded = json.dumps(
        search_body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def load_judgments(path: str | Path) -> list[dict]:
    """Load a JSON list or JSONL judgment file."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list):
            raise ValueError("Judgments JSON must be a list.")
        return [item for item in value if isinstance(item, dict)]
    return [
        value
        for line in text.splitlines()
        if line.strip()
        for value in [json.loads(line)]
        if isinstance(value, dict)
    ]


def normalize_judgments(
    judgments: list[dict],
    baseline_fingerprint: str | None = None,
) -> list[dict]:
    """Retain usable pairwise preferences for this exact baseline."""
    normalized: list[dict] = []
    for item in judgments:
        if item.get("type", "pairwise") != "pairwise":
            continue
        preferred = str(item.get("preferred_doc_id", "")).strip()
        rejected = str(item.get("rejected_doc_id", "")).strip()
        if not preferred or not rejected or preferred == rejected:
            continue
        item_fingerprint = str(item.get("baseline_fingerprint", "")).strip()
        if (
            baseline_fingerprint
            and item_fingerprint
            and item_fingerprint != baseline_fingerprint
        ):
            continue
        normalized.append(
            {
                "preferred_doc_id": preferred,
                "rejected_doc_id": rejected,
                "reason": str(item.get("reason", "")).strip(),
            }
        )
    return normalized


def _tokens(value: object) -> set[str]:
    return set(_TOKEN_RE.findall(str(value or "").lower()))


def _query_terms(search_body: dict) -> set[str]:
    metadata = inspect_query(search_body.get("query") or {})
    return {
        token
        for value in metadata.query_terms
        for token in _tokens(value)
    }


def _iter_nodes(value: object, path: tuple[object, ...] = ()):
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from _iter_nodes(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_nodes(child, path + (index,))


def _resolve(root: object, path: tuple[object, ...]):
    current = root
    for part in path:
        current = current[part]
    return current


def _multi_match_fields(search_body: dict) -> set[str]:
    fields: set[str] = set()
    for _, node in _iter_nodes(search_body.get("query") or {}):
        clause = node.get("multi_match")
        if not isinstance(clause, dict):
            continue
        for value in clause.get("fields") or []:
            if not isinstance(value, str):
                continue
            match = _FIELD_RE.match(value)
            if match:
                fields.add(match.group("field"))
    return fields


def _boost_field(search_body: dict, field_name: str, increment: float = 1.0) -> tuple[dict, list[str]]:
    candidate = copy.deepcopy(search_body)
    changes: list[str] = []
    for _, node in _iter_nodes(candidate.get("query") or {}):
        clause = node.get("multi_match")
        if not isinstance(clause, dict):
            continue
        updated_fields: list[object] = []
        for value in clause.get("fields") or []:
            if not isinstance(value, str):
                updated_fields.append(value)
                continue
            match = _FIELD_RE.match(value)
            if not match or match.group("field") != field_name:
                updated_fields.append(value)
                continue
            before = float(match.group("boost") or 1.0)
            after = before + increment
            updated_fields.append(f"{field_name}^{after:g}")
            changes.append(f"Increase '{field_name}' boost from {before:g} to {after:g}.")
        clause["fields"] = updated_fields
    return candidate, list(dict.fromkeys(changes))


def _field_support(
    documents: dict[str, dict],
    judgments: list[dict],
    query_terms: set[str],
    field_name: str,
) -> int:
    support = 0
    for judgment in judgments:
        preferred = documents.get(judgment["preferred_doc_id"], {})
        rejected = documents.get(judgment["rejected_doc_id"], {})
        preferred_matches = len(_tokens(preferred.get(field_name)) & query_terms)
        rejected_matches = len(_tokens(rejected.get(field_name)) & query_terms)
        support += preferred_matches - rejected_matches
    return support


def propose_query_candidates(
    search_body: dict,
    judgments: list[dict],
    documents: dict[str, dict],
    mapping_properties: dict,
) -> list[QueryCandidate]:
    """Generate conservative candidates without claiming they improve relevance."""
    if not isinstance(search_body, dict) or not isinstance(search_body.get("query"), dict):
        raise ValueError("Baseline must be a complete search body with a query object.")

    fingerprint = query_fingerprint(search_body)
    usable_judgments = normalize_judgments(judgments, fingerprint)
    if not usable_judgments:
        return []

    candidates: list[QueryCandidate] = []
    flattened_mapping = flatten_mapping(mapping_properties)
    query_terms = _query_terms(search_body)

    for field_name in sorted(_multi_match_fields(search_body)):
        mapping = flattened_mapping.get(field_name)
        if not isinstance(mapping, dict) or mapping.get("type") not in _TEXT_FIELD_TYPES:
            continue
        support = _field_support(
            documents,
            usable_judgments,
            query_terms,
            field_name,
        )
        if support <= 0:
            continue
        candidate_body, changes = _boost_field(search_body, field_name)
        if changes:
            candidates.append(
                QueryCandidate(
                    name=f"boost-{field_name.replace('.', '-')}",
                    search_body=candidate_body,
                    changes=tuple(changes),
                    rationale=(
                        f"Preferred documents have {support} more judged query-term "
                        f"matches in '{field_name}' than rejected documents."
                    ),
                )
            )

    for path, node in _iter_nodes(search_body.get("query") or {}):
        function_score = node.get("function_score")
        if not isinstance(function_score, dict):
            continue
        if function_score.get("boost_mode") != "replace":
            continue

        preserve_lexical = copy.deepcopy(search_body)
        target = _resolve(preserve_lexical["query"], path)["function_score"]
        target["boost_mode"] = "sum"
        candidates.append(
            QueryCandidate(
                name="preserve-lexical-score",
                search_body=preserve_lexical,
                changes=("Change function_score boost_mode from 'replace' to 'sum'.",),
                rationale=(
                    "The baseline discards the lexical score. Preserve it before "
                    "evaluating the existing function signal."
                ),
            )
        )

        field_value_factor = function_score.get("field_value_factor")
        factor = (
            field_value_factor.get("factor", 1.0)
            if isinstance(field_value_factor, dict)
            else None
        )
        if not isinstance(factor, (int, float)) or factor <= 0:
            continue
        for divisor in (10.0, 100.0):
            tempered = copy.deepcopy(search_body)
            target = _resolve(tempered["query"], path)["function_score"]
            target["boost_mode"] = "sum"
            next_factor = factor / divisor
            target["field_value_factor"]["factor"] = next_factor
            candidates.append(
                QueryCandidate(
                    name=f"temper-function-score-{next_factor:g}",
                    search_body=tempered,
                    changes=(
                        "Change function_score boost_mode from 'replace' to 'sum'.",
                        f"Reduce field_value_factor factor from {factor:g} to {next_factor:g}.",
                    ),
                    rationale=(
                        "Preserve lexical relevance and test a lower contribution from "
                        "the already-configured numeric signal."
                    ),
                )
            )

    unique: dict[str, QueryCandidate] = {}
    for candidate in candidates:
        unique.setdefault(query_fingerprint(candidate.search_body), candidate)
    return list(unique.values())


def _rank(hits: list[dict], doc_id: str) -> int | None:
    for rank, hit in enumerate(hits, start=1):
        if str(hit.get("_id")) == str(doc_id):
            return rank
    return None


def _precedes(preferred_rank: int | None, rejected_rank: int | None) -> bool:
    if preferred_rank is None:
        return False
    return rejected_rank is None or preferred_rank < rejected_rank


def _safe_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    suffix = f" (HTTP {status})" if status is not None else ""
    return f"{type(exc).__name__}{suffix}"


def validate_query_candidates(
    search_body: dict,
    candidates: list[QueryCandidate],
    judgments: list[dict],
    search_fn: Callable[[dict], list[dict]],
) -> dict:
    """Select only a candidate that improves judgments without regression."""
    fingerprint = query_fingerprint(search_body)
    usable_judgments = normalize_judgments(judgments, fingerprint)
    baseline_hits = search_fn(copy.deepcopy(search_body))

    baseline_outcomes: list[dict] = []
    for judgment in usable_judgments:
        preferred_rank = _rank(baseline_hits, judgment["preferred_doc_id"])
        rejected_rank = _rank(baseline_hits, judgment["rejected_doc_id"])
        baseline_outcomes.append(
            {
                **judgment,
                "preferred_rank": preferred_rank,
                "rejected_rank": rejected_rank,
                "satisfied": _precedes(preferred_rank, rejected_rank),
            }
        )

    evaluated: list[dict] = []
    for candidate in candidates:
        try:
            hits = search_fn(copy.deepcopy(candidate.search_body))
            error = None
        except Exception as exc:
            hits = []
            error = _safe_error(exc)

        outcomes: list[dict] = []
        improved = 0
        regressed = 0
        for judgment, baseline in zip(usable_judgments, baseline_outcomes):
            preferred_rank = _rank(hits, judgment["preferred_doc_id"]) if not error else None
            rejected_rank = _rank(hits, judgment["rejected_doc_id"]) if not error else None
            satisfied = _precedes(preferred_rank, rejected_rank) if not error else False
            improved += int(not baseline["satisfied"] and satisfied)
            regressed += int(baseline["satisfied"] and not satisfied)
            outcomes.append(
                {
                    **judgment,
                    "before": {
                        "preferred_rank": baseline["preferred_rank"],
                        "rejected_rank": baseline["rejected_rank"],
                        "satisfied": baseline["satisfied"],
                    },
                    "after": {
                        "preferred_rank": preferred_rank,
                        "rejected_rank": rejected_rank,
                        "satisfied": satisfied,
                    },
                }
            )

        evaluated.append(
            {
                "name": candidate.name,
                "query": candidate.search_body,
                "query_fingerprint": query_fingerprint(candidate.search_body),
                "changes": list(candidate.changes),
                "rationale": candidate.rationale,
                "improved_judgments": improved,
                "regressed_judgments": regressed,
                "accepted": bool(usable_judgments) and improved > 0 and regressed == 0 and not error,
                "error": error,
                "outcomes": outcomes,
            }
        )

    accepted = [item for item in evaluated if item["accepted"]]
    accepted.sort(
        key=lambda item: (
            -item["improved_judgments"],
            len(item["changes"]),
        )
    )
    selected = accepted[0] if accepted else None
    return {
        "baseline_query": copy.deepcopy(search_body),
        "baseline_fingerprint": fingerprint,
        "judgment_count": len(usable_judgments),
        "baseline_outcomes": baseline_outcomes,
        "candidates": evaluated,
        "selected": selected,
    }
