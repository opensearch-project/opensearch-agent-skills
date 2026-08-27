"""Unit tests for quality.py — the correctness backbone.

All expected values are HAND-COMPUTED and documented with arithmetic.
This is the objective evidence of correctness.
"""


import sys as _sys
from pathlib import Path as _Path

# ai-search-tuner uses a flat-import layout; put its skill script dirs and the
# test fixtures dir on sys.path so `from model import ...`, `from dense_knn
# import ...`, `from fake_client import ...` resolve (no running cluster needed).
_REPO_ROOT = _Path(__file__).resolve().parents[1]
_SKILL = _REPO_ROOT / "skills" / "opensearch-skills" / "search" / "ai-search-tuner" / "scripts"
for _p in (_SKILL, _SKILL / "harness", _SKILL / "modes"):
    _sp = str(_p)
    if _sp not in _sys.path:
        _sys.path.insert(0, _sp)

import pytest
from model import Mode, Metric, QualityScore, RunResult, QueryResult, Config
from corpus import Qrels
from quality import recall_at_k, ndcg_at_k, map_at_k, score_run


# ============================================================================
# recall_at_k tests
# ============================================================================


def test_recall_at_k_basic():
    """Test recall@k with a simple overlap case.

    Hand computation:
    retrieved = [a, b, x], reference = [a, b, c, d], k=3
    top-3(retrieved) = {a, b, x}
    top-3(reference) = {a, b, c}
    intersection = {a, b} → size = 2
    denominator = min(3, 4) = 3
    recall@3 = 2/3 ≈ 0.6667
    """
    retrieved = ["a", "b", "x"]
    reference = ["a", "b", "c", "d"]
    recall = recall_at_k(retrieved, reference, k=3)
    assert recall == pytest.approx(2 / 3, abs=1e-4)


def test_recall_at_k_perfect():
    """Test perfect recall: retrieved matches reference exactly.

    retrieved = [a, b, c], reference = [a, b, c], k=3
    intersection = {a, b, c} → size = 3
    recall@3 = 3/3 = 1.0
    """
    retrieved = ["a", "b", "c"]
    reference = ["a", "b", "c"]
    recall = recall_at_k(retrieved, reference, k=3)
    assert recall == 1.0


def test_recall_at_k_zero():
    """Test zero recall: no overlap.

    retrieved = [x, y, z], reference = [a, b, c], k=3
    intersection = {} → size = 0
    recall@3 = 0/3 = 0.0
    """
    retrieved = ["x", "y", "z"]
    reference = ["a", "b", "c"]
    recall = recall_at_k(retrieved, reference, k=3)
    assert recall == 0.0


def test_recall_at_k_clamps_k():
    """Test that k > len(reference) is handled gracefully.

    retrieved = [a, b, c, d, e], reference = [a, b], k=10
    effective_k = min(10, 2) = 2
    top-2(retrieved) = {a, b}
    top-2(reference) = {a, b}
    intersection = {a, b} → size = 2
    recall@10 = 2/2 = 1.0
    """
    retrieved = ["a", "b", "c", "d", "e"]
    reference = ["a", "b"]
    recall = recall_at_k(retrieved, reference, k=10)
    assert recall == 1.0


def test_recall_at_k_empty_reference():
    """Empty reference → recall = 0.0."""
    retrieved = ["a", "b", "c"]
    reference = []
    recall = recall_at_k(retrieved, reference, k=3)
    assert recall == 0.0


def test_recall_at_k_empty_retrieved():
    """Empty retrieved list → recall = 0.0.

    retrieved = [], reference = [a, b, c], k=3
    intersection = {} → size = 0
    recall@3 = 0/3 = 0.0
    """
    retrieved = []
    reference = ["a", "b", "c"]
    recall = recall_at_k(retrieved, reference, k=3)
    assert recall == 0.0


# ============================================================================
# ndcg_at_k tests
# ============================================================================


def test_ndcg_at_k_perfect():
    """Test perfect NDCG: retrieved matches ideal ranking.

    graded = {d1: 3, d2: 2, d3: 1}
    retrieved = [d1, d2, d3]  # perfect order
    k = 3

    DCG@3 = 3/log2(2) + 2/log2(3) + 1/log2(4)
          = 3/1.0 + 2/1.585 + 1/2.0
          = 3.0 + 1.262 + 0.5
          = 4.762

    IDCG@3 = same (already ideal) = 4.762

    NDCG@3 = 4.762 / 4.762 = 1.0
    """
    retrieved = ["d1", "d2", "d3"]
    graded = {"d1": 3, "d2": 2, "d3": 1}
    ndcg = ndcg_at_k(retrieved, graded, k=3)
    assert ndcg == pytest.approx(1.0, abs=1e-4)


