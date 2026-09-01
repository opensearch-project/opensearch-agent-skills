"""Parse OpenSearch ``_explain`` trees while preserving score semantics.

The raw explain tree looks like:

    {
      "value": 1.23,
      "description": "sum of:",
      "details": [
        {"value": 0.9, "description": "weight(title:wireless in 0) [...]", "details": [...]},
        {"value": 0.3, "description": "weight(description:charger in 0) [...]", "details": [...]}
      ]
    }

Explain values are not uniformly additive. Some nodes are sums or maxima,
while others are multiplicative factors such as IDF, TF, and boosts. This
module keeps those roles separate so callers do not present a factor as an
independent contribution to the final score.

No network calls, no OpenSearch client dependency — pure data transformation,
so it is safe to unit test without a live cluster.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Category detection -----------------------------------------------------
#
# OpenSearch/Lucene explain "description" strings are stable-ish across
# versions for the common scorers we care about. We match on substrings
# rather than full-string equality since exact wording carries parameters
# (field names, term text) that vary per call.

_TERM_MATCH_RE = re.compile(r"weight\((?P<field>[\w.\-]+):(?P<term>.+?) in \d+\)")
_FUNCTION_SCORE_HINTS = ("function score", "FunctionScoreQuery")
_KNN_HINTS = ("KnnScoreDocQuery", "knn", "vector")
_CONSTANT_SCORE_HINTS = ("ConstantScoreQuery", "ConstantScoreScorer")
_BOOST_RE = re.compile(r"boost of ([\d.]+)", re.IGNORECASE)
_IDF_HINTS = ("idf, computed as", "inverse document frequency")
_TF_HINTS = ("tf, computed as", "term frequency")
_FIELD_NORM_HINTS = ("fieldNorm", "field norm", "avgFieldLength", "fieldLength")
_HYBRID_HINTS = ("hybrid", "normalization processor", "combination technique")
MAX_EXPLAIN_DEPTH = 50


@dataclass
class Contribution:
    """One attributable score clause or non-additive scoring factor."""

    value: float
    description: str
    category: str
    field: str | None = None
    term: str | None = None
    depth: int = 0
    role: str = "score_clause"  # score_clause | factor
    path: tuple[int, ...] = ()
    operators: tuple[str, ...] = ()


@dataclass
class ExplainSummary:
    """Structured summary of a full explain tree for one document."""

    total_score: float
    matched: bool
    match_known: bool = True
    contributions: list[Contribution] = field(default_factory=list)
    factors: list[Contribution] = field(default_factory=list)
    knn_score: float | None = None
    bm25_score: float | None = None
    is_hybrid: bool = False
    fields_matched: set[str] = field(default_factory=set)
    fields_referenced_but_unmatched: set[str] = field(default_factory=set)
    root_operation: str | None = None
    traversal_truncated: bool = False


def _categorize(description: str) -> str:
    desc = description or ""
    lowered = desc.lower()
    if _TERM_MATCH_RE.search(desc):
        return "term_match"
    if any(h.lower() in lowered for h in _KNN_HINTS):
        return "knn"
    if any(h.lower() in lowered for h in _FUNCTION_SCORE_HINTS):
        return "function_score"
    if any(h.lower() in lowered for h in _CONSTANT_SCORE_HINTS):
        return "constant_score"
    if any(h.lower() in lowered for h in _HYBRID_HINTS):
        return "hybrid"
    if any(h.lower() in lowered for h in _IDF_HINTS):
        return "idf"
    if any(h.lower() in lowered for h in _TF_HINTS):
        return "tf"
    if any(h.lower() in lowered for h in _FIELD_NORM_HINTS):
        return "field_norm"
    if _BOOST_RE.search(desc) or lowered.strip() == "boost":
        return "boost"
    if desc.strip() in ("sum of:", "max of:", "product of:"):
        return "combiner"
    return "other"


def _operation(description: str) -> str | None:
    normalized = (description or "").strip().lower()
    if normalized.startswith("sum of"):
        return "sum"
    if normalized.startswith("max of"):
        return "max"
    if normalized.startswith("product of"):
        return "product"
    return None


def _walk(
    node: dict,
    depth: int,
    path: tuple[int, ...],
    score_clauses: list[Contribution],
    factors: list[Contribution],
    matched_fields: set[str],
    inside_score_clause: bool = False,
    operators: tuple[str, ...] = (),
    max_depth: int = MAX_EXPLAIN_DEPTH,
) -> bool:
    if not isinstance(node, dict):
        return False
    value = float(node.get("value", 0.0) or 0.0)
    description = node.get("description", "") or ""
    category = _categorize(description)
    operation = _operation(description)
    child_operators = operators + ((operation,) if operation else ())

    field_name = None
    term = None
    m = _TERM_MATCH_RE.search(description)
    if m:
        field_name = m.group("field")
        term = m.group("term")
        matched_fields.add(field_name)

    factor_categories = {"boost", "idf", "tf", "field_norm"}
    score_categories = {"term_match", "function_score", "knn", "constant_score"}

    if category in factor_categories:
        factors.append(
            Contribution(
                value=value,
                description=description,
                category=category,
                field=field_name,
                term=term,
                depth=depth,
                role="factor",
                path=path,
                operators=operators,
            )
        )
    elif category in score_categories and not inside_score_clause:
        score_clauses.append(
            Contribution(
                value=value,
                description=description,
                category=category,
                field=field_name,
                term=term,
                depth=depth,
                role="score_clause",
                path=path,
                operators=operators,
            )
        )
        inside_score_clause = True

    children = node.get("details", []) or []
    if depth >= max_depth:
        return bool(children)

    truncated = False
    for index, child in enumerate(children):
        truncated = _walk(
            child,
            depth + 1,
            path + (index,),
            score_clauses,
            factors,
            matched_fields,
            inside_score_clause=inside_score_clause,
            operators=child_operators,
            max_depth=max_depth,
        ) or truncated
    return truncated


def _combine(values: list[float], operation: str | None) -> float | None:
    """Combine sibling clause values only when the explain operator is known."""
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    if operation == "sum":
        return sum(values)
    if operation == "max":
        return max(values)
    if operation == "product":
        result = 1.0
        for value in values:
            result *= value
        return result
    return None


def _combine_category(
    contributions: list[Contribution],
    category: str,
    root_operation: str | None,
) -> float | None:
    clauses = [c for c in contributions if c.category == category]
    if not clauses:
        return None
    if len(clauses) == 1:
        if any(operation != "sum" for operation in clauses[0].operators):
            return None
        return clauses[0].value
    if not root_operation:
        return None
    if any(clause.operators != (root_operation,) for clause in clauses):
        return None
    return _combine([clause.value for clause in clauses], root_operation)


def parse_explain(
    explain_node: dict,
    doc_matched: bool | None = None,
    *,
    max_depth: int = MAX_EXPLAIN_DEPTH,
) -> ExplainSummary:
    """Parse a single document's explain tree into an :class:`ExplainSummary`.

    Args:
        explain_node: the ``explanation`` object as returned by OpenSearch's
            ``_explain`` endpoint, or the ``_explanation`` field on a hit
            from ``_search`` with ``explain=true``.
        doc_matched: override for whether the document matched at all.
            When ``None``, inferred from ``explain_node['value'] > 0``, since
            not every explain payload carries a ``"match"`` field verbatim.

    Returns:
        An :class:`ExplainSummary` with categorized contributions.
    """
    if not explain_node:
        return ExplainSummary(total_score=0.0, matched=False)

    total_score = float(explain_node.get("value", 0.0) or 0.0)
    matched = doc_matched if doc_matched is not None else total_score > 0.0

    contributions: list[Contribution] = []
    factors: list[Contribution] = []
    fields_matched: set[str] = set()
    traversal_truncated = _walk(
        explain_node,
        0,
        (),
        contributions,
        factors,
        fields_matched,
        max_depth=max_depth,
    )

    knn_scores = [c.value for c in contributions if c.category == "knn"]
    term_scores = [c.value for c in contributions if c.category == "term_match"]
    root_operation = _operation(explain_node.get("description", ""))
    is_hybrid = any(c.category == "hybrid" for c in contributions) or (
        bool(knn_scores) and bool(term_scores)
    )

    return ExplainSummary(
        total_score=total_score,
        matched=matched,
        contributions=contributions,
        factors=factors,
        knn_score=_combine_category(contributions, "knn", root_operation),
        bm25_score=_combine_category(contributions, "term_match", root_operation),
        is_hybrid=is_hybrid,
        fields_matched=fields_matched,
        root_operation=root_operation,
        traversal_truncated=traversal_truncated,
    )


def top_contributions(summary: ExplainSummary, limit: int = 5) -> list[Contribution]:
    """Return the highest-value attributable score clauses."""
    ranked = sorted(summary.contributions, key=lambda c: c.value, reverse=True)
    return ranked[:limit]


def missing_query_fields(summary: ExplainSummary, expected_fields: list[str]) -> list[str]:
    """Return expected query fields that never appear in the explain tree.

    Useful for spotting "the query targeted field X but nothing in the
    explain tree ever matched against X" — a common root cause for
    surprising rankings.
    """
    return [f for f in expected_fields if f not in summary.fields_matched]


def to_plain_english(summary: ExplainSummary) -> list[str]:
    """Render the top contributions as short, human-readable sentences.

    This is intentionally simple/deterministic (no LLM call) so it is fully
    unit-testable; the calling skill/agent is expected to further compose
    these lines into the final narrative response.
    """
    lines: list[str] = []
    if not summary.match_known:
        lines.append("The target's match status is unknown from the available explain data.")
        return lines
    if not summary.matched:
        lines.append("The document did not match the query at all (score = 0).")
        return lines

    for c in top_contributions(summary, limit=5):
        additive = bool(c.operators) and all(operator == "sum" for operator in c.operators)
        value_phrase = (
            f"contributed {c.value:.3f} to the score"
            if additive
            else f"has explain value {c.value:.3f}"
        )
        if c.category == "term_match" and c.field and c.term:
            lines.append(
                f"Matched term '{c.term}' in field '{c.field}' and {value_phrase}."
            )
        elif c.category == "knn":
            lines.append(f"The vector (k-NN) clause {value_phrase}.")
        elif c.category == "function_score":
            lines.append(f"The function_score clause {value_phrase}.")
        elif c.category == "constant_score":
            lines.append(f"The constant/filter clause {value_phrase}.")
        else:
            lines.append(f"'{c.description.strip()}' {value_phrase}.")

    for factor in sorted(summary.factors, key=lambda c: c.depth)[:3]:
        lines.append(
            f"Non-additive {factor.category} factor = {factor.value:.3f}; "
            "it is an input to its parent score, not a separate contribution."
        )
    return lines
