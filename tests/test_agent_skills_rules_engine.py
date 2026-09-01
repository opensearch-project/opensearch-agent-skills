"""Tests for the bundled Relevance X-Ray rules engine."""

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

from relevance_xray_lib.explain_parser import parse_explain
from relevance_xray_lib.rules_engine import (
    check_analyzer_mismatch,
    check_hybrid_leg_imbalance,
    check_knn_counterfactual,
    check_missing_keyword_subfield,
    check_unindexed_scoring_field,
    check_vocabulary_mismatch,
    evaluated_rule_names,
    rule_coverage,
    run_all_rules,
)


def test_missing_keyword_subfield_detected():
    mapping = {"brand": {"type": "text"}}
    findings = check_missing_keyword_subfield(mapping, ["brand"])
    assert len(findings) == 1
    assert findings[0].tag == "[INDEX_MAPPING]"
    assert "brand" in findings[0].message


def test_missing_keyword_subfield_not_flagged_when_keyword_present():
    mapping = {"brand": {"type": "text", "fields": {"keyword": {"type": "keyword"}}}}
    findings = check_missing_keyword_subfield(mapping, ["brand"])
    assert findings == []


def test_missing_keyword_subfield_ignores_non_text_fields():
    mapping = {"price": {"type": "float"}}
    findings = check_missing_keyword_subfield(mapping, ["price"])
    assert findings == []


def test_missing_keyword_subfield_ignores_text_child_of_keyword_field():
    mapping = {
        "sku": {"type": "keyword", "fields": {"text": {"type": "text"}}},
        "sku.text": {"type": "text"},
    }
    assert check_missing_keyword_subfield(mapping, ["sku.text"]) == []


def test_analyzer_mismatch_detects_near_variant():
    findings = check_analyzer_mismatch({
        "description": {
            "search_tokens": ["running"],
            "index_tokens": ["run"],
            "target_tokens": ["run", "shoe", "trail"],
        }
    })
    assert len(findings) == 1
    assert findings[0].rule == "analyzer_mismatch"
    assert findings[0].confidence == "high"


def test_analyzer_mismatch_silent_on_exact_match():
    findings = check_analyzer_mismatch({
        "description": {
            "search_tokens": ["running"],
            "index_tokens": ["run"],
            "target_tokens": ["running", "shoe"],
        }
    })
    assert findings == []


def test_analyzer_mismatch_does_not_guess_from_shared_prefix():
    findings = check_analyzer_mismatch({
        "description": {
            "search_tokens": ["analyst"],
            "index_tokens": ["analyst"],
            "target_tokens": ["analysis"],
        }
    })
    assert findings == []


def test_analyzer_mismatch_preserves_case_sensitive_tokens():
    findings = check_analyzer_mismatch({
        "code": {
            "search_tokens": ["abc"],
            "index_tokens": ["ABC"],
            "target_tokens": ["ABC"],
        }
    })
    assert len(findings) == 1


def test_unindexed_scoring_field_missing_from_mapping():
    findings = check_unindexed_scoring_field(["popularity_score"], {"title": {"type": "text"}})
    assert len(findings) == 1
    assert findings[0].severity == "HIGH"


def test_scoring_field_index_false_is_allowed_when_doc_values_available():
    mapping = {"popularity_score": {"type": "float", "index": False}}
    findings = check_unindexed_scoring_field(["popularity_score"], mapping)
    assert findings == []


def test_scoring_field_doc_values_false_is_flagged():
    mapping = {"popularity_score": {"type": "float", "index": False, "doc_values": False}}
    findings = check_unindexed_scoring_field(["popularity_score"], mapping)
    assert len(findings) == 1
    assert "doc_values" in findings[0].message


def test_unindexed_scoring_field_ok_when_indexed():
    mapping = {"popularity_score": {"type": "float"}}
    findings = check_unindexed_scoring_field(["popularity_score"], mapping)
    assert findings == []


def test_vocabulary_mismatch_detected():
    node = {
        "value": 0.5,
        "description": "sum of:",
        "details": [
            {
                "value": 0.5,
                "description": "weight(description:trainers in 0) [PerFieldSimilarity], result of:",
                "details": [],
            }
        ],
    }
    summary = parse_explain(node)
    findings = check_vocabulary_mismatch(
        query_terms=["sneakers"],
        summary=summary,
        co_occurring_terms={"sneakers": {"trainers"}},
    )
    assert len(findings) == 1
    assert findings[0].tag == "[QUERY_TUNING]"


