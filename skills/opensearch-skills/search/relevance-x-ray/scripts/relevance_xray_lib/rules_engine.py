"""Evidence-gated anti-pattern rules bundled with Relevance X-Ray.

Each rule takes the index mapping/settings, the query, and the parsed
:class:`~relevance_xray_lib.explain_parser.ExplainSummary` for a document, and returns zero
or more :class:`Finding` objects. Rules are pure functions over plain data
structures — no OpenSearch client calls here — so they are fully unit
testable with fixture JSON.

Tags reuse the vocabulary already established by opensearch-launchpad's
evaluator (``lib/evaluate.py``) where the concept overlaps, so users see one
consistent tag taxonomy across both skills:

  [INDEX_MAPPING]   field types, analyzers, missing .keyword sub-fields
  [MODEL_SELECTION]  embedding/vector model or k-NN parameter issues
  [SEARCH_PIPELINE]  hybrid normalization/combination weighting
  [QUERY_TUNING]     boosts, unindexed fields, vocabulary/synonym gaps
"""

from __future__ import annotations

from dataclasses import dataclass

from .explain_parser import ExplainSummary


@dataclass
class Finding:
    rule: str
    tag: str
    severity: str  # HIGH | MEDIUM | LOW
    message: str
    fix: str
    confidence: str = "medium"  # high | medium | low
    evidence: tuple[str, ...] = ()


def _text_fields_without_keyword(mapping_properties: dict) -> set[str]:
    """Return top-level field names mapped as 'text' with no '.keyword' sibling."""
    result = set()
    for name, spec in (mapping_properties or {}).items():
        if not isinstance(spec, dict):
            continue
        if spec.get("type") == "text":
            parent_name = name.rsplit(".", 1)[0] if "." in name else ""
            parent_spec = (mapping_properties or {}).get(parent_name)
            if isinstance(parent_spec, dict) and parent_spec.get("type") == "keyword":
                continue
            fields = spec.get("fields") or {}
            has_keyword = any(
                isinstance(f, dict) and f.get("type") == "keyword" for f in fields.values()
            )
            if not has_keyword:
                result.add(name)
    return result


def check_missing_keyword_subfield(
    mapping_properties: dict, filter_or_exact_fields: list[str]
) -> list[Finding]:
    """Rule: query does exact/filter matching against a text-only field."""
    findings: list[Finding] = []
    missing = _text_fields_without_keyword(mapping_properties)
    for f in filter_or_exact_fields:
        field_name = f.split("^", 1)[0]
        if field_name in missing:
            findings.append(
                Finding(
                    rule="missing_keyword_subfield",
                    tag="[INDEX_MAPPING]",
                    severity="MEDIUM",
                    message=(
                        f"Field '{field_name}' is mapped as 'text' with no keyword "
                        f"sub-field, but the query uses it for exact/filter matching. "
                        "A term query can match an analyzed token, but this mapping "
                        "does not provide whole-value exact-match semantics."
                    ),
                    fix=(
                        f"Add a keyword sub-field to '{field_name}' and reindex, e.g.\n"
                        f'  "{field_name}": {{"type": "text", "fields": '
                        f'{{"keyword": {{"type": "keyword", "ignore_above": 256}}}}}}'
                    ),
                )
            )
    return findings


def check_analyzer_mismatch(analysis_by_field: dict) -> list[Finding]:
    """Detect analyzer divergence using actual ``_analyze``/term-vector tokens.

    A finding requires all of the following evidence for a field:
    the search analyzer's query tokens miss the target document, applying the
    index analyzer to the same query produces different tokens, and at least
    one of those index-analyzed tokens exists in the target's term vectors.
    """
    findings: list[Finding] = []
    for fld, evidence in (analysis_by_field or {}).items():
        search_tokens = {str(t) for t in evidence.get("search_tokens", [])}
        index_tokens = {str(t) for t in evidence.get("index_tokens", [])}
        target_tokens = {str(t) for t in evidence.get("target_tokens", [])}
        if not search_tokens or not index_tokens or not target_tokens:
            continue
        if search_tokens & target_tokens:
            continue
        recoverable_tokens = index_tokens & target_tokens
        if index_tokens != search_tokens and recoverable_tokens:
            findings.append(
                Finding(
                    rule="analyzer_mismatch",
                    tag="[INDEX_MAPPING]",
                    severity="MEDIUM",
                    confidence="high",
                    message=(
                        f"Field '{fld}' analyzes the query differently at search and index "
                        f"time. Search tokens {sorted(search_tokens)} miss the target, while "
                        f"index-time tokens {sorted(recoverable_tokens)} occur in its term vectors."
                    ),
                    fix=(
                        f"Align the 'analyzer' and 'search_analyzer' for '{fld}', then "
                        "reindex or re-run the query and compare the target rank."
                    ),
                    evidence=(
                        f"search_tokens={sorted(search_tokens)}",
                        f"index_tokens={sorted(index_tokens)}",
                        f"target_tokens={sorted(target_tokens)}",
                    ),
                )
            )
    return findings


