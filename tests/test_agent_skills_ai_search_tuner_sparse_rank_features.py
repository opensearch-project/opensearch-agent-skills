"""Tests for sparse_rank_features.py: Traditional Neural Sparse mode (EXACT).

Critical assertions (per task requirements):
1. QualityScore RECALL entries MUST be labeled reference="unpruned-baseline" (result
   overlap), NEVER "fidelity-to-exact" (mode.is_approximate is FALSE for this mode).
2. With qrels: NDCG present.
3. ConfigGenerator enables two_phase by default and NEVER emits forbidden params.
4. CostProbe reads cat_indices store.size; pruned configs can have smaller synthesized
   size (set fake.indices[name]["_size_bytes"]).
5. Teardown removes both index AND pipeline after exit and after exception.
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
from contextlib import contextmanager

from model import (
    Capabilities,
    Config,
    Cost,
    Measurement,
    Metric,
    Mode,
    QualityScore,
)
from corpus import Corpus, Document, Query, QuerySet, Qrels
from sparse_rank_features import (
    SparseRankFeaturesPlugin,
    VERIFIED_PARAMS,
    FORBIDDEN_PARAMS,
)
from fake_client import FakeOSClient
from runner import benchmark


# --- Fixtures ---


@pytest.fixture
def fake_client():
    """FakeOSClient with neural-search plugin + sparse model."""
    return FakeOSClient(
        version="2.17.1",
        plugins=["opensearch-knn", "opensearch-neural-search", "opensearch-ml"],
        ml_model_ids=["sparse-doc-v3"],
    )


@pytest.fixture
def corpus():
    """Small text corpus (~15 docs) for testing."""
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
        Document(id="d12", text="approximate nearest neighbor search"),
        Document(id="d13", text="recall precision tradeoff"),
        Document(id="d14", text="query understanding natural language"),
        Document(id="d15", text="document ranking relevance scoring"),
    ]
    return Corpus(documents=docs)


@pytest.fixture
def queries():
    """Small query set."""
    return QuerySet(
        [
            Query(id="q1", text="sparse search models"),
            Query(id="q2", text="neural retrieval systems"),
            Query(id="q3", text="index optimization"),
        ]
    )


@pytest.fixture
def qrels():
    """Minimal qrels for NDCG testing."""
    return {
        "q1": {"d2": 3, "d5": 2, "d11": 1},  # q1: sparse search models
        "q2": {"d1": 3, "d9": 2, "d5": 1},  # q2: neural retrieval systems
        "q3": {"d7": 2, "d8": 2},  # q3: index optimization
    }


@pytest.fixture
def capabilities():
    """Capabilities with sparse_rank_features enabled."""
    return Capabilities(
        version="2.17.1",
        dense_knn=True,
        sparse_rank_features=True,
        sparse_ann=False,
        hybrid=False,
        sparse_models=("sparse-doc-v3",),
    )


# --- Tests ---


def test_plugin_is_available(capabilities):
    """Plugin is available when sparse_rank_features capability is present."""
    plugin = SparseRankFeaturesPlugin()
    assert plugin.is_available(capabilities)

    cap_without = Capabilities(version="2.17.1", sparse_rank_features=False)
    assert not plugin.is_available(cap_without)


def test_config_generator_enables_two_phase_by_default(capabilities, corpus):
    """ConfigGenerator enables two_phase_parameter by default."""
    plugin = SparseRankFeaturesPlugin()
    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)

    assert len(configs) > 0
    for config in configs:
        two_phase = config.get("two_phase_parameter")
        assert two_phase is not None, f"Config {config.label} missing two_phase_parameter"
        # two_phase is a dict with enabled=True
        assert isinstance(two_phase, tuple)  # frozen dict becomes tuple of tuples
        two_phase_dict = dict(two_phase)
        assert two_phase_dict.get("enabled") is True


def test_config_generator_never_emits_forbidden_params(capabilities, corpus):
    """ConfigGenerator NEVER emits forbidden params (DESIGN §10.3)."""
    plugin = SparseRankFeaturesPlugin()
    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)

    for config in configs:
        param_keys = {k for k, _ in config.params}
        forbidden_found = param_keys & FORBIDDEN_PARAMS
        assert not forbidden_found, (
            f"Config {config.label} emits forbidden params: {forbidden_found}. "
            f"Forbidden: {FORBIDDEN_PARAMS}"
        )


def test_config_generator_only_emits_verified_params(capabilities, corpus):
    """ConfigGenerator only emits verified params (DESIGN §5, §10.3)."""
    plugin = SparseRankFeaturesPlugin()
    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)

    for config in configs:
        param_keys = {k for k, _ in config.params}
        unverified = param_keys - VERIFIED_PARAMS
        assert not unverified, (
            f"Config {config.label} emits unverified params: {unverified}. "
            f"Verified: {VERIFIED_PARAMS}"
        )


def test_config_generator_caps_at_10(capabilities, corpus):
    """ConfigGenerator hard-caps at ~10 configs."""
    plugin = SparseRankFeaturesPlugin()
    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)
    assert len(configs) <= 10


def test_cost_probe_reads_cat_indices_store_size(fake_client, corpus, capabilities):
    """CostProbe reads store.size from cat_indices."""
    plugin = SparseRankFeaturesPlugin()
    builder = plugin.index_builder(fake_client)
    probe = plugin.cost_probe(fake_client)

    config = Config.make(
        Mode.SPARSE_RANK_FEATURES,
        "test-cost",
        {"model_id": "sparse-doc-v3", "prune_type": "none", "prune_ratio": None},
    )

    with builder.build(config, corpus) as built:
        # Synthesize a size for this index.
        fake_client.indices[built.index_name]["_size_bytes"] = 1024 * 500  # 500KB

        cost = probe.measure(built)
        assert cost.index_size_bytes == 1024 * 500


def test_cost_probe_pruned_vs_unpruned_size(fake_client, corpus, capabilities):
    """Pruned config can have smaller synthesized size than unpruned."""
    plugin = SparseRankFeaturesPlugin()
    builder = plugin.index_builder(fake_client)
    probe = plugin.cost_probe(fake_client)

    unpruned_config = Config.make(
        Mode.SPARSE_RANK_FEATURES,
        "unpruned",
        {"model_id": "sparse-doc-v3", "prune_type": "none", "prune_ratio": None},
    )

    pruned_config = Config.make(
        Mode.SPARSE_RANK_FEATURES,
        "pruned-0.1",
        {"model_id": "sparse-doc-v3", "prune_type": "max_ratio", "prune_ratio": 0.1},
    )

    with builder.build(unpruned_config, corpus) as built_unpruned:
        fake_client.indices[built_unpruned.index_name]["_size_bytes"] = 1024 * 1000  # 1MB
        cost_unpruned = probe.measure(built_unpruned)

    with builder.build(pruned_config, corpus) as built_pruned:
        # Pruned index is smaller (simulate 60% of unpruned).
        fake_client.indices[built_pruned.index_name]["_size_bytes"] = 1024 * 600  # 600KB
        cost_pruned = probe.measure(built_pruned)

    assert cost_unpruned.index_size_bytes == 1024 * 1000
    assert cost_pruned.index_size_bytes == 1024 * 600
    assert cost_pruned.index_size_bytes < cost_unpruned.index_size_bytes


def test_teardown_removes_index_and_pipeline(fake_client, corpus):
    """IndexBuilder teardown removes both index and pipeline."""
    plugin = SparseRankFeaturesPlugin()
    builder = plugin.index_builder(fake_client)

    config = Config.make(
        Mode.SPARSE_RANK_FEATURES,
        "teardown-test",
        {"model_id": "sparse-doc-v3", "prune_type": "none", "prune_ratio": None},
    )

    index_name_captured = None
    pipeline_id_captured = None

    with builder.build(config, corpus) as built:
        index_name_captured = built.index_name
        pipeline_id_captured = built.extra["pipeline_id"]

        # During context, they should exist.
        assert index_name_captured in fake_client.indices
        assert pipeline_id_captured in fake_client.ingest_pipelines

    # After exit, they should be gone.
    assert index_name_captured not in fake_client.indices
    assert pipeline_id_captured not in fake_client.ingest_pipelines


def test_teardown_on_exception(fake_client, corpus):
    """IndexBuilder teardown happens even on exception."""
    plugin = SparseRankFeaturesPlugin()
    builder = plugin.index_builder(fake_client)

    config = Config.make(
        Mode.SPARSE_RANK_FEATURES,
        "exception-test",
        {"model_id": "sparse-doc-v3", "prune_type": "none", "prune_ratio": None},
    )

    index_name_captured = None
    pipeline_id_captured = None

    with pytest.raises(RuntimeError, match="Simulated error"):
        with builder.build(config, corpus) as built:
            index_name_captured = built.index_name
            pipeline_id_captured = built.extra["pipeline_id"]
            raise RuntimeError("Simulated error")

    # Even after exception, teardown should have happened.
    assert index_name_captured not in fake_client.indices
    assert pipeline_id_captured not in fake_client.ingest_pipelines


def test_quality_score_without_qrels_has_unpruned_baseline_label(
    fake_client, corpus, queries, capabilities
):
    """Without qrels: RECALL entries labeled 'unpruned-baseline', NOT 'exact'."""
    plugin = SparseRankFeaturesPlugin()

    # Generate one config to test.
    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)[:1]

    measurements = benchmark(
        plugin=plugin,
        client=fake_client,
        corpus=corpus,
        queries=queries,
        configs=configs,
        qrels=None,  # No qrels
        ks=(5, 10),
    )

    assert len(measurements) > 0
    for m in measurements:
        quality = m.quality
        # Reference should be "unpruned-baseline", not "exact" or "fp32-brute-force".
        assert quality.reference == "unpruned-baseline", (
            f"Expected reference='unpruned-baseline' for SPARSE_RANK_FEATURES without qrels, "
            f"got '{quality.reference}'"
        )

        # RECALL entries should be present (result overlap vs unpruned).
        recall_10 = quality.get(Metric.RECALL, 10)
        assert recall_10 is not None, "Expected RECALL@10 to be present"


def test_quality_score_with_qrels_has_ndcg(fake_client, corpus, queries, qrels, capabilities):
    """With qrels: NDCG present, reference includes 'qrels'."""
    plugin = SparseRankFeaturesPlugin()

    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)[:1]

    measurements = benchmark(
        plugin=plugin,
        client=fake_client,
        corpus=corpus,
        queries=queries,
        configs=configs,
        qrels=qrels,
        ks=(5, 10),
    )

    assert len(measurements) > 0
    for m in measurements:
        quality = m.quality
        # Reference should include "qrels".
        assert "qrels" in quality.reference.lower(), (
            f"Expected reference to include 'qrels', got '{quality.reference}'"
        )

        # NDCG should be present.
        ndcg_10 = quality.get(Metric.NDCG, 10)
        assert ndcg_10 is not None, "Expected NDCG@10 to be present with qrels"


def test_no_false_recall_fidelity_to_exact_label(fake_client, corpus, queries, capabilities):
    """CRITICAL: RECALL must NOT be labeled as 'fidelity-to-exact' or 'exact' alone.

    For SPARSE_RANK_FEATURES (mode.is_approximate=False), RECALL entries measuring
    result overlap vs unpruned baseline MUST be labeled 'unpruned-baseline', NOT
    as fidelity-to-exact (which would be misleading since this mode IS exact).
    """
    plugin = SparseRankFeaturesPlugin()

    # Verify mode property.
    assert not plugin.mode.is_approximate, (
        "SPARSE_RANK_FEATURES must have is_approximate=False"
    )

    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)[:2]

    measurements = benchmark(
        plugin=plugin,
        client=fake_client,
        corpus=corpus,
        queries=queries,
        configs=configs,
        qrels=None,  # No qrels → only unpruned-baseline overlap
        ks=(5, 10),
    )

    for m in measurements:
        quality = m.quality
        # Reference must be "unpruned-baseline", not "exact" or "fp32-brute-force".
        assert quality.reference == "unpruned-baseline", (
            f"SPARSE_RANK_FEATURES RECALL must be labeled 'unpruned-baseline' "
            f"(result overlap), not '{quality.reference}' (fidelity-to-exact). "
            f"This is EXACT Lucene scoring, no recall-vs-exact to tune."
        )

        # RECALL entries are measuring result overlap, not approximation fidelity.
        for metric, k in quality.by_metric_k:
            if metric == Metric.RECALL:
                # Presence of RECALL is fine (overlap measurement), but the label
                # MUST be correct.
                pass


def test_full_benchmark_run(fake_client, corpus, queries, qrels, capabilities):
    """Full integration: benchmark runs, produces measurements with quality and cost."""
    plugin = SparseRankFeaturesPlugin()

    gen = plugin.config_generator()
    configs = gen.seed_configs(capabilities, corpus)[:3]

    measurements = benchmark(
        plugin=plugin,
        client=fake_client,
        corpus=corpus,
        queries=queries,
        configs=configs,
        qrels=qrels,
        ks=(5, 10),
    )

    # Should have measurements for all configs (no failures).
    assert len(measurements) == len(configs)

    for m in measurements:
        # Quality: should have RECALL (overlap) and NDCG (qrels).
        assert m.quality.get(Metric.RECALL, 10) is not None
        assert m.quality.get(Metric.NDCG, 10) is not None

        # Reference label should include both.
        assert "unpruned-baseline" in m.quality.reference
        assert "qrels" in m.quality.reference

        # Cost: index_size_bytes should be present.
        assert m.cost.index_size_bytes is not None
        assert m.cost.index_size_bytes >= 0

        # Latency: should be positive.
        assert m.latency_p50_ms > 0
        assert m.latency_p95_ms >= m.latency_p50_ms
        assert m.latency_p99_ms >= m.latency_p95_ms


def test_reference_provider_unpruned_baseline_kind():
    """ReferenceProvider.kind must be 'unpruned-baseline'."""
    from sparse_rank_features import SparseRankFeaturesReferenceProvider

    fake = FakeOSClient()
    corpus = Corpus([Document(id="d1", text="test")])
    ref = SparseRankFeaturesReferenceProvider(fake, corpus, None)

    assert ref.kind == "unpruned-baseline"


def test_mode_is_approximate_false():
    """SPARSE_RANK_FEATURES mode MUST have is_approximate=False."""
    assert Mode.SPARSE_RANK_FEATURES.is_approximate is False, (
        "SPARSE_RANK_FEATURES is EXACT Lucene scoring, not approximate. "
        "mode.is_approximate must be False."
    )