def test_ndcg_at_k_reordered():
    """Test NDCG with imperfect ranking.

    graded = {d1: 3, d2: 2, d3: 0}
    retrieved = [d1, d3, d2]  # d3 (irrelevant) is ranked 2nd
    k = 3

    DCG@3 = 3/log2(2) + 0/log2(3) + 2/log2(4)
          = 3/1.0 + 0 + 2/2.0
          = 3.0 + 0.0 + 1.0
          = 4.0

    IDCG@3 = 3/log2(2) + 2/log2(3) + 0/log2(4)  # ideal: [d1, d2, d3]
           = 3/1.0 + 2/1.585 + 0
           = 3.0 + 1.262 + 0.0
           = 4.262

    NDCG@3 = 4.0 / 4.262 ≈ 0.9385
    """
    retrieved = ["d1", "d3", "d2"]
    graded = {"d1": 3, "d2": 2, "d3": 0}
    ndcg = ndcg_at_k(retrieved, graded, k=3)
    assert ndcg == pytest.approx(4.0 / 4.262, abs=1e-4)


def test_ndcg_at_k_no_relevant():
    """Test NDCG when no relevant docs exist.

    graded = {}  # empty
    retrieved = [d1, d2, d3]
    IDCG = 0 → NDCG = 0.0
    """
    retrieved = ["d1", "d2", "d3"]
    graded = {}
    ndcg = ndcg_at_k(retrieved, graded, k=3)
    assert ndcg == 0.0


def test_ndcg_at_k_partial_judgments():
    """Test NDCG with some docs not in judgments.

    graded = {d1: 2, d3: 1}  # d2 not judged (treated as 0)
    retrieved = [d2, d1, d3]
    k = 3

    DCG@3 = 0/log2(2) + 2/log2(3) + 1/log2(4)
          = 0 + 2/1.585 + 1/2.0
          = 0 + 1.262 + 0.5
          = 1.762

    IDCG@3 = 2/log2(2) + 1/log2(3) + 0/log2(4)  # ideal: [d1, d3, d2]
           = 2/1.0 + 1/1.585 + 0
           = 2.0 + 0.631 + 0.0
           = 2.631

    NDCG@3 = 1.762 / 2.631 ≈ 0.6697
    """
    retrieved = ["d2", "d1", "d3"]
    graded = {"d1": 2, "d3": 1}
    ndcg = ndcg_at_k(retrieved, graded, k=3)
    assert ndcg == pytest.approx(1.762 / 2.631, abs=1e-3)


def test_ndcg_at_k_cutoff():
    """Test NDCG@k with k < retrieved length.

    graded = {d1: 3, d2: 2, d3: 1, d4: 0}
    retrieved = [d4, d1, d2, d3]  # d4 (irrelevant) first
    k = 2  # only look at top-2

    DCG@2 = 0/log2(2) + 3/log2(3)
          = 0 + 3/1.585
          = 1.893

    IDCG@2 = 3/log2(2) + 2/log2(3)  # ideal: [d1, d2]
           = 3/1.0 + 2/1.585
           = 3.0 + 1.262
           = 4.262

    NDCG@2 = 1.893 / 4.262 ≈ 0.4443
    """
    retrieved = ["d4", "d1", "d2", "d3"]
    graded = {"d1": 3, "d2": 2, "d3": 1, "d4": 0}
    ndcg = ndcg_at_k(retrieved, graded, k=2)
    assert ndcg == pytest.approx(1.893 / 4.262, abs=1e-3)


# ============================================================================
# map_at_k tests
# ============================================================================


def test_map_at_k_basic():
    """Test MAP@k with a simple case.

    retrieved = [rel1, notrel, rel2], relevant = {rel1, rel2}, k=3

    Relevant docs at ranks: 1, 3
    Precision@1 = 1/1 = 1.0
    Precision@3 = 2/3 ≈ 0.6667

    AP@3 = (1.0 + 0.6667) / 2 = 1.6667 / 2 ≈ 0.8333
    """
    retrieved = ["rel1", "notrel", "rel2"]
    relevant = {"rel1", "rel2"}
    map_score = map_at_k(retrieved, relevant, k=3)
    assert map_score == pytest.approx((1.0 + 2 / 3) / 2, abs=1e-4)


