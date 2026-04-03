"""Tests for skills/opensearch-skills/scripts/lib/evaluate.py"""

import math
import sys
from pathlib import Path

import pytest

_LIB_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_LIB_DIR))

from lib.evaluate import (
    GRADE_LABELS,
    bar,
    compute_query_metrics,
    dcg,
    diagnose_query,
    evaluate_results,
    format_completion,
    format_findings,
    format_report,
    mrr,
    ndcg,
    precision_at_k,
    star_rating,
)


# ---------------------------------------------------------------------------
# Visual helpers
# ---------------------------------------------------------------------------


def test_star_rating_perfect():
    assert star_rating(1.0) == "★★★★★"


def test_star_rating_strong():
    assert star_rating(0.85) == "★★★★☆"


def test_star_rating_adequate():
    assert star_rating(0.55) == "★★★☆☆"


def test_star_rating_weak():
    assert star_rating(0.30) == "★★☆☆☆"


def test_star_rating_poor():
    assert star_rating(0.10) == "★☆☆☆☆"


def test_star_rating_zero():
    assert star_rating(0.0) == "✗ 0.00"


def test_bar_full():
    assert bar(1.0) == "██████████"


def test_bar_empty():
    assert bar(0.0) == "░░░░░░░░░░"


def test_bar_half():
    result = bar(0.5)
    assert result.count("█") == 5
    assert result.count("░") == 5


def test_bar_custom_width():
    result = bar(0.5, width=4)
    assert len(result) == 4


def test_grade_labels():
    assert GRADE_LABELS[3] == "perfect"
    assert GRADE_LABELS[2] == "relevant"
    assert GRADE_LABELS[1] == "marginal"
    assert GRADE_LABELS[0] == ""


# ---------------------------------------------------------------------------
# Metrics: dcg
# ---------------------------------------------------------------------------


def test_dcg_perfect_single():
    assert dcg([3], 1) == pytest.approx(3.0)


def test_dcg_two_items():
    result = dcg([3, 2], 2)
    assert result == pytest.approx(3.0 + 2.0 / math.log2(3))


def test_dcg_with_zeros():
    assert dcg([0, 0, 3], 3) == pytest.approx(3.0 / math.log2(4))


def test_dcg_respects_k():
    assert dcg([3, 2, 1], 1) == pytest.approx(3.0)


def test_dcg_empty():
    assert dcg([], 5) == 0.0


# ---------------------------------------------------------------------------
# Metrics: ndcg
# ---------------------------------------------------------------------------


def test_ndcg_perfect_ranking():
    assert ndcg([3, 2, 1], [3, 2, 1], 3) == pytest.approx(1.0)


def test_ndcg_worst_ranking():
    assert ndcg([0, 0, 0], [3], 3) == pytest.approx(0.0)


def test_ndcg_reversed_ranking():
    score = ndcg([1, 2, 3], [3, 2, 1], 3)
    assert 0.0 < score < 1.0


def test_ndcg_no_ideal():
    assert ndcg([0, 0], [0, 0], 2) == 0.0


def test_ndcg_k_truncates():
    assert ndcg([0, 3], [3], 1) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Metrics: precision_at_k
# ---------------------------------------------------------------------------


def test_precision_all_relevant():
    assert precision_at_k([3, 2, 1], 3) == pytest.approx(1.0)


def test_precision_none_relevant():
    assert precision_at_k([0, 0, 0], 3) == pytest.approx(0.0)


def test_precision_mixed():
    assert precision_at_k([3, 0, 1, 0, 0], 5) == pytest.approx(0.4)


def test_precision_respects_k():
    assert precision_at_k([1, 0, 1], 2) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Metrics: mrr
# ---------------------------------------------------------------------------


def test_mrr_first_position():
    assert mrr([3, 0, 0]) == pytest.approx(1.0)


def test_mrr_second_position():
    assert mrr([0, 2, 0]) == pytest.approx(0.5)


def test_mrr_third_position():
    assert mrr([0, 0, 1]) == pytest.approx(1.0 / 3.0)


def test_mrr_no_relevant():
    assert mrr([0, 0, 0]) == 0.0


# ---------------------------------------------------------------------------
# compute_query_metrics
# ---------------------------------------------------------------------------


def _make_results(titles):
    """Build a fake OpenSearch response from a list of titles."""
    return {
        "hits": {
            "hits": [{"_id": t, "_source": {"title": t}} for t in titles],
        }
    }