def test_vocabulary_mismatch_silent_when_term_matched():
    node = {
        "value": 0.5,
        "description": "sum of:",
        "details": [
            {
                "value": 0.5,
                "description": "weight(description:sneakers in 0) [PerFieldSimilarity], result of:",
                "details": [],
            }
        ],
    }
    summary = parse_explain(node)
    findings = check_vocabulary_mismatch(
        query_terms=["sneakers"],
        summary=summary,
        co_occurring_terms={"sneakers": {"trainers"}},
    )
    assert findings == []


def test_weak_knn_recall_requires_measured_rank_improvement():
    findings = check_knn_counterfactual({
        "before_rank": None,
        "after_rank": 4,
        "before_params": {"embedding.ef_search": 20},
        "after_params": {"embedding.ef_search": 100},
    })
    assert len(findings) == 1
    assert findings[0].tag == "[MODEL_SELECTION]"


def test_weak_knn_recall_not_inferred_from_score_or_unchanged_rank():
    findings = check_knn_counterfactual({
        "before_rank": None,
        "after_rank": None,
        "before_params": {"embedding.ef_search": 20},
        "after_params": {"embedding.ef_search": 100},
    })
    assert findings == []


def test_weak_knn_recall_rejects_candidate_count_changes():
    findings = check_knn_counterfactual({
        "before_rank": None,
        "after_rank": 4,
        "before_params": {"embedding.k": 5},
        "after_params": {"embedding.k": 20},
    })
    assert findings == []


def test_hybrid_leg_imbalance_flagged():
    findings = check_hybrid_leg_imbalance(
        {"bm25": [0.0, 0.0], "knn": [0.2, 0.8]},
        {"bm25": 0.5, "knn": 0.5},
    )
    assert len(findings) == 1
    assert findings[0].tag == "[SEARCH_PIPELINE]"


def test_hybrid_leg_imbalance_silent_when_balanced():
    findings = check_hybrid_leg_imbalance(
        {"bm25": [0.2, 0.6], "knn": [0.4, 0.7]},
        {"bm25": 0.5, "knn": 0.5},
    )
    assert findings == []


def test_run_all_rules_skips_rules_with_missing_inputs():
    # Only summary provided — mapping-based rules should not run/error.
    node = {"value": 1.0, "description": "sum of:", "details": []}
    summary = parse_explain(node)
    findings = run_all_rules({"summary": summary})
    assert findings == []


def test_run_all_rules_aggregates_multiple_rules():
    mapping = {"brand": {"type": "text"}}
    node = {
        "value": 0.5,
        "description": "sum of:",
        "details": [
            {
                "value": 0.5,
                "description": "weight(description:trainers in 0) [PerFieldSimilarity], result of:",
                "details": [],
            }
        ],
    }
    summary = parse_explain(node)
    findings = run_all_rules(
        {
            "mapping_properties": mapping,
            "filter_or_exact_fields": ["brand"],
            "query_terms": ["sneakers"],
            "summary": summary,
            "co_occurring_terms": {"sneakers": {"trainers"}},
        }
    )
    tags = {f.tag for f in findings}
    assert "[INDEX_MAPPING]" in tags
    assert "[QUERY_TUNING]" in tags


def test_evaluated_rule_names_excludes_rules_without_evidence():
    context = {"summary": parse_explain({"value": 0.1, "description": "sum of:"})}
    assert evaluated_rule_names(context) == []


def test_rule_coverage_reports_every_skipped_rule_with_reason():
    context = {
        "mapping_properties": {"title": {"type": "text"}},
        "analysis_by_field": {
            "title": {
                "search_tokens": ["running"],
                "index_tokens": ["run"],
                "target_tokens": [],
            }
        },
        "summary": parse_explain({"value": 0.1, "description": "sum of:"}),
    }
    evaluated, skipped = rule_coverage(context)
    assert evaluated == []
    assert set(skipped) == {
        "missing_keyword_subfield",
        "analyzer_mismatch",
        "unindexed_scoring_field",
        "vocabulary_mismatch",
        "weak_knn_recall",
        "hybrid_leg_imbalance",
    }
    assert "target-term-vector" in skipped["analyzer_mismatch"]