def test_map_at_k_perfect():
    """Test perfect MAP: all relevant docs at the top.

    retrieved = [rel1, rel2, rel3, notrel], relevant = {rel1, rel2, rel3}, k=4

    Relevant docs at ranks: 1, 2, 3
    Precision@1 = 1/1 = 1.0
    Precision@2 = 2/2 = 1.0
    Precision@3 = 3/3 = 1.0

    AP@4 = (1.0 + 1.0 + 1.0) / 3 = 1.0
    """
    retrieved = ["rel1", "rel2", "rel3", "notrel"]
    relevant = {"rel1", "rel2", "rel3"}
    map_score = map_at_k(retrieved, relevant, k=4)
    assert map_score == 1.0


def test_map_at_k_zero():
    """Test MAP when no relevant docs in top-k.

    retrieved = [notrel1, notrel2, notrel3], relevant = {rel1, rel2}, k=3
    No relevant docs found → AP@3 = 0.0
    """
    retrieved = ["notrel1", "notrel2", "notrel3"]
    relevant = {"rel1", "rel2"}
    map_score = map_at_k(retrieved, relevant, k=3)
    assert map_score == 0.0


def test_map_at_k_single_relevant():
    """Test MAP with a single relevant doc.

    retrieved = [notrel1, rel1, notrel2], relevant = {rel1}, k=3

    Relevant doc at rank: 2
    Precision@2 = 1/2 = 0.5

    AP@3 = 0.5 / 1 = 0.5
    """
    retrieved = ["notrel1", "rel1", "notrel2"]
    relevant = {"rel1"}
    map_score = map_at_k(retrieved, relevant, k=3)
    assert map_score == 0.5


def test_map_at_k_cutoff():
    """Test MAP@k with k < retrieved length.

    retrieved = [notrel1, notrel2, rel1, rel2], relevant = {rel1, rel2}, k=2

    Only top-2 considered: [notrel1, notrel2]
    No relevant docs in top-2 → AP@2 = 0.0
    """
    retrieved = ["notrel1", "notrel2", "rel1", "rel2"]
    relevant = {"rel1", "rel2"}
    map_score = map_at_k(retrieved, relevant, k=2)
    assert map_score == 0.0


def test_map_at_k_empty_relevant():
    """Empty relevant set → MAP = 0.0."""
    retrieved = ["d1", "d2", "d3"]
    relevant = set()
    map_score = map_at_k(retrieved, relevant, k=3)
    assert map_score == 0.0


# ============================================================================
# score_run tests — integration with Mode semantics
# ============================================================================


def _make_config(mode: Mode, label: str) -> Config:
    """Helper to create a minimal Config."""
    return Config.make(mode=mode, label=label, params={})


def test_score_run_approximate_with_reference():
    """Test score_run for DENSE_KNN (approximate) with reference ranking.

    Should emit Recall@k for each k, reference="exact"
    """
    config = _make_config(Mode.DENSE_KNN, "test-dense")

    # Two queries
    per_query = [
        QueryResult(query_id="q1", doc_ids=["d1", "d2", "d3"]),
        QueryResult(query_id="q2", doc_ids=["d10", "d20", "d30"]),
    ]
    run = RunResult(config=config, per_query=per_query)

    # Reference rankings (exact brute-force)
    reference = {
        "q1": ["d1", "d2", "d4"],  # retrieved gets [d1, d2, d3] → overlap@3 = 2
        "q2": ["d10", "d20", "d30"],  # perfect match
    }

    score = score_run(run, Mode.DENSE_KNN, reference, qrels=None, ks=(3,))

    # Hand computation for Recall@3:
    # q1: top-3 retrieved = {d1, d2, d3}, top-3 reference = {d1, d2, d4}
    #     intersection = {d1, d2} → 2/3 ≈ 0.6667
    # q2: top-3 retrieved = {d10, d20, d30}, top-3 reference = {d10, d20, d30}
    #     intersection = {d10, d20, d30} → 3/3 = 1.0
    # Mean = (0.6667 + 1.0) / 2 ≈ 0.8333

    assert score.get(Metric.RECALL, 3) == pytest.approx((2 / 3 + 1.0) / 2, abs=1e-4)
    assert score.reference == "exact"
    # No NDCG/MAP (qrels not provided)
    assert score.get(Metric.NDCG, 3) is None
    assert score.get(Metric.MAP, 3) is None