def test_compute_metrics_perfect():
    results = _make_results(["Doc A", "Doc B"])
    relevance = {"Doc A": 3, "Doc B": 2}
    m = compute_query_metrics(results, relevance, "title", k=2)

    assert m["ndcg"] == pytest.approx(1.0)
    assert m["p@k"] == pytest.approx(1.0)
    assert m["mrr"] == pytest.approx(1.0)
    assert m["rels"] == [3, 2]
    assert m["titles"] == ["Doc A", "Doc B"]
    assert m["doc_ids"] == ["Doc A", "Doc B"]
    assert len(m["dcg_contribs"]) == 2
    assert m["dcg_contribs"][0] == pytest.approx(3.0 / math.log2(2))  # 3.0


def test_compute_metrics_no_relevant():
    results = _make_results(["X", "Y", "Z"])
    relevance = {"Doc A": 3}
    m = compute_query_metrics(results, relevance, "title", k=3)

    assert m["ndcg"] == pytest.approx(0.0)
    assert m["p@k"] == pytest.approx(0.0)
    assert m["mrr"] == 0.0
    assert m["rels"] == [0, 0, 0]


def test_compute_metrics_partial():
    results = _make_results(["X", "Doc A", "Y"])
    relevance = {"Doc A": 3}
    m = compute_query_metrics(results, relevance, "title", k=3)

    assert m["mrr"] == pytest.approx(0.5)
    assert m["p@k"] == pytest.approx(1.0 / 3.0)


def test_compute_metrics_respects_k():
    results = _make_results(["X", "Y", "Doc A"])
    relevance = {"Doc A": 3}
    m = compute_query_metrics(results, relevance, "title", k=2)

    assert m["rels"] == [0, 0]
    assert m["titles"] == ["X", "Y"]


def test_compute_metrics_uses_title_field():
    results = {
        "hits": {
            "hits": [{"_id": "1", "_source": {"name": "Doc A"}}],
        }
    }
    relevance = {"Doc A": 3}
    m = compute_query_metrics(results, relevance, "name", k=1)

    assert m["rels"] == [3]


def test_compute_metrics_falls_back_to_id():
    results = {
        "hits": {
            "hits": [{"_id": "doc-1", "_source": {}}],
        }
    }
    relevance = {"doc-1": 3}
    m = compute_query_metrics(results, relevance, "title", k=1)

    assert m["rels"] == [3]
    assert m["titles"] == ["doc-1"]


# ---------------------------------------------------------------------------
# Helpers for diagnose_query tests
# ---------------------------------------------------------------------------


def _make_metrics(ndcg_val, titles=None, rels=None):
    """Helper to build a metrics dict for diagnosis tests."""
    return {
        "ndcg": ndcg_val,
        "p@k": 0.0,
        "mrr": 0.0,
        "titles": titles or [],
        "rels": rels or [],
    }


# ---------------------------------------------------------------------------
# diagnose_query: Rule 1 -- all methods fail
# ---------------------------------------------------------------------------


def test_diagnose_rule1_semantic_all_fail():
    test = {"type": "semantic", "query": "abstract concept", "relevance": {"A": 3}}
    metrics = {m: _make_metrics(0.1, ["X"], [0]) for m in ["HYBRID", "BM25", "KNN"]}

    findings = diagnose_query(test, metrics, k=5)

    assert len(findings) >= 1
    assert findings[0][0] == "[MODEL_SELECTION]"
    assert findings[0][1] == "HIGH"


def test_diagnose_rule1_combined_all_fail():
    test = {"type": "combined", "query": "structured query", "relevance": {"A": 3}}
    metrics = {m: _make_metrics(0.1, ["X"], [0]) for m in ["HYBRID", "BM25", "KNN"]}

    findings = diagnose_query(test, metrics, k=5)

    assert len(findings) >= 1
    assert findings[0][0] == "[INDEX_MAPPING]"
    assert findings[0][1] == "HIGH"


def test_diagnose_rule1_generic_type_all_fail():
    """Unrecognised query type still triggers rule 1 with INDEX_MAPPING."""
    test = {"type": "exact", "query": "test", "relevance": {"A": 3}}
    metrics = {"MethodA": _make_metrics(0.1, ["X"], [0])}

    findings = diagnose_query(test, metrics, k=5)

    assert len(findings) >= 1
    assert findings[0][0] == "[INDEX_MAPPING]"
    assert findings[0][1] == "HIGH"


