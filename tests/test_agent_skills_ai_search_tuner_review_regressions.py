"""Regression tests locking in the adversarial-review fixes.

These guard the exact failure inputs the reviewer traced, so the bugs can never
silently return. The MAP one is the most important: a wrong MAP in front of
OpenSearch maintainers would be fatal.
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

from quality import map_at_k, score_run
from model import Mode, Metric
from corpus import Corpus, Document
from runner import benchmark
from dense_knn import DenseKnnPlugin
from fake_client import FakeOSClient


# ---- Finding 1: MAP denominator ----

def test_map_partial_recall_not_inflated():
    # 1 of 2 relevant docs, at rank 1. Old (buggy) code returned 1.0.
    # Correct AP@5 = (1/min(5,2)) * P@1 = (1/2)*1.0 = 0.5
    assert abs(map_at_k(["rel1", "x", "y", "z", "w"], {"rel1", "rel2"}, 5) - 0.5) < 1e-9


def test_map_one_of_four_relevant():
    # 1 of 4 relevant, at rank 2. Correct = (1/4)*(1/2) = 0.125 (old code: 0.5)
    assert abs(map_at_k(["x", "rel1", "y", "z"], {"rel1", "r2", "r3", "r4"}, 4) - 0.125) < 1e-9


def test_map_perfect_still_one():
    assert abs(map_at_k(["a", "b"], {"a", "b"}, 5) - 1.0) < 1e-9


def test_map_none_retrieved_zero():
    assert map_at_k(["x", "y"], {"a", "b"}, 5) == 0.0


# ---- Finding 3: queries with no relevant docs excluded from NDCG/MAP mean ----

def test_score_run_skips_empty_relevant_queries():
    from model import QueryResult, RunResult, Config
    run = RunResult(
        config=Config.make(Mode.DENSE_KNN, "c", {}),
        per_query=[
            QueryResult(query_id="q1", doc_ids=["a", "b"]),
            QueryResult(query_id="q2", doc_ids=["x", "y"]),  # q2 has no relevant
        ],
    )
    qrels = {"q1": {"a": 1, "b": 1}, "q2": {"x": 0, "y": 0}}
    score = score_run(run, Mode.DENSE_KNN, reference_ranking=None, qrels=qrels, ks=(5,))
    # q1 is perfect (ndcg 1.0); q2 (no relevant) must be EXCLUDED, not averaged as 0.
    ndcg = score.get(Metric.NDCG, 5)
    assert ndcg == 1.0, f"empty-relevant query biased the mean: {ndcg}"


# ---- Finding 2: dense reference index is unique + torn down ----

def _corpus(n=12, dim=4):
    docs = []
    for i in range(n):
        v = [0.0] * dim
        v[i % dim] = 1.0
        docs.append(Document(id=f"d{i}", text=f"doc {i}", vector=v))
    return Corpus(documents=docs, dim=dim)


def test_reference_index_torn_down_after_benchmark():
    fake = FakeOSClient()
    corpus = _corpus()
    from corpus import sample_queries_from_corpus
    queries = sample_queries_from_corpus(corpus, n=4, seed=0)
    plugin = DenseKnnPlugin()
    gen = plugin.config_generator()
    from model import Capabilities
    cap = Capabilities(version="2.17.1", dense_knn=True, quantization=("fp32",))
    configs = gen.seed_configs(cap, corpus)

    benchmark(plugin, fake, corpus, queries, configs, qrels=None, ks=(5,))

    # No index whose name starts with the reference prefix may remain.
    leaked = [n for n in fake.indices if n.startswith("rt-dense-reference-exact")]
    assert not leaked, f"reference index leaked: {leaked}"
    # And per-config indices are gone too (IndexBuilder teardown).
    assert not [n for n in fake.indices if n.startswith("rt-dense-")], fake.indices


def test_reference_index_name_is_unique_per_instance():
    fake = FakeOSClient()
    corpus = _corpus()
    p1 = DenseKnnPlugin().reference_provider(fake, corpus, None)
    p2 = DenseKnnPlugin().reference_provider(fake, corpus, None)
    n1 = p1._ensure_reference_index()
    n2 = p2._ensure_reference_index()
    assert n1 != n2, "reference index names must be unique per provider instance"
    p1.close()
    p2.close()
    assert not [n for n in fake.indices if n.startswith("rt-dense-reference-exact")]
