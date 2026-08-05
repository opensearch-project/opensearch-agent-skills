"""Tests for sparse_ann.py: Neural Sparse ANN mode (sparse_vector / SEISMIC, APPROXIMATE).

Critical assertions (the crux distinction from sparse_rank_features):
1. Mode.SPARSE_ANN.is_approximate is TRUE — this mode genuinely approximates
   exact sparse, so RECALL@k vs exact is meaningful (unlike rank_features).
2. QualityScore RECALL entries are labeled reference="exact-sparse" (fidelity to
   exact sparse), plus a "+qrels" suffix when qrels are supplied.
3. Recall RISES with heap_factor (the ef_search analog) — the recall-vs-exact story.
4. ConfigGenerator sweeps heap_factor first, keeps top_n/heap_factor UNDER
   method_parameters, only emits verified params, never forbidden ones, caps ~12.
5. CostProbe reads cat_indices store.size.
6. Teardown removes both index AND pipeline, even on exception.
7. Plugin gates on sparse_ann capability AND a deployed sparse model.
"""

from __future__ import annotations


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

from model import Capabilities, Config, Metric, Mode
from corpus import Corpus, Document, Query, QuerySet
from sparse_ann import (
    SparseAnnPlugin,
    SparseAnnConfigGenerator,
    SparseAnnReferenceProvider,
    VERIFIED_PARAMS,
    FORBIDDEN_PARAMS,
)
from fake_client import FakeOSClient
from runner import benchmark


# --- Fixtures ---


@pytest.fixture
def fake_client():
    """FakeOSClient at 3.3+ with neural-search plugin + a deployed sparse model."""
    return FakeOSClient(
        version="3.3.0",
        plugins=["opensearch-knn", "opensearch-neural-search", "opensearch-ml"],
        ml_model_ids=["sparse-doc-v3"],
    )


@pytest.fixture
def corpus():
    docs = [
        Document(id="d1", text="retrieval augmented generation systems"),
        Document(id="d2", text="neural sparse search models"),
        Document(id="d3", text="dense vector embeddings for search"),
        Document(id="d4", text="hybrid search combines dense and sparse"),
        Document(id="d5", text="opensearch neural search plugin"),
        Document(id="d6", text="lucene rank features exact scoring"),
        Document(id="d7", text="two phase query processing optimization"),
        Document(id="d8", text="token pruning reduces index size"),
        Document(id="d9", text="semantic search with transformers"),
        Document(id="d10", text="information retrieval evaluation metrics"),
        Document(id="d11", text="learned sparse representations"),
        Document(id="d12", text="approximate nearest neighbor search seismic clusters"),
        Document(id="d13", text="recall precision tradeoff heap factor"),
        Document(id="d14", text="query understanding natural language search"),
        Document(id="d15", text="document ranking relevance scoring search"),
    ]
    return Corpus(documents=docs)


@pytest.fixture
def queries():
    return QuerySet(
        [
            Query(id="q1", text="sparse search models"),
            Query(id="q2", text="neural retrieval search systems"),
            Query(id="q3", text="approximate nearest neighbor search"),
        ]
    )


@pytest.fixture
def qrels():
    return {
        "q1": {"d2": 3, "d5": 2, "d11": 1},
        "q2": {"d1": 3, "d9": 2, "d5": 1},
        "q3": {"d12": 3, "d3": 1},
    }


@pytest.fixture
def capabilities():
    """Capabilities with sparse_ann (SEISMIC) enabled — version >= 3.3."""
    return Capabilities(
        version="3.3.0",
        dense_knn=True,
        sparse_rank_features=True,
        sparse_ann=True,
        hybrid=True,
        sparse_models=("sparse-doc-v3",),
    )


# --- Mode property (the crux) ---


def test_mode_is_approximate_true():
    """SPARSE_ANN (SEISMIC) MUST be approximate — recall-vs-exact is meaningful."""
    assert Mode.SPARSE_ANN.is_approximate is True, (
        "SPARSE_ANN approximates exact sparse scoring; is_approximate must be True."
    )


# --- Availability gating ---


