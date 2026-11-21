"""Tests for the bundled Relevance X-Ray explain parser."""

import sys
from pathlib import Path

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "search"
    / "relevance-x-ray"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

from relevance_xray_lib.explain_parser import (
    missing_query_fields,
    parse_explain,
    to_plain_english,
    top_contributions,
)


def _term_match_node(field, term, value):
    return {
        "value": value,
        "description": f"weight({field}:{term} in 0) [PerFieldSimilarity], result of:",
        "details": [],
    }


def test_parse_explain_unmatched_document():
    summary = parse_explain({"value": 0.0, "description": "no matching term", "details": []})
    assert summary.matched is False
    assert summary.total_score == 0.0
    assert summary.contributions == []


def test_parse_explain_empty_node():
    summary = parse_explain({})
    assert summary.matched is False
    assert summary.total_score == 0.0


def test_parse_explain_simple_term_match():
    node = {
        "value": 1.23,
        "description": "sum of:",
        "details": [_term_match_node("title", "wireless", 0.9), _term_match_node("description", "charger", 0.33)],
    }
    summary = parse_explain(node)
    assert summary.matched is True
    assert summary.total_score == 1.23
    assert summary.fields_matched == {"title", "description"}
    assert summary.bm25_score is not None
    # combiner node ("sum of:") should not itself be recorded as a contribution
    assert all(c.description != "sum of:" for c in summary.contributions)


def test_parse_explain_categorizes_knn():
    node = {
        "value": 0.87,
        "description": "within top k documents",
        "details": [
            {
                "value": 0.87,
                "description": "KnnScoreDocQuery [0]",
                "details": [],
            }
        ],
    }
    summary = parse_explain(node)
    assert summary.knn_score == 0.87
    assert summary.bm25_score is None


def test_parse_explain_hybrid_detected_when_both_legs_present():
    node = {
        "value": 1.5,
        "description": "sum of:",
        "details": [
            _term_match_node("title", "wireless", 0.9),
            {"value": 0.6, "description": "KnnScoreDocQuery [0]", "details": []},
        ],
    }
    summary = parse_explain(node)
    assert summary.is_hybrid is True
    assert summary.bm25_score == 0.9
    assert summary.knn_score == 0.6


def test_top_contributions_limits_and_sorts_descending():
    node = {
        "value": 2.0,
        "description": "sum of:",
        "details": [
            _term_match_node("title", "a", 0.1),
            _term_match_node("title", "b", 1.5),
            _term_match_node("title", "c", 0.4),
        ],
    }
    summary = parse_explain(node)
    top = top_contributions(summary, limit=2)
    assert len(top) == 2
    assert top[0].value == 1.5
    assert top[1].value == 0.4


def test_missing_query_fields_reports_absent_fields():
    node = {
        "value": 0.5,
        "description": "sum of:",
        "details": [_term_match_node("title", "wireless", 0.5)],
    }
    summary = parse_explain(node)
    missing = missing_query_fields(summary, ["title", "description", "brand"])
    assert missing == ["description", "brand"]


def test_to_plain_english_unmatched():
    summary = parse_explain({"value": 0.0, "description": "no match", "details": []})
    lines = to_plain_english(summary)
    assert len(lines) == 1
    assert "did not match" in lines[0]


def test_to_plain_english_describes_term_match():
    node = {
        "value": 0.9,
        "description": "sum of:",
        "details": [_term_match_node("title", "wireless", 0.9)],
    }
    summary = parse_explain(node)
    lines = to_plain_english(summary)
    assert any("wireless" in line and "title" in line for line in lines)


def test_non_additive_factors_are_not_ranked_as_contributions():
    node = {
        "value": 0.6,
        "description": "weight(title:wireless in 0) [PerFieldSimilarity], result of:",
        "details": [
            {
                "value": 0.6,
                "description": "score(freq=1.0), computed as boost * idf * tf from:",
                "details": [
                    {"value": 2.0, "description": "boost of 2.0", "details": []},
                    {"value": 0.3, "description": "idf, computed as log", "details": []},
                    {"value": 1.0, "description": "tf, computed as freq", "details": []},
                ],
            }
        ],
    }
    summary = parse_explain(node)
    assert [c.value for c in summary.contributions] == [0.6]
    assert {factor.category for factor in summary.factors} == {"boost", "idf", "tf"}
    assert all(factor.role == "factor" for factor in summary.factors)
    lines = to_plain_english(summary)
    assert any("not a separate contribution" in line for line in lines)


def test_function_score_max_boost_sentinel_is_not_reported_as_factor():
    node = {
        "value": 1.0,
        "description": "function score, product of:",
        "details": [
            _term_match_node("title", "wireless", 1.0),
            {
                "value": 3.4028235e38,
                "description": "maxBoost",
                "details": [],
            },
        ],
    }
    summary = parse_explain(node)
    assert all(factor.description != "maxBoost" for factor in summary.factors)
    assert "340282" not in "\n".join(to_plain_english(summary))


def test_max_combiner_does_not_sum_sibling_scores():
    node = {
        "value": 1.5,
        "description": "max of:",
        "details": [
            _term_match_node("title", "wireless", 1.5),
            _term_match_node("description", "wireless", 0.9),
        ],
    }
    summary = parse_explain(node)
    assert summary.root_operation == "max"
    assert summary.bm25_score == 1.5


def test_nested_max_clauses_are_not_described_as_additive():
    node = {
        "value": 1.5,
        "description": "sum of:",
        "details": [{
            "value": 1.5,
            "description": "max of:",
            "details": [
                _term_match_node("title", "wireless", 1.5),
                _term_match_node("description", "wireless", 0.9),
            ],
        }],
    }
    summary = parse_explain(node)
    assert summary.bm25_score is None
    assert all(c.operators == ("sum", "max") for c in summary.contributions)
    assert all("contributed" not in line for line in to_plain_english(summary))


def test_single_clause_under_nested_max_abstains_from_additive_score():
    node = {
        "value": 1.5,
        "description": "sum of:",
        "details": [{
            "value": 1.5,
            "description": "max of:",
            "details": [_term_match_node("title", "wireless", 1.5)],
        }],
    }

    summary = parse_explain(node)

    assert summary.bm25_score is None


def test_deep_explain_tree_is_truncated_without_recursion_error():
    node = _term_match_node("title", "wireless", 1.0)
    for _ in range(100):
        node = {"value": 1.0, "description": "sum of:", "details": [node]}
    summary = parse_explain(node, max_depth=20)
    assert summary.traversal_truncated is True
