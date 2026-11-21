"""Tests for the bundled Relevance X-Ray synonym suggester.

No cluster required — the client-calling helpers (fetch_sample_documents,
simulate_synonym_analyzer, validate_synonym_candidate) are exercised with a
fake client object rather than a real OpenSearch connection.
"""

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

from relevance_xray_lib.synonym_suggester import (
    SynonymCandidate,
    analyze_source_document,
    fetch_document_term_lists,
    fetch_sample_document_ids,
    fetch_sample_documents,
    mine_candidate_synonyms,
    rank_delta,
    score_overlap,
    simulate_synonym_analyzer,
    validate_synonym_candidate,
)


# ---------------------------------------------------------------------------
# mine_candidate_synonyms (pure)
# ---------------------------------------------------------------------------


def test_mine_candidate_synonyms_finds_co_occurring_term():
    corpus = [
        ["sneakers", "running", "trainers", "lightweight"],
        ["sneakers", "casual", "trainers"],
        ["boots", "leather", "waterproof"],
    ]
    candidates = mine_candidate_synonyms(
        query_term="sneakers",
        target_doc_terms=["trainers", "boots", "leather"],
        corpus_term_lists=corpus,
        min_support=2,
    )
    assert len(candidates) == 1
    assert candidates[0].candidate == "trainers"
    assert candidates[0].support == 2


def test_mine_candidate_synonyms_requires_term_in_target_doc():
    corpus = [["sneakers", "trainers"], ["sneakers", "trainers"]]
    candidates = mine_candidate_synonyms(
        query_term="sneakers",
        target_doc_terms=["trainers"],
        corpus_term_lists=corpus,
        min_support=2,
    )
    assert [candidate.candidate for candidate in candidates] == ["trainers"]


def test_mine_candidate_synonyms_counts_documents_not_duplicate_tokens():
    corpus = [["sneakers", "canvas", "canvas"], ["boots"]]
    candidates = mine_candidate_synonyms(
        query_term="sneakers",
        target_doc_terms=["canvas"],
        corpus_term_lists=corpus,
        min_support=2,
    )
    assert candidates == []


def test_mine_candidate_synonyms_respects_min_support():
    corpus = [["sneakers", "trainers"], ["boots"]]
    candidates = mine_candidate_synonyms(
        query_term="sneakers",
        target_doc_terms=["trainers"],
        corpus_term_lists=corpus,
        min_support=2,
    )
    assert candidates == []  # 'trainers' only co-occurs once


def test_mine_candidate_synonyms_no_neighborhood_returns_empty():
    corpus = [["boots", "leather"]]
    candidates = mine_candidate_synonyms(
        query_term="sneakers", target_doc_terms=[], corpus_term_lists=corpus
    )
    assert candidates == []