def test_plugin_available_with_seismic_and_model(capabilities):
    plugin = SparseAnnPlugin()
    assert plugin.is_available(capabilities)


def test_plugin_unavailable_without_seismic():
    """Below 3.3 (sparse_ann=False), the mode is cleanly skipped."""
    plugin = SparseAnnPlugin()
    cap = Capabilities(
        version="2.17.1",
        sparse_rank_features=True,
        sparse_ann=False,
        sparse_models=("sparse-doc-v3",),
    )
    assert not plugin.is_available(cap)


def test_plugin_unavailable_without_model(capabilities):
    """SEISMIC present but no deployed sparse model → skip (graceful degradation)."""
    plugin = SparseAnnPlugin()
    cap = Capabilities(version="3.3.0", sparse_ann=True, sparse_models=())
    assert not plugin.is_available(cap)


# --- ConfigGenerator ---


def test_config_generator_sweeps_heap_factor_first(capabilities, corpus):
    """Primary sweep varies heap_factor (the ef_search analog) at fixed n_postings."""
    gen = SparseAnnConfigGenerator()
    configs = gen.seed_configs(capabilities, corpus)
    assert len(configs) > 0

    heap_factors = []
    for c in configs:
        mp = dict(c.get("method_parameters"))
        assert "heap_factor" in mp, f"{c.label} missing method_parameters.heap_factor"
        assert "top_n" in mp, f"{c.label} missing method_parameters.top_n"
        heap_factors.append(mp["heap_factor"])

    # More than one distinct heap_factor is swept.
    assert len({hf for hf in heap_factors}) >= 3


def test_config_generator_only_verified_params(capabilities, corpus):
    gen = SparseAnnConfigGenerator()
    for config in gen.seed_configs(capabilities, corpus):
        keys = {k for k, _ in config.params}
        unverified = keys - VERIFIED_PARAMS
        assert not unverified, f"{config.label} emits unverified params: {unverified}"


def test_config_generator_never_forbidden_params(capabilities, corpus):
    """Never emit dense/HNSW knobs, rank_features pruning, two_phase, or a bare
    top-level heap_factor/top_n (they must nest under method_parameters)."""
    gen = SparseAnnConfigGenerator()
    for config in gen.seed_configs(capabilities, corpus):
        keys = {k for k, _ in config.params}
        forbidden = keys & FORBIDDEN_PARAMS
        assert not forbidden, f"{config.label} emits forbidden params: {forbidden}"


def test_config_generator_caps_at_12(capabilities, corpus):
    gen = SparseAnnConfigGenerator()
    assert len(gen.seed_configs(capabilities, corpus)) <= 12


def test_config_generator_no_model_returns_empty(corpus):
    gen = SparseAnnConfigGenerator()
    cap = Capabilities(version="3.3.0", sparse_ann=True, sparse_models=())
    assert gen.seed_configs(cap, corpus) == []


# --- Query runner: approximate path passes method_parameters ---


def test_query_runner_passes_method_parameters(fake_client, corpus, capabilities):
    plugin = SparseAnnPlugin()
    builder = plugin.index_builder(fake_client)
    runner = plugin.query_runner(fake_client)

    config = Config.make(
        Mode.SPARSE_ANN,
        "probe",
        {
            "model_id": "sparse-doc-v3",
            "n_postings": 4000,
            "method_parameters": {"top_n": 10, "heap_factor": 1.0},
        },
    )
    q = QuerySet([Query(id="q1", text="neural sparse search")])
    with builder.build(config, corpus) as built:
        result = runner.run(built, q)
    assert len(result.per_query) == 1
    assert result.per_query[0].doc_ids  # got hits


# --- CostProbe ---


def test_cost_probe_reads_store_size(fake_client, corpus):
    plugin = SparseAnnPlugin()
    builder = plugin.index_builder(fake_client)
    probe = plugin.cost_probe(fake_client)

    config = Config.make(
        Mode.SPARSE_ANN,
        "cost",
        {"model_id": "sparse-doc-v3", "n_postings": 4000, "cluster_ratio": 0.1,
         "method_parameters": {"top_n": 10, "heap_factor": 1.0}},
    )
    with builder.build(config, corpus) as built:
        fake_client.indices[built.index_name]["_size_bytes"] = 1024 * 700
        cost = probe.measure(built)
    assert cost.index_size_bytes == 1024 * 700