def check_unindexed_scoring_field(
    referenced_fields: list[str], mapping_properties: dict
) -> list[Finding]:
    """Check whether a function/script field can be read for scoring.

    Script and ``field_value_factor`` access normally use doc values, so
    ``index: false`` alone is not an error. Flag only absent fields or fields
    with doc values explicitly disabled.
    """
    findings: list[Finding] = []
    for f in referenced_fields:
        field_name = f if f in (mapping_properties or {}) else f.split(".")[0]
        spec = (mapping_properties or {}).get(field_name)
        if spec is None:
            findings.append(
                Finding(
                    rule="unindexed_scoring_field",
                    tag="[QUERY_TUNING]",
                    severity="HIGH",
                    message=(
                        f"Field '{field_name}' is referenced in scoring but does not exist "
                        f"in the index mapping at all."
                    ),
                    fix=(
                        f"Fix the field reference, or add '{field_name}' to the mapping "
                        "and reindex."
                    ),
                    confidence="high",
                    evidence=(f"mapping field '{field_name}' is absent",),
                )
            )
        elif isinstance(spec, dict) and spec.get("doc_values") is False:
            findings.append(
                Finding(
                    rule="unindexed_scoring_field",
                    tag="[QUERY_TUNING]",
                    severity="HIGH",
                    message=(
                        f"Field '{field_name}' is referenced in scoring but has "
                        f"'doc_values: false', so doc-value-based scoring cannot read it."
                    ),
                    fix=(
                        f"Enable doc values for '{field_name}' and reindex, or rewrite the scoring "
                        "logic to use a supported value source."
                    ),
                    confidence="high",
                    evidence=(f"mapping '{field_name}.doc_values' is false",),
                )
            )
    return findings


def check_vocabulary_mismatch(
    query_terms: list[str], summary: ExplainSummary, co_occurring_terms: dict[str, set[str]]
) -> list[Finding]:
    """Rule: a query term did not match, but corpus evidence produced a
    candidate target term for a separate rank-validation experiment.
    """
    findings: list[Finding] = []
    matched_terms = {c.term.lower() for c in summary.contributions if c.term}
    for term in query_terms:
        term_lower = term.lower()
        if term_lower in matched_terms:
            continue
        candidates = co_occurring_terms.get(term_lower, set())
        if candidates:
            findings.append(
                Finding(
                    rule="vocabulary_mismatch",
                    tag="[QUERY_TUNING]",
                    severity="MEDIUM",
                    message=(
                        f"Query term '{term}' did not match this document, but other "
                        f"documents associate it with {sorted(candidates)}. "
                        f"The association is a candidate vocabulary "
                        f"gap, not proof that the terms are semantically equivalent."
                    ),
                    fix=(
                        f"Consider adding a synonym filter mapping '{term}' to "
                        f"{sorted(candidates)}. Run suggest-synonyms to validate."
                    ),
                    confidence="low",
                    evidence=(f"corpus candidates={sorted(candidates)}",),
                )
            )
    return findings


def check_knn_counterfactual(counterfactual: dict) -> list[Finding]:
    """Report weak approximate recall only after a measured parameter sweep."""
    before_rank = counterfactual.get("before_rank")
    after_rank = counterfactual.get("after_rank")
    if after_rank is None:
        return []
    improved = before_rank is None or after_rank < before_rank
    if not improved:
        return []
    before_params = counterfactual.get("before_params", {})
    after_params = counterfactual.get("after_params", {})
    if not before_params or set(before_params) != set(after_params):
        return []
    if any(not key.endswith(".ef_search") for key in before_params):
        return []
    if any(
        not isinstance(before_params[key], (int, float))
        or not isinstance(after_params[key], (int, float))
        or after_params[key] <= before_params[key]
        for key in before_params
    ):
        return []
    return [
        Finding(
            rule="weak_knn_recall",
            tag="[MODEL_SELECTION]",
            severity="MEDIUM",
            confidence="high",
            message=(
                "The target's rank improved in a controlled k-NN parameter sweep "
                f"({before_rank if before_rank is not None else 'outside top-k'} -> {after_rank})."
            ),
            fix=(
                f"Evaluate the higher-recall parameters {after_params} against latency and "
                "aggregate relevance before adopting them."
            ),
            evidence=(
                f"before_params={before_params}",
                f"after_params={after_params}",
                f"rank_delta={before_rank}->{after_rank}",
            ),
        )
    ]