def test_mine_candidate_synonyms_respects_max_candidates():
    corpus = [
        ["sneakers", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot"],
        ["sneakers", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot"],
    ]
    candidates = mine_candidate_synonyms(
        query_term="sneakers",
        target_doc_terms=["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"],
        corpus_term_lists=corpus,
        min_support=2,
        max_candidates=3,
    )
    assert len(candidates) == 3


# ---------------------------------------------------------------------------
# score_overlap / rank_delta (pure)
# ---------------------------------------------------------------------------


def test_score_overlap_computes_delta():
    result = score_overlap(
        before_terms={"a", "b"}, after_terms={"a", "b", "c"}, relevant_terms={"b", "c", "d"}
    )
    assert result == {"before_overlap": 1, "after_overlap": 2, "delta": 1}


def test_rank_delta_improved():
    result = rank_delta(before_rank=8, after_rank=1)
    assert result["improved"] is True
    assert result["moved"] is True


def test_rank_delta_appeared_from_nowhere():
    result = rank_delta(before_rank=None, after_rank=3)
    assert result["improved"] is True


def test_rank_delta_disappeared():
    result = rank_delta(before_rank=3, after_rank=None)
    assert result["improved"] is False


def test_rank_delta_unchanged():
    result = rank_delta(before_rank=None, after_rank=None)
    assert result == {"before_rank": None, "after_rank": None, "moved": False, "improved": False}


# ---------------------------------------------------------------------------
# Client-calling helpers (fake client, no real cluster)
# ---------------------------------------------------------------------------


class _FakeIndicesClient:
    def analyze(self, index, body):
        # Minimal fake: split text and pretend the synonym filter expands
        # any term found in the synonym rules.
        text = body["text"]
        if isinstance(text, list):
            text = " ".join(text)
        tokens = text.lower().split()
        return {"tokens": [{"token": t} for t in tokens]}


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.indices = _FakeIndicesClient()

    def search(self, index, body, **kwargs):
        self.last_search_body = body
        return {"hits": {"hits": self._hits}}

    def mtermvectors(self, index, body, **kwargs):
        return {
            "docs": [
                {
                    "_id": doc_id,
                    "term_vectors": {
                        "title": {
                            "terms": {
                                "Sneakers": {},
                                f"term-{doc_id}": {},
                            }
                        }
                    },
                }
                for doc_id in body["ids"]
            ]
        }


def test_fetch_sample_documents_extracts_source():
    fake_hits = [{"_source": {"title": "Wireless Charger"}}, {"_source": {"title": "Trainers"}}]
    client = _FakeClient(fake_hits)
    docs = fetch_sample_documents(client, "products", fields=["title"], size=10)
    assert docs == [{"title": "Wireless Charger"}, {"title": "Trainers"}]
    assert "random_score" in client.last_search_body["query"]["function_score"]


def test_fetch_sample_document_ids_omits_source_and_uses_random_sample():
    client = _FakeClient([{"_id": "1"}, {"_id": "2"}])
    assert fetch_sample_document_ids(client, "products", size=10) == ["1", "2"]
    assert client.last_search_body["_source"] is False
    assert client.last_search_body["query"]["function_score"]["random_score"]["seed"]


def test_fetch_document_term_lists_batches_ids_and_preserves_order():
    client = _FakeClient([])
    terms = fetch_document_term_lists(
        client,
        "products",
        ["2", "1"],
        ["title"],
    )
    assert terms == [["sneakers", "term-2"], ["sneakers", "term-1"]]


def test_simulate_synonym_analyzer_returns_tokens():
    client = _FakeClient([])
    tokens = simulate_synonym_analyzer(
        client, "products", "sneakers trainers", synonym_pairs=[("sneakers", "trainers")]
    )
    assert tokens == ["sneakers", "trainers"]


def test_analyze_source_document_uses_field_analyzer():
    client = _FakeClient([])
    tokens = analyze_source_document(
        client,
        "products",
        {"title": "Running Trainers", "ignored": "No"},
        ["title"],
    )
    assert tokens == ["running", "trainers"]


def test_validate_synonym_candidate_reports_rank_improvement():
    client = _FakeClient([])

    def fake_search_fn(client, index, query_text):
        # Simulate: expanded query surfaces doc "42" earlier.
        if "trainers" in query_text:
            return ["1", "42", "2"]
        return ["1", "2", "3"]  # doc "42" absent without the synonym

    candidate = SynonymCandidate(term="sneakers", candidate="trainers", support=5, confidence=0.5)
    result = validate_synonym_candidate(
        client, "products", "sneakers", candidate, target_doc_id="42", search_fn=fake_search_fn
    )
    assert result["before_rank"] is None
    assert result["after_rank"] == 2
    assert result["improved"] is True


def test_validate_synonym_candidate_normalizes_document_id_types():
    client = _FakeClient([])

    def fake_search_fn(client, index, query_text):
        return [7, 42] if "trainers" in query_text else [42, 7]

    candidate = SynonymCandidate(
        term="sneakers",
        candidate="trainers",
        support=5,
        confidence=0.5,
    )

    result = validate_synonym_candidate(
        client,
        "products",
        "sneakers",
        candidate,
        target_doc_id="42",
        search_fn=fake_search_fn,
    )

    assert result["before_rank"] == 1
    assert result["after_rank"] == 2