# --- Teardown ---


def test_teardown_removes_index_and_pipeline(fake_client, corpus):
    plugin = SparseAnnPlugin()
    builder = plugin.index_builder(fake_client)
    config = Config.make(
        Mode.SPARSE_ANN, "teardown",
        {"model_id": "sparse-doc-v3", "method_parameters": {"top_n": 10, "heap_factor": 1.0}},
    )
    with builder.build(config, corpus) as built:
        idx, pipe = built.index_name, built.extra["pipeline_id"]
        assert idx in fake_client.indices
        assert pipe in fake_client.ingest_pipelines
    assert idx not in fake_client.indices
    assert pipe not in fake_client.ingest_pipelines


def test_teardown_on_exception(fake_client, corpus):
    plugin = SparseAnnPlugin()
    builder = plugin.index_builder(fake_client)
    config = Config.make(
        Mode.SPARSE_ANN, "boom",
        {"model_id": "sparse-doc-v3", "method_parameters": {"top_n": 10, "heap_factor": 1.0}},
    )
    idx = pipe = None
    with pytest.raises(RuntimeError, match="Simulated error"):
        with builder.build(config, corpus) as built:
            idx, pipe = built.index_name, built.extra["pipeline_id"]
            raise RuntimeError("Simulated error")
    assert idx not in fake_client.indices
    assert pipe not in fake_client.ingest_pipelines


# --- ReferenceProvider ---


def test_reference_provider_kind_is_exact_sparse():
    fake = FakeOSClient(version="3.3.0")
    corpus = Corpus([Document(id="d1", text="test")])
    ref = SparseAnnReferenceProvider(fake, corpus, None)
    assert ref.kind == "exact-sparse"


# --- Quality scoring semantics ---


def test_recall_labeled_exact_sparse_without_qrels(fake_client, corpus, queries, capabilities):
    """RECALL entries labeled 'exact-sparse' (fidelity-to-exact), NOT unpruned-baseline."""
    plugin = SparseAnnPlugin()
    configs = plugin.config_generator().seed_configs(capabilities, corpus)[:2]
    measurements = benchmark(
        plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
        configs=configs, qrels=None, ks=(5, 10),
    )
    assert measurements
    for m in measurements:
        assert m.quality.reference == "exact-sparse", (
            f"SPARSE_ANN recall must be fidelity-to-exact-sparse, got '{m.quality.reference}'"
        )
        assert m.quality.get(Metric.RECALL, 10) is not None


def test_quality_with_qrels_has_ndcg_and_exact_sparse(fake_client, corpus, queries, qrels, capabilities):
    plugin = SparseAnnPlugin()
    configs = plugin.config_generator().seed_configs(capabilities, corpus)[:2]
    measurements = benchmark(
        plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
        configs=configs, qrels=qrels, ks=(5, 10),
    )
    assert measurements
    for m in measurements:
        assert "exact-sparse" in m.quality.reference
        assert "qrels" in m.quality.reference.lower()
        assert m.quality.get(Metric.NDCG, 10) is not None


def test_recall_rises_with_heap_factor(fake_client, corpus, queries, capabilities):
    """The recall-vs-exact story: higher heap_factor (the ef_search analog) ⇒
    higher recall@k vs the exact-sparse reference."""
    plugin = SparseAnnPlugin()

    def recall_for(hf: float) -> float:
        config = Config.make(
            Mode.SPARSE_ANN, f"heap={hf}",
            {"model_id": "sparse-doc-v3", "n_postings": 4000, "cluster_ratio": 0.1,
             "summary_prune_ratio": 0.4,
             "method_parameters": {"top_n": 10, "heap_factor": hf}},
        )
        ms = benchmark(
            plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
            configs=[config], qrels=None, ks=(10,),
        )
        assert ms
        return ms[0].quality.get(Metric.RECALL, 10)

    low = recall_for(0.5)
    high = recall_for(2.0)
    assert high >= low, f"recall should rise with heap_factor: hf=0.5→{low}, hf=2.0→{high}"
    assert high > low  # strictly higher given the fake's miss model