def check_hybrid_leg_imbalance(
    normalized_contributions: dict[str, list[float]],
    configured_weights: dict[str, float],
) -> list[Finding]:
    """Flag a weighted hybrid leg only when measured normalized output is inert.

    Raw BM25 and vector scores are intentionally rejected here because their
    scales are not comparable before the search pipeline's normalization.
    """
    findings: list[Finding] = []
    for leg, values in (normalized_contributions or {}).items():
        weight = float((configured_weights or {}).get(leg, 0.0) or 0.0)
        if weight > 0 and values and all(float(value) == 0.0 for value in values):
            findings.append(
                Finding(
                    rule="hybrid_leg_imbalance",
                    tag="[SEARCH_PIPELINE]",
                    severity="MEDIUM",
                    confidence="high",
                    message=(
                        f"The '{leg}' leg has configured weight {weight:.3f} but its measured "
                        "normalized contribution is zero for every inspected result."
                    ),
                    fix=(
                        f"Inspect the '{leg}' query and normalization bounds before changing "
                        "weights; verify the fix on the same candidate set."
                    ),
                    evidence=(f"normalized_{leg}={values}",),
                )
            )
    return findings


def _has_complete_analyzer_evidence(analysis_by_field: dict) -> bool:
    return any(
        evidence.get("search_tokens")
        and evidence.get("index_tokens")
        and evidence.get("target_tokens")
        for evidence in (analysis_by_field or {}).values()
    )


def rule_coverage(context: dict) -> tuple[list[str], dict[str, str]]:
    """Return evaluated rules and an explicit reason for every skipped rule."""
    evaluated: list[str] = []
    skipped: dict[str, str] = {}
    if context.get("mapping_properties") is not None and context.get("filter_or_exact_fields"):
        evaluated.append("missing_keyword_subfield")
    else:
        skipped["missing_keyword_subfield"] = (
            "the query contained no term/terms exact-match clause"
            if context.get("mapping_properties") is not None
            else "index mapping evidence was unavailable"
        )
    if _has_complete_analyzer_evidence(context.get("analysis_by_field") or {}):
        evaluated.append("analyzer_mismatch")
    else:
        skipped["analyzer_mismatch"] = (
            "no field had complete index-token, search-token, and target-term-vector evidence"
        )
    if (
        context.get("referenced_fields")
        and context.get("mapping_properties") is not None
    ):
        evaluated.append("unindexed_scoring_field")
    else:
        skipped["unindexed_scoring_field"] = (
            "the query contained no scoring field reference"
            if context.get("mapping_properties") is not None
            else "index mapping evidence was unavailable"
        )
    if (
        context.get("query_terms")
        and context.get("summary")
        and context.get("co_occurring_terms") is not None
    ):
        evaluated.append("vocabulary_mismatch")
    else:
        skipped["vocabulary_mismatch"] = (
            "no corpus association evidence was collected; run suggest-synonyms"
        )
    if context.get("knn_counterfactual") is not None:
        evaluated.append("weak_knn_recall")
    else:
        skipped["weak_knn_recall"] = (
            "no controlled ef_search counterfactual was available"
        )
    if (
        context.get("hybrid_normalized_contributions") is not None
        and context.get("hybrid_weights") is not None
    ):
        evaluated.append("hybrid_leg_imbalance")
    else:
        skipped["hybrid_leg_imbalance"] = (
            "normalized per-leg contributions and configured weights were unavailable"
        )
    return evaluated, skipped


def evaluated_rule_names(context: dict) -> list[str]:
    """Return only rules for which the context contains sufficient evidence."""
    return rule_coverage(context)[0]


def run_all_rules(context: dict) -> list[Finding]:
    """Convenience entrypoint: run every applicable rule given a context dict.

    ``context`` keys (all optional — rules skip themselves if their inputs
    are missing):
        mapping_properties, filter_or_exact_fields, analysis_by_field,
        referenced_fields, query_terms, summary, co_occurring_terms,
        knn_counterfactual, hybrid_normalized_contributions, hybrid_weights
    """
    findings: list[Finding] = []

    if context.get("mapping_properties") is not None and context.get("filter_or_exact_fields"):
        findings += check_missing_keyword_subfield(
            context["mapping_properties"], context["filter_or_exact_fields"]
        )

    if _has_complete_analyzer_evidence(context.get("analysis_by_field") or {}):
        findings += check_analyzer_mismatch(context["analysis_by_field"])

    if context.get("referenced_fields") and context.get("mapping_properties") is not None:
        findings += check_unindexed_scoring_field(
            context["referenced_fields"], context["mapping_properties"]
        )

    if (
        context.get("query_terms")
        and context.get("summary")
        and context.get("co_occurring_terms") is not None
    ):
        findings += check_vocabulary_mismatch(
            context["query_terms"], context["summary"], context["co_occurring_terms"]
        )

    if context.get("knn_counterfactual") is not None:
        findings += check_knn_counterfactual(context["knn_counterfactual"])

    if (
        context.get("hybrid_normalized_contributions") is not None
        and context.get("hybrid_weights") is not None
    ):
        findings += check_hybrid_leg_imbalance(
            context["hybrid_normalized_contributions"],
            context["hybrid_weights"],
        )

    return findings