def test_score_run_exact_with_qrels():
    """Test score_run for SPARSE_RANK_FEATURES (exact) with qrels.

    Should emit NDCG@k and MAP@k, NOT Recall (exact mode, no reference provided).
    """
    config = _make_config(Mode.SPARSE_RANK_FEATURES, "test-sparse")

    per_query = [
        QueryResult(query_id="q1", doc_ids=["d1", "d3", "d2"]),
    ]
    run = RunResult(config=config, per_query=per_query)

    # Qrels
    qrels: Qrels = {
        "q1": {"d1": 3, "d2": 2, "d3": 0},
    }

    score = score_run(run, Mode.SPARSE_RANK_FEATURES, reference_ranking=None, qrels=qrels, ks=(3,))

    # Hand computation for NDCG@3 (from earlier test_ndcg_at_k_reordered):
    # DCG@3 = 3/log2(2) + 0/log2(3) + 2/log2(4) = 4.0
    # IDCG@3 = 4.262
    # NDCG@3 = 4.0 / 4.262 ≈ 0.9385

    # Hand computation for MAP@3:
    # retrieved = [d1, d3, d2], relevant = {d1, d2}
    # Relevant at ranks: 1, 3
    # Precision@1 = 1/1 = 1.0
    # Precision@3 = 2/3 ≈ 0.6667
    # AP@3 = (1.0 + 0.6667) / 2 ≈ 0.8333

    assert score.get(Metric.NDCG, 3) == pytest.approx(4.0 / 4.262, abs=1e-4)
    assert score.get(Metric.MAP, 3) == pytest.approx((1.0 + 2 / 3) / 2, abs=1e-4)
    # No RECALL (exact mode, no reference)
    assert score.get(Metric.RECALL, 3) is None
    assert score.reference == "qrels"


def test_score_run_exact_with_unpruned_baseline():
    """Test score_run for SPARSE_RANK_FEATURES with unpruned-baseline reference.

    Should emit Recall@k (result overlap), reference="unpruned-baseline"
    """
    config = _make_config(Mode.SPARSE_RANK_FEATURES, "test-sparse-pruned")

    per_query = [
        QueryResult(query_id="q1", doc_ids=["d1", "d2", "d3"]),
    ]
    run = RunResult(config=config, per_query=per_query)

    # Unpruned baseline reference
    reference = {
        "q1": ["d1", "d2", "d4"],  # pruned version differs at d3 vs d4
    }

    score = score_run(run, Mode.SPARSE_RANK_FEATURES, reference, qrels=None, ks=(3,))

    # Hand computation for result overlap@3:
    # top-3 retrieved = {d1, d2, d3}, top-3 reference = {d1, d2, d4}
    # intersection = {d1, d2} → 2/3 ≈ 0.6667

    assert score.get(Metric.RECALL, 3) == pytest.approx(2 / 3, abs=1e-4)
    assert score.reference == "unpruned-baseline"


def test_score_run_approximate_with_qrels():
    """Test score_run for SPARSE_ANN (approximate) with both reference and qrels.

    Should emit Recall@k (vs exact sparse) AND NDCG@k/MAP@k (vs qrels).
    """
    config = _make_config(Mode.SPARSE_ANN, "test-sparse-ann")

    per_query = [
        QueryResult(query_id="q1", doc_ids=["d1", "d2", "d3"]),
    ]
    run = RunResult(config=config, per_query=per_query)

    # Reference (exact sparse)
    reference = {
        "q1": ["d1", "d2", "d4"],
    }

    # Qrels
    qrels: Qrels = {
        "q1": {"d1": 2, "d2": 1, "d3": 1, "d4": 0},
    }

    score = score_run(run, Mode.SPARSE_ANN, reference, qrels, ks=(3,))

    # Recall@3 = 2/3 (overlap {d1, d2})
    assert score.get(Metric.RECALL, 3) == pytest.approx(2 / 3, abs=1e-4)

    # NDCG@3:
    # retrieved = [d1, d2, d3], graded = {d1: 2, d2: 1, d3: 1, d4: 0}
    # DCG@3 = 2/log2(2) + 1/log2(3) + 1/log2(4)
    #       = 2/1.0 + 1/1.585 + 1/2.0
    #       = 2.0 + 0.631 + 0.5 = 3.131
    # IDCG@3 = 2/log2(2) + 1/log2(3) + 1/log2(4)  # ideal: [d1, d2, d3] (or [d1, d3, d2])
    #        = same = 3.131
    # NDCG@3 = 3.131 / 3.131 = 1.0

    # MAP@3:
    # retrieved = [d1, d2, d3], relevant = {d1, d2, d3}
    # All relevant, perfect order → AP@3 = (1/1 + 2/2 + 3/3) / 3 = 3.0 / 3 = 1.0

    assert score.get(Metric.NDCG, 3) == pytest.approx(1.0, abs=1e-4)
    assert score.get(Metric.MAP, 3) == pytest.approx(1.0, abs=1e-4)
    assert score.reference == "exact+qrels"