def test_full_benchmark_run(fake_client, corpus, queries, qrels, capabilities):
    plugin = SparseAnnPlugin()
    configs = plugin.config_generator().seed_configs(capabilities, corpus)[:4]
    measurements = benchmark(
        plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
        configs=configs, qrels=qrels, ks=(5, 10),
    )
    assert len(measurements) == len(configs)
    for m in measurements:
        assert m.quality.get(Metric.RECALL, 10) is not None
        assert m.quality.get(Metric.NDCG, 10) is not None
        assert m.cost.index_size_bytes is not None and m.cost.index_size_bytes >= 0
        assert m.latency_p50_ms > 0
        assert m.latency_p95_ms >= m.latency_p50_ms


# --- Agentic refinement: lower top_n after the recall floor is met ---


def test_refine_proposes_lower_top_n_when_floor_met(fake_client, corpus, queries, capabilities):
    """After the heap_factor sweep, refine() should trade query terms (top_n) for
    latency: propose SMALLER top_n variants at the qualifying config's heap_factor."""
    plugin = SparseAnnPlugin()
    gen = plugin.config_generator()
    seed = gen.seed_configs(capabilities, corpus)
    ms = benchmark(
        plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
        configs=seed, qrels=None, ks=(10,), quality_floor=0.8,
    )
    follow = gen.refine(ms, quality_floor=0.8, latency_budget_ms=None)
    assert follow, "expected top_n follow-ups once a config met the recall floor"
    # every follow-up carries a top_n strictly below the seed default (10),
    # nested under method_parameters (never top-level).
    for c in follow:
        mp = dict(c.get("method_parameters"))
        assert "top_n" in mp and mp["top_n"] < 10
        assert "top_n" not in {k for k, _ in c.params}  # not at top level


def test_refine_is_one_shot(fake_client, corpus, queries, capabilities):
    """refine() proposes the ladder once, then returns [] so the CLI loop stops."""
    plugin = SparseAnnPlugin()
    gen = plugin.config_generator()
    seed = gen.seed_configs(capabilities, corpus)
    ms = benchmark(
        plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
        configs=seed, qrels=None, ks=(10,), quality_floor=0.8,
    )
    assert gen.refine(ms, 0.8, None)      # first call: proposals
    assert gen.refine(ms, 0.8, None) == []  # second call: stop


def test_refine_stops_without_floor_or_when_unmet(fake_client, corpus, queries, capabilities):
    """No recall floor → no refinement. Floor nobody meets → no refinement."""
    plugin = SparseAnnPlugin()
    seed = plugin.config_generator().seed_configs(capabilities, corpus)
    ms = benchmark(
        plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
        configs=seed, qrels=None, ks=(10,), quality_floor=0.8,
    )
    assert SparseAnnConfigGenerator().refine(ms, None, None) == []       # no floor
    assert SparseAnnConfigGenerator().refine(ms, 1.01, None) == []       # impossible floor


def test_lower_top_n_cuts_latency(fake_client, corpus, queries, capabilities):
    """The payoff: at a fixed heap_factor, a smaller top_n yields lower p95 latency."""
    plugin = SparseAnnPlugin()

    def p95_for(top_n: int) -> float:
        cfg = Config.make(
            Mode.SPARSE_ANN, f"topn={top_n}",
            {"model_id": "sparse-doc-v3", "n_postings": 4000, "cluster_ratio": 0.1,
             "summary_prune_ratio": 0.4,
             "method_parameters": {"top_n": top_n, "heap_factor": 1.0}},
        )
        ms = benchmark(
            plugin=plugin, client=fake_client, corpus=corpus, queries=queries,
            configs=[cfg], qrels=None, ks=(10,),
        )
        return ms[0].latency_p95_ms

    assert p95_for(5) < p95_for(10), "lower top_n should reduce latency"