def test_diagnose_rule1_not_triggered_when_one_succeeds():
    test = {"type": "semantic", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "HYBRID": _make_metrics(0.1, ["X"], [0]),
        "BM25": _make_metrics(0.6, ["A"], [3]),
        "KNN": _make_metrics(0.1, ["X"], [0]),
    }

    findings = diagnose_query(test, metrics, k=5)

    rule1_findings = [f for f in findings if f[1] == "HIGH" and "All methods" in f[2]]
    assert len(rule1_findings) == 0


def test_diagnose_rule1_single_method_fails():
    """Rule 1 works with a single method."""
    test = {"type": "semantic", "query": "concept", "relevance": {"A": 3}}
    metrics = {"OnlyMethod": _make_metrics(0.1, ["X"], [0])}

    findings = diagnose_query(test, metrics, k=5)

    assert len(findings) >= 1
    assert findings[0][1] == "HIGH"


# ---------------------------------------------------------------------------
# diagnose_query: Rule 2 -- pairwise method gaps (tag-aware)
# ---------------------------------------------------------------------------


def test_diagnose_rule2_vector_fails_lexical_succeeds():
    test = {"type": "exact", "query": "entity lookup", "relevance": {"A": 3}}
    metrics = {
        "BM25": _make_metrics(0.8, ["A"], [3]),
        "KNN": _make_metrics(0.1, ["X"], [0]),
    }
    tags = {"BM25": "lexical", "KNN": "vector"}

    findings = diagnose_query(test, metrics, k=5, method_tags=tags)

    model_findings = [f for f in findings if f[0] == "[MODEL_SELECTION]" and f[1] == "MEDIUM"]
    assert len(model_findings) == 1
    assert "KNN" in model_findings[0][2]


def test_diagnose_rule2_lexical_fails_vector_succeeds():
    test = {"type": "semantic", "query": "concept", "relevance": {"A": 3}}
    metrics = {
        "BM25": _make_metrics(0.1, ["X"], [0]),
        "Dense": _make_metrics(0.8, ["A"], [3]),
    }
    tags = {"BM25": "lexical", "Dense": "vector"}

    findings = diagnose_query(test, metrics, k=5, method_tags=tags)

    mapping_findings = [f for f in findings if f[0] == "[INDEX_MAPPING]" and f[1] == "MEDIUM"]
    assert len(mapping_findings) == 1
    assert "BM25" in mapping_findings[0][2]


def test_diagnose_rule2_untagged_pairwise_gap():
    """Large gap between two untagged methods triggers QUERY_TUNING."""
    test = {"type": "exact", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "MethodA": _make_metrics(0.9, ["A"], [3]),
        "MethodB": _make_metrics(0.2, ["X"], [0]),
    }

    findings = diagnose_query(test, metrics, k=5)

    tuning = [f for f in findings if f[0] == "[QUERY_TUNING]"]
    assert len(tuning) >= 1
    assert "MethodB" in tuning[0][2]


# ---------------------------------------------------------------------------
# diagnose_query: Rule 3 -- hybrid worse than best single
# ---------------------------------------------------------------------------


def test_diagnose_rule3_hybrid_worse_than_lexical():
    test = {"type": "exact", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "Hybrid": _make_metrics(0.4, ["A", "X"], [3, 0]),
        "BM25": _make_metrics(0.8, ["A"], [3]),
        "KNN": _make_metrics(0.3, ["X"], [0]),
    }
    tags = {"Hybrid": "hybrid", "BM25": "lexical", "KNN": "vector"}

    findings = diagnose_query(test, metrics, k=5, method_tags=tags)

    pipeline_findings = [f for f in findings if f[0] == "[SEARCH_PIPELINE]"]
    assert len(pipeline_findings) >= 1
    assert pipeline_findings[0][1] == "MEDIUM"


def test_diagnose_rule3_hybrid_worse_than_vector():
    test = {"type": "semantic", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "Hybrid": _make_metrics(0.4, ["X", "A"], [0, 3]),
        "BM25": _make_metrics(0.2, ["X"], [0]),
        "KNN": _make_metrics(0.8, ["A"], [3]),
    }
    tags = {"Hybrid": "hybrid", "BM25": "lexical", "KNN": "vector"}

    findings = diagnose_query(test, metrics, k=5, method_tags=tags)

    pipeline_findings = [f for f in findings if f[0] == "[SEARCH_PIPELINE]"]
    assert len(pipeline_findings) >= 1
    assert pipeline_findings[0][1] == "LOW"