def test_score_run_no_reference_no_qrels():
    """Test score_run with neither reference nor qrels → empty QualityScore."""
    config = _make_config(Mode.SPARSE_RANK_FEATURES, "test-empty")

    per_query = [
        QueryResult(query_id="q1", doc_ids=["d1", "d2", "d3"]),
    ]
    run = RunResult(config=config, per_query=per_query)

    score = score_run(run, Mode.SPARSE_RANK_FEATURES, reference_ranking=None, qrels=None, ks=(3,))

    # No metrics should be present
    assert score.get(Metric.RECALL, 3) is None
    assert score.get(Metric.NDCG, 3) is None
    assert score.get(Metric.MAP, 3) is None
    assert score.reference == ""


def test_score_run_multiple_ks():
    """Test score_run with multiple k values."""
    config = _make_config(Mode.DENSE_KNN, "test-multi-k")

    per_query = [
        QueryResult(query_id="q1", doc_ids=["d1", "d2", "d3", "d4", "d5"]),
    ]
    run = RunResult(config=config, per_query=per_query)

    reference = {
        "q1": ["d1", "d2", "d99", "d4", "d5"],  # d3 is wrong at rank 3
    }

    score = score_run(run, Mode.DENSE_KNN, reference, qrels=None, ks=(2, 3, 5))

    # Recall@2: top-2 retrieved = {d1, d2}, top-2 reference = {d1, d2} → 2/2 = 1.0
    # Recall@3: top-3 retrieved = {d1, d2, d3}, top-3 reference = {d1, d2, d99} → 2/3
    # Recall@5: top-5 retrieved = {d1, d2, d3, d4, d5}, top-5 reference = {d1, d2, d99, d4, d5} → 4/5 = 0.8

    assert score.get(Metric.RECALL, 2) == pytest.approx(1.0, abs=1e-4)
    assert score.get(Metric.RECALL, 3) == pytest.approx(2 / 3, abs=1e-4)
    assert score.get(Metric.RECALL, 5) == pytest.approx(4 / 5, abs=1e-4)


def test_score_run_empty_run():
    """Test score_run with empty per_query → empty QualityScore."""
    config = _make_config(Mode.DENSE_KNN, "test-empty-run")
    run = RunResult(config=config, per_query=[])

    score = score_run(run, Mode.DENSE_KNN, reference_ranking={}, qrels=None, ks=(3,))

    assert len(score.by_metric_k) == 0
    assert score.reference == ""


def test_score_run_missing_query_in_reference():
    """Test score_run when some queries are missing from reference → skip those."""
    config = _make_config(Mode.DENSE_KNN, "test-missing")

    per_query = [
        QueryResult(query_id="q1", doc_ids=["d1", "d2"]),
        QueryResult(query_id="q2", doc_ids=["d10", "d20"]),  # missing from reference
    ]
    run = RunResult(config=config, per_query=per_query)

    reference = {
        "q1": ["d1", "d2"],  # q2 not in reference
    }

    score = score_run(run, Mode.DENSE_KNN, reference, qrels=None, ks=(2,))

    # Only q1 contributes: Recall@2 = 2/2 = 1.0
    # Mean of [1.0] = 1.0
    assert score.get(Metric.RECALL, 2) == pytest.approx(1.0, abs=1e-4)


# ============================================================================
# Edge cases
# ============================================================================


def test_recall_at_k_negative_k():
    """Negative k → recall = 0.0."""
    retrieved = ["a", "b", "c"]
    reference = ["a", "b", "c"]
    recall = recall_at_k(retrieved, reference, k=-1)
    assert recall == 0.0


def test_ndcg_at_k_negative_k():
    """Negative k → NDCG = 0.0."""
    retrieved = ["d1", "d2"]
    graded = {"d1": 2}
    ndcg = ndcg_at_k(retrieved, graded, k=-1)
    assert ndcg == 0.0


def test_map_at_k_negative_k():
    """Negative k → MAP = 0.0."""
    retrieved = ["d1", "d2"]
    relevant = {"d1"}
    map_score = map_at_k(retrieved, relevant, k=-1)
    assert map_score == 0.0
