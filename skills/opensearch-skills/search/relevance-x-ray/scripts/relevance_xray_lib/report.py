"""Render findings in the fixed human-readable Relevance X-Ray diagnosis
schema described in SKILL.md's "Output Format" section:

  1. Supported conclusion or abstention
  2. Evidence
  3. Coverage and limitations
  4. Fix or next measurement

Pure string formatting — no client calls, no I/O — so it is fully unit
testable.
"""

from __future__ import annotations

from .explain_parser import ExplainSummary, to_plain_english
from .rules_engine import Finding

_SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (
            _SEVERITY_ORDER.get(f.severity, 99),
            _CONFIDENCE_ORDER.get(f.confidence, 99),
        ),
    )


def build_diagnosis_report(
    index: str,
    query_text: str,
    doc_id: str,
    summary: ExplainSummary,
    findings: list[Finding],
    validation: dict | None = None,
    search_context: dict | None = None,
    evaluated_rules: list[str] | None = None,
    skipped_rules: dict[str, str] | None = None,
    limitations: list[str] | None = None,
    leg_summaries: dict[str, ExplainSummary] | None = None,
) -> str:
    """Render the full diagnosis as a plain-text report.

    ``validation`` is the dict returned by
    ``synonym_suggester.validate_synonym_candidate`` (or similar), included
    only when Step 5 of the workflow was actually run.
    """
    lines: list[str] = []
    lines.append(f"Relevance X-Ray — index '{index}', query '{query_text}', doc '{doc_id}'")
    lines.append("=" * 72)
    lines.append("")

    # Supported conclusion
    lines.append("SUPPORTED CONCLUSION")
    lines.append("-" * 72)
    if findings:
        top = _sorted_findings(findings)[0]
        lines.append(f"{top.tag} [{top.confidence.upper()} CONFIDENCE] {top.message}")
    elif summary.match_known and not summary.matched:
        lines.append("Observed: the target document did not match this query (score = 0).")
    else:
        lines.append(
            "No supported root cause was established from the evidence collected. "
            "This does not mean the ranking is correct."
        )
    lines.append("")

    # Evidence
    lines.append("EVIDENCE")
    lines.append("-" * 72)
    for line in to_plain_english(summary):
        lines.append(f"  - {line}")
    if search_context:
        target_rank = search_context.get("target_rank")
        top_k = search_context.get("top_k")
        rank_text = str(target_rank) if target_rank is not None else f"outside top-{top_k}"
        lines.append(f"  - Observed target rank: {rank_text}.")
        for hit in search_context.get("top_hits", [])[:3]:
            lines.append(
                f"  - Competing hit rank {hit.get('rank')}: doc '{hit.get('id')}', "
                f"score={hit.get('score')}."
            )
            if hit.get("score_evidence"):
                lines.append(f"    Evidence: {hit['score_evidence']}")
    for leg_name, leg_summary in (leg_summaries or {}).items():
        lines.append(
            f"  - Raw '{leg_name}' leg explain score: {leg_summary.total_score:.3f} "
            "(not a normalized hybrid contribution)."
        )
    for finding in _sorted_findings(findings):
        for item in finding.evidence:
            lines.append(f"  - {finding.rule}: {item}")
    lines.append("")

    lines.append("COVERAGE")
    lines.append("-" * 72)
    if evaluated_rules:
        lines.append(f"  Evaluated rules: {', '.join(evaluated_rules)}")
    else:
        lines.append("  No diagnostic rule had sufficient evidence to run.")
    for rule, reason in (skipped_rules or {}).items():
        lines.append(f"  Skipped rule: {rule} ({reason}).")
    for limitation in limitations or []:
        lines.append(f"  Limitation: {limitation}")
    lines.append("")

    # All findings (fix section)
    lines.append("FIX" if len(findings) <= 1 else "FIXES")
    lines.append("-" * 72)
    if not findings:
        lines.append(
            "  No automatic fix is justified yet. Collect the missing evidence or "
            "run a controlled counterfactual before changing production relevance."
        )
    else:
        for f in _sorted_findings(findings):
            lines.append(
                f"  [{f.severity}] {f.tag} {f.rule} ({f.confidence} confidence)"
            )
            lines.append(f"    {f.fix}")
    lines.append("")

    # Validation
    if validation:
        lines.append("VALIDATED IMPACT")
        lines.append("-" * 72)
        before_rank = validation.get("before_rank")
        after_rank = validation.get("after_rank")
        candidate = validation.get("candidate")
        query_term = validation.get("query_term")
        lines.append(
            f"  OR-expanding '{query_term}' with '{candidate}': "
            f"rank {before_rank if before_rank is not None else 'not in top-k'} -> "
            f"{after_rank if after_rank is not None else 'not in top-k'} "
            f"({'improved' if validation.get('improved') else 'no improvement'})"
        )
        lines.append("")

    return "\n".join(lines)


def build_findings_table(findings: list[Finding]) -> str:
    """Compact table rendering, e.g. for batch/summary views."""
    if not findings:
        return "No findings."
    header = f"{'Severity':<8} {'Tag':<20} {'Rule':<28} Fix"
    rows = [header, "-" * len(header)]
    for f in _sorted_findings(findings):
        rows.append(f"{f.severity:<8} {f.tag:<20} {f.rule:<28} {f.fix}")
    return "\n".join(rows)