def test_diagnose_rule3_not_triggered_when_close():
    test = {"type": "exact", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "Hybrid": _make_metrics(0.75, ["A"], [3]),
        "BM25": _make_metrics(0.80, ["A"], [3]),
        "KNN": _make_metrics(0.70, ["A"], [3]),
    }
    tags = {"Hybrid": "hybrid", "BM25": "lexical", "KNN": "vector"}

    findings = diagnose_query(test, metrics, k=5, method_tags=tags)

    pipeline_findings = [f for f in findings if f[0] == "[SEARCH_PIPELINE]"]
    assert len(pipeline_findings) == 0


def test_diagnose_rule3_not_triggered_without_hybrid_tag():
    """Without hybrid tag, rule 3 doesn't fire (methods are untagged)."""
    test = {"type": "exact", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "MethodA": _make_metrics(0.4, ["A", "X"], [3, 0]),
        "MethodB": _make_metrics(0.8, ["A"], [3]),
    }

    findings = diagnose_query(test, metrics, k=5)

    pipeline_findings = [f for f in findings if f[0] == "[SEARCH_PIPELINE]"]
    assert len(pipeline_findings) == 0


# ---------------------------------------------------------------------------
# diagnose_query: Rule 4 -- irrelevant doc in top 2
# ---------------------------------------------------------------------------


def test_diagnose_rule4_noise_in_one_method():
    test = {"type": "combined", "query": "test query", "relevance": {"A": 3}}
    metrics = {
        "Hybrid": _make_metrics(0.5, ["Noise", "A", "X", "Y", "Z"], [0, 3, 0, 0, 0]),
        "BM25": _make_metrics(0.5, ["Noise", "A", "X"], [0, 3, 0]),
        "KNN": _make_metrics(0.5, ["A", "B", "C"], [3, 0, 0]),
    }

    findings = diagnose_query(test, metrics, k=5)

    tuning_findings = [f for f in findings if f[0] == "[QUERY_TUNING]"]
    assert len(tuning_findings) >= 1
    assert "Noise" in tuning_findings[0][2]


def test_diagnose_rule4_noise_across_all_methods():
    test = {"type": "semantic", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "M1": _make_metrics(0.5, ["FalsePos", "A", "X", "Y", "Z"], [0, 3, 0, 0, 0]),
        "M2": _make_metrics(0.5, ["FalsePos", "A", "D"], [0, 3, 0]),
    }

    findings = diagnose_query(test, metrics, k=5)

    model_findings = [f for f in findings if f[0] == "[MODEL_SELECTION]"]
    assert len(model_findings) >= 1


def test_diagnose_rule4_not_triggered_when_ndcg_high():
    test = {"type": "exact", "query": "test", "relevance": {"A": 3, "B": 2}}
    metrics = {
        "M1": _make_metrics(0.9, ["X", "A", "B"], [0, 3, 2]),
        "M2": _make_metrics(0.9, ["A", "B"], [3, 2]),
    }

    findings = diagnose_query(test, metrics, k=5)

    rule4_findings = [f for f in findings if f[0] == "[QUERY_TUNING]"]
    assert len(rule4_findings) == 0


def test_diagnose_rule4_single_method():
    """Rule 4 works with a single method (no cross-method attribution)."""
    test = {"type": "exact", "query": "test", "relevance": {"A": 3}}
    metrics = {
        "Only": _make_metrics(0.5, ["Noise", "A", "X"], [0, 3, 0]),
    }

    findings = diagnose_query(test, metrics, k=5)

    tuning = [f for f in findings if f[0] == "[QUERY_TUNING]"]
    assert len(tuning) >= 1
    assert "Noise" in tuning[0][2]


# ---------------------------------------------------------------------------
# diagnose_query: Rule 5 -- missed relevant docs
# ---------------------------------------------------------------------------


def test_diagnose_rule5_missed_docs():
    test = {"type": "exact", "query": "test", "relevance": {"A": 3, "B": 2, "C": 2}}
    metrics = {
        "M1": _make_metrics(0.5, ["A"], [3]),
        "M2": _make_metrics(0.5, ["A"], [3]),
    }

    findings = diagnose_query(test, metrics, k=5, embedded_fields="title + text")

    missed_findings = [f for f in findings if "not in any top" in f[2]]
    assert len(missed_findings) == 1
    assert "B" in missed_findings[0][2] or "C" in missed_findings[0][2]


