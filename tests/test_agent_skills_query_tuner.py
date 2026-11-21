"""Tests for deterministic, judgment-backed query tuning."""

import sys
from pathlib import Path

from opensearchpy.exceptions import RequestError

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "search"
    / "relevance-x-ray"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

from relevance_xray_lib.query_tuner import (
    normalize_judgments,
    propose_query_candidates,
    query_fingerprint,
    validate_query_candidates,
)


BASELINE = {
    "query": {
        "function_score": {
            "query": {
                "multi_match": {
                    "query": "running trainers",
                    "fields": ["title", "description"],
                }
            },
            "field_value_factor": {"field": "popularity", "factor": 1.0},
            "boost_mode": "replace",
        }
    }
}
JUDGMENTS = [
    {
        "type": "pairwise",
        "preferred_doc_id": "1",
        "rejected_doc_id": "2",
        "reason": "lexical intent",
    }
]
DOCUMENTS = {
    "1": {
        "title": "Lightweight Running Trainers",
        "description": "Breathable trainers",
    },
    "2": {
        "title": "Classic Canvas Sneakers",
        "description": "Everyday canvas shoes",
    },
}
MAPPING = {
    "title": {"type": "text"},
    "description": {"type": "text"},
    "popularity": {"type": "float"},
}


def test_query_fingerprint_is_stable_across_key_order():
    first = {"query": {"match": {"title": "shoes"}}, "size": 10}
    second = {"size": 10, "query": {"match": {"title": "shoes"}}}
    assert query_fingerprint(first) == query_fingerprint(second)


def test_normalize_judgments_rejects_other_baseline_fingerprint():
    judgments = [
        {
            **JUDGMENTS[0],
            "baseline_fingerprint": "different",
        }
    ]
    assert normalize_judgments(judgments, "expected") == []


def test_proposals_use_observed_field_support_and_existing_function_score():
    candidates = propose_query_candidates(
        BASELINE,
        JUDGMENTS,
        DOCUMENTS,
        MAPPING,
    )
    by_name = {candidate.name: candidate for candidate in candidates}

    assert "boost-title" in by_name
    assert (
        by_name["boost-title"]
        .search_body["query"]["function_score"]["query"]["multi_match"]["fields"][0]
        == "title^2"
    )
    assert "preserve-lexical-score" in by_name
    assert "temper-function-score-0.1" in by_name
    assert (
        by_name["temper-function-score-0.1"]
        .search_body["query"]["function_score"]["field_value_factor"]["factor"]
        == 0.1
    )


def test_validation_selects_measured_improvement_without_regression():
    candidates = propose_query_candidates(
        BASELINE,
        JUDGMENTS,
        DOCUMENTS,
        MAPPING,
    )

    def search_fn(body):
        function_score = body["query"]["function_score"]
        factor = function_score["field_value_factor"]["factor"]
        boost_mode = function_score["boost_mode"]
        if boost_mode == "sum" and factor <= 0.1:
            return [{"_id": "1"}, {"_id": "2"}]
        return [{"_id": "2"}, {"_id": "1"}]

    result = validate_query_candidates(
        BASELINE,
        candidates,
        JUDGMENTS,
        search_fn,
    )

    assert result["baseline_outcomes"][0]["satisfied"] is False
    assert result["selected"]["name"] == "temper-function-score-0.1"
    assert result["selected"]["improved_judgments"] == 1
    assert result["selected"]["regressed_judgments"] == 0


def test_validation_abstains_when_no_candidate_improves_ordering():
    candidates = propose_query_candidates(
        BASELINE,
        JUDGMENTS,
        DOCUMENTS,
        MAPPING,
    )

    result = validate_query_candidates(
        BASELINE,
        candidates,
        JUDGMENTS,
        lambda body: [{"_id": "2"}, {"_id": "1"}],
    )

    assert result["selected"] is None
    assert all(not candidate["accepted"] for candidate in result["candidates"])


def test_candidate_failure_does_not_expose_cluster_response_body():
    candidates = propose_query_candidates(
        BASELINE,
        JUDGMENTS,
        DOCUMENTS,
        MAPPING,
    )
    calls = 0

    def search_fn(body):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [{"_id": "2"}, {"_id": "1"}]
        raise RequestError(
            400,
            "search_phase_execution_exception",
            {"error": {"reason": "secret-index on internal-node-7"}},
        )

    result = validate_query_candidates(
        BASELINE,
        candidates,
        JUDGMENTS,
        search_fn,
    )
    assert all(
        candidate["error"] == "RequestError (HTTP 400)"
        for candidate in result["candidates"]
    )
    assert "secret-index" not in str(result)