def test_diagnose_rule5_no_missed_when_all_found():
    test = {"type": "exact", "query": "test", "relevance": {"A": 3, "B": 2}}
    metrics = {
        "M1": _make_metrics(1.0, ["A", "B"], [3, 2]),
    }

    findings = diagnose_query(test, metrics, k=5)

    missed_findings = [f for f in findings if "not in any top" in f[2]]
    assert len(missed_findings) == 0


def test_diagnose_rule5_ignores_marginal_docs():
    test = {"type": "exact", "query": "test", "relevance": {"A": 3, "B": 1}}
    metrics = {
        "M1": _make_metrics(1.0, ["A"], [3]),
    }

    findings = diagnose_query(test, metrics, k=5)

    missed_findings = [f for f in findings if "not in any top" in f[2]]
    assert len(missed_findings) == 0


def test_diagnose_rule5_found_across_different_methods():
    """Doc found by one method is not counted as missed."""
    test = {"type": "exact", "query": "test", "relevance": {"A": 3, "B": 2}}
    metrics = {
        "M1": _make_metrics(0.8, ["A"], [3]),
        "M2": _make_metrics(0.8, ["B"], [2]),
    }

    findings = diagnose_query(test, metrics, k=5)

    missed_findings = [f for f in findings if "not in any top" in f[2]]
    assert len(missed_findings) == 0


# ---------------------------------------------------------------------------
# diagnose_query: no findings when everything works
# ---------------------------------------------------------------------------


def test_diagnose_no_findings_when_all_good():
    test = {"type": "exact", "query": "perfect query", "relevance": {"A": 3}}
    metrics = {
        "M1": _make_metrics(1.0, ["A"], [3]),
        "M2": _make_metrics(1.0, ["A"], [3]),
    }

    findings = diagnose_query(test, metrics, k=5)
    assert findings == []


def test_diagnose_no_findings_single_method_good():
    test = {"type": "exact", "query": "perfect query", "relevance": {"A": 3}}
    metrics = {"Only": _make_metrics(1.0, ["A"], [3])}

    findings = diagnose_query(test, metrics, k=5)
    assert findings == []


def test_diagnose_empty_methods():
    test = {"type": "exact", "query": "test", "relevance": {"A": 3}}
    findings = diagnose_query(test, {}, k=5)
    assert findings == []


# ---------------------------------------------------------------------------
# evaluate_results (integration)
# ---------------------------------------------------------------------------


def _make_os_response(titles):
    """Build a minimal OpenSearch search response."""
    return {
        "hits": {
            "hits": [{"_id": t, "_source": {"title": t}} for t in titles],
        }
    }


def test_evaluate_results_basic():
    tests = [
        {"name": "Q1", "type": "exact", "query": "test", "relevance": {"A": 3, "B": 2}},
    ]
    results_by_method = {
        "Alpha": [_make_os_response(["A", "B"])],
        "Beta": [_make_os_response(["B", "A"])],
    }

    report = evaluate_results(tests, results_by_method, k=2, title_field="title")

    assert report["methods"] == ["Alpha", "Beta"]
    assert report["k"] == 2
    assert len(report["metrics"]["Alpha"]) == 1
    assert len(report["metrics"]["Beta"]) == 1
    assert report["metrics"]["Alpha"][0]["ndcg"] == pytest.approx(1.0)
    assert report["metrics"]["Beta"][0]["ndcg"] < 1.0
    assert "Alpha" in report["summary"]
    assert "Beta" in report["summary"]


def test_evaluate_results_single_method():
    tests = [
        {"name": "Q1", "type": "exact", "query": "test", "relevance": {"A": 3}},
    ]
    results_by_method = {
        "Only": [_make_os_response(["A"])],
    }

    report = evaluate_results(tests, results_by_method, k=1)

    assert report["methods"] == ["Only"]
    assert report["summary"]["Only"]["mean_ndcg"] == pytest.approx(1.0)


def test_evaluate_results_multiple_queries():
    tests = [
        {"name": "Q1", "type": "exact", "query": "a", "relevance": {"A": 3}},
        {"name": "Q2", "type": "semantic", "query": "b", "relevance": {"B": 3}},
    ]
    results_by_method = {
        "M": [_make_os_response(["A"]), _make_os_response(["X"])],
    }

    report = evaluate_results(tests, results_by_method, k=1)

    assert report["metrics"]["M"][0]["ndcg"] == pytest.approx(1.0)
    assert report["metrics"]["M"][1]["ndcg"] == pytest.approx(0.0)
    assert report["summary"]["M"]["mean_ndcg"] == pytest.approx(0.5)


def test_evaluate_results_with_tags():
    tests = [
        {"name": "Q1", "type": "exact", "query": "test", "relevance": {"A": 3}},
    ]
    results_by_method = {
        "BM25": [_make_os_response(["A"])],
        "KNN": [_make_os_response(["X"])],
    }
    tags = {"BM25": "lexical", "KNN": "vector"}

    report = evaluate_results(tests, results_by_method, k=1, method_tags=tags)

    # KNN fails, BM25 succeeds -> should produce MODEL_SELECTION finding
    flat_findings = [
        (tag, sev) for _, findings in report["findings"] for tag, sev, _ in findings
    ]
    model_findings = [(t, s) for t, s in flat_findings if t == "[MODEL_SELECTION]"]
    assert len(model_findings) >= 1


def test_evaluate_results_findings_empty_when_perfect():
    tests = [
        {"name": "Q1", "type": "exact", "query": "test", "relevance": {"A": 3}},
    ]
    results_by_method = {
        "M1": [_make_os_response(["A"])],
        "M2": [_make_os_response(["A"])],
    }

    report = evaluate_results(tests, results_by_method, k=1)

    assert report["findings"] == []


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_findings_empty():
    output = format_findings([])
    assert "None" in output
    assert "performing well" in output


def test_format_findings_with_data():
    all_findings = [
        ("Q1", [("[MODEL_SELECTION]", "HIGH", "Test message")]),
    ]
    output = format_findings(all_findings)
    assert "MODEL_SELECTION" in output
    assert "Test message" in output
    assert "RECOMMENDED NEXT ACTION" in output


def test_format_completion_target_met():
    report = {
        "metrics": {"M": [{"ndcg": 0.9, "p@k": 0.8, "mrr": 0.9}]},
        "findings": [],
        "k": 5,
    }
    output = format_completion(report)
    assert "Target met" in output


def test_format_completion_needs_work():
    report = {
        "metrics": {"M": [{"ndcg": 0.3, "p@k": 0.2, "mrr": 0.3}]},
        "findings": [("Q1", [("[INDEX_MAPPING]", "HIGH", "bad")])],
        "k": 5,
    }
    output = format_completion(report)
    assert "optimization recommended" in output


def test_format_report_runs_without_error():
    tests = [
        {"name": "Q1", "type": "exact", "query": "test", "relevance": {"A": 3}},
    ]
    report = {
        "methods": ["M1", "M2"],
        "tests": tests,
        "metrics": {
            "M1": [{"ndcg": 1.0, "p@k": 1.0, "mrr": 1.0, "rels": [3], "titles": ["A"],
                     "doc_ids": ["a1"], "scores": [5.0], "dcg_contribs": [3.0]}],
            "M2": [{"ndcg": 0.0, "p@k": 0.0, "mrr": 0.0, "rels": [0], "titles": ["X"],
                     "doc_ids": ["x1"], "scores": [1.0], "dcg_contribs": [0.0]}],
        },
        "findings": [],
        "summary": {
            "M1": {"mean_ndcg": 1.0, "mean_pk": 1.0, "mean_mrr": 1.0},
            "M2": {"mean_ndcg": 0.0, "mean_pk": 0.0, "mean_mrr": 0.0},
        },
        "k": 1,
    }
    output = format_report(report, config={"index": "test-index"})
    assert "SEARCH QUALITY EVALUATION" in output
    assert "test-index" in output
    assert "M1" in output
    assert "M2" in output


# ---------------------------------------------------------------------------
# Config schema validation
# ---------------------------------------------------------------------------


def test_config_schema_validation():
    """Validate that a well-formed config dict has all required fields."""
    config = {
        "index": "test-index",
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "bm25_fields": ["title^4", "text^2"],
        "embedded_fields": "title + text",
        "methods": [
            {"name": "HYBRID", "mode": "hybrid", "tag": "hybrid"},
            {"name": "BM25", "mode": "bm25", "tag": "lexical"},
        ],
        "tests": [
            {
                "name": "Q1: Test query",
                "type": "semantic",
                "query": "test query",
                "relevance": {"Doc A": 3, "Doc B": 1},
            },
        ],
    }
    assert "index" in config
    assert "model" in config
    assert "bm25_fields" in config
    assert len(config["tests"]) > 0
    for test in config["tests"]:
        assert "name" in test
        assert "type" in test
        assert "query" in test
        assert "relevance" in test
        assert isinstance(test["relevance"], dict)
        assert test["type"] in ("semantic", "exact", "combined", "structured", "fuzzy")
    for method in config["methods"]:
        assert "name" in method
