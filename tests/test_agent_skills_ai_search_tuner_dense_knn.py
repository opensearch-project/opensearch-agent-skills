"""Tests for dense_knn.py — the MVP core mode.

Test coverage:
    - Full loop through harness (benchmark) with recall < 1.0 for approximate
    - Exact reference path yields recall 1.0
    - CostProbe scales with num_vectors and m
    - Index teardown (context manager cleanup)
    - ConfigGenerator respects Capabilities.quantization and caps count
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

from dense_knn import DenseKnnPlugin
from fake_client import FakeOSClient
from corpus import Corpus, Document, Query, QuerySet
from model import Capabilities, Config, Metric, Mode
from runner import benchmark


def test_full_loop_recall_methodology():
    """End-to-end: approximate recall < 1.0, exact reference recall = 1.0.

    This is the CRITICAL test that proves the recall methodology works:
        - Approximate knn queries (via knn body) yield recall < 1.0 when
          FakeOSClient.approx_miss_fraction > 0
        - Exact reference (via script_score with params.query_value) yields
          recall 1.0 (or very close, within tolerance)

    This demonstrates that the tool can detect silent recall regressions.
    """
    # Build a small corpus: 20 docs, dim=4, hand-chosen vectors for determinism
    docs = [
        Document(id=f"doc{i}", vector=[float(i), float(i+1), float(i+2), float(i+3)])
        for i in range(20)
    ]
    corpus = Corpus(documents=docs, dim=4)

    # Sample queries from the corpus (first 3 docs as queries)
    queries = QuerySet(queries=[
        Query(id=f"q{i}", vector=docs[i].vector) for i in range(3)
    ])

    # FakeOSClient with approx_miss_fraction = 0.3 (drops 30% of true top-k)
    fake = FakeOSClient(version="2.17.1", plugins=["opensearch-knn"])
    fake.approx_miss_fraction = 0.3

    # Build a test config (FP32, ef_search=100)
    config = Config.make(
        mode=Mode.DENSE_KNN,
        label="test-fp32",
        params={
            "m": 16,
            "ef_construction": 100,
            "ef_search": 100,
            "encoder": "fp32",
            "k": 10,
        },
    )

    # Capabilities (dense_knn available, no special quantization)
    cap = Capabilities(version="2.17.1", dense_knn=True, quantization=("fp32",))

    # Run benchmark via the harness
    plugin = DenseKnnPlugin()
    assert plugin.is_available(cap)

    measurements = benchmark(
        plugin=plugin,
        client=fake,
        corpus=corpus,
        queries=queries,
        configs=[config],
        qrels=None,
        ks=(5, 10),
    )

    # Should have 1 measurement
    assert len(measurements) == 1
    meas = measurements[0]

    # Check recall@10 for the approximate config
    recall_10_approx = meas.quality.get(Metric.RECALL, 10)
    assert recall_10_approx is not None
    # With approx_miss_fraction=0.3, we expect recall < 1.0
    # Exact value depends on the deterministic drop; should be around 0.7
    assert 0.5 < recall_10_approx < 1.0, f"Expected recall < 1.0, got {recall_10_approx}"

    # The reference ranking should be EXACT (script_score path)
    # To verify, we'll check that the reference itself is correct by running
    # the reference provider directly and comparing against known exact ranking.

    # Compute reference ranking directly
    ref_provider = plugin.reference_provider(fake, corpus, None)
    ref_ranking = ref_provider.reference_ranking(queries, k=10)

    # For each query, the reference ranking should be the TRUE top-10 by cosine
    # Since queries are doc0, doc1, doc2 and they are in the corpus, they should
    # rank themselves at the top (cosine with self = 1.0).
    for i, query in enumerate(queries.queries):
        ref_docs = ref_ranking[query.id]
        # The query vector is the same as doc{i}, so doc{i} should be rank 1
        assert ref_docs[0] == f"doc{i}", f"Expected doc{i} at rank 1 for {query.id}"

    # Now verify that if we set approx_miss_fraction=0, recall = 1.0
    fake.approx_miss_fraction = 0.0
    measurements_exact = benchmark(
        plugin=plugin,
        client=fake,
        corpus=corpus,
        queries=queries,
        configs=[config],
        qrels=None,
        ks=(5, 10),
    )

    assert len(measurements_exact) == 1
    meas_exact = measurements_exact[0]
    recall_10_exact = meas_exact.quality.get(Metric.RECALL, 10)
    assert recall_10_exact is not None
    # With no miss fraction, recall should be 1.0 (or very close)
    assert recall_10_exact >= 0.99, f"Expected recall ~1.0, got {recall_10_exact}"

    print(f"✓ Recall methodology verified: approx={recall_10_approx:.2f}, exact={recall_10_exact:.2f}")


def test_cost_probe_scales_with_params():
    """CostProbe graph_memory_bytes should scale with num_vectors and m."""
    fake = FakeOSClient(version="2.17.1", plugins=["opensearch-knn"])

    # Small corpus
    docs = [Document(id=f"doc{i}", vector=[1.0, 2.0, 3.0, 4.0]) for i in range(10)]
    corpus_small = Corpus(documents=docs, dim=4)

    # Large corpus
    docs_large = [Document(id=f"doc{i}", vector=[1.0, 2.0, 3.0, 4.0]) for i in range(100)]
    corpus_large = Corpus(documents=docs_large, dim=4)

    plugin = DenseKnnPlugin()

    # Config with m=16
    config_m16 = Config.make(
        mode=Mode.DENSE_KNN,
        label="m16",
        params={"m": 16, "ef_construction": 100, "ef_search": 100, "encoder": "fp32", "k": 10},
    )

    # Config with m=32
    config_m32 = Config.make(
        mode=Mode.DENSE_KNN,
        label="m32",
        params={"m": 32, "ef_construction": 100, "ef_search": 100, "encoder": "fp32", "k": 10},
    )

    # Build and measure cost for small corpus, m=16
    builder = plugin.index_builder(fake)
    probe = plugin.cost_probe(fake)

    with builder.build(config_m16, corpus_small) as built_small_m16:
        cost_small_m16 = probe.measure(built_small_m16)

    with builder.build(config_m16, corpus_large) as built_large_m16:
        cost_large_m16 = probe.measure(built_large_m16)

    with builder.build(config_m32, corpus_small) as built_small_m32:
        cost_small_m32 = probe.measure(built_small_m32)

    # Assertions:
    # 1. Larger corpus -> larger graph memory
    assert cost_large_m16.graph_memory_bytes > cost_small_m16.graph_memory_bytes

    # 2. Larger m -> larger graph memory (for same corpus)
    assert cost_small_m32.graph_memory_bytes > cost_small_m16.graph_memory_bytes

    # 3. Check the formula: graph_memory ≈ 1.1 * (4*dim + 8*m) * num_vectors
    # For small corpus (10 docs), m=16, dim=4:
    # Expected: 1.1 * (4*4 + 8*16) * 10 = 1.1 * (16 + 128) * 10 = 1.1 * 144 * 10 = 1584
    expected_small_m16 = int(1.1 * (4 * 4 + 8 * 16) * 10)
    assert cost_small_m16.graph_memory_bytes == expected_small_m16

    # For small corpus (10 docs), m=32, dim=4:
    expected_small_m32 = int(1.1 * (4 * 4 + 8 * 32) * 10)
    assert cost_small_m32.graph_memory_bytes == expected_small_m32

    print(f"✓ CostProbe scales correctly: small_m16={cost_small_m16.graph_memory_bytes}, "
          f"large_m16={cost_large_m16.graph_memory_bytes}, small_m32={cost_small_m32.graph_memory_bytes}")


def test_index_teardown_on_exception():
    """Index should be deleted even if an exception occurs during the context."""
    fake = FakeOSClient(version="2.17.1", plugins=["opensearch-knn"])

    docs = [Document(id=f"doc{i}", vector=[1.0, 2.0, 3.0]) for i in range(5)]
    corpus = Corpus(documents=docs, dim=3)

    config = Config.make(
        mode=Mode.DENSE_KNN,
        label="teardown-test",
        params={"m": 16, "ef_construction": 100, "ef_search": 100, "encoder": "fp32", "k": 10},
    )

    plugin = DenseKnnPlugin()
    builder = plugin.index_builder(fake)

    # Record the index name so we can check it's deleted
    index_name = None

    try:
        with builder.build(config, corpus) as built:
            index_name = built.index_name
            # Verify index exists
            assert index_name in fake.indices
            # Raise an exception to test cleanup
            raise RuntimeError("Simulated error")
    except RuntimeError:
        pass

    # After exiting the context (even with exception), index should be gone
    assert index_name is not None
    assert index_name not in fake.indices

    print(f"✓ Index {index_name} was cleaned up after exception")


def test_index_teardown_on_success():
    """Index should be deleted after normal exit from context."""
    fake = FakeOSClient(version="2.17.1", plugins=["opensearch-knn"])

    docs = [Document(id=f"doc{i}", vector=[1.0, 2.0]) for i in range(3)]
    corpus = Corpus(documents=docs, dim=2)

    config = Config.make(
        mode=Mode.DENSE_KNN,
        label="success-test",
        params={"m": 16, "ef_construction": 100, "ef_search": 100, "encoder": "fp32", "k": 10},
    )

    plugin = DenseKnnPlugin()
    builder = plugin.index_builder(fake)

    with builder.build(config, corpus) as built:
        index_name = built.index_name
        assert index_name in fake.indices

    # After exiting, index should be gone
    assert index_name not in fake.indices

    print(f"✓ Index {index_name} was cleaned up after success")


def test_config_generator_respects_capabilities():
    """ConfigGenerator should only emit encoders present in Capabilities.quantization."""
    plugin = DenseKnnPlugin()
    gen = plugin.config_generator()

    # Capabilities with only FP32
    cap_fp32_only = Capabilities(
        version="2.17.1",
        dense_knn=True,
        quantization=("fp32",),
    )

    docs = [Document(id=f"doc{i}", vector=[1.0, 2.0]) for i in range(5)]
    corpus = Corpus(documents=docs, dim=2)

    configs_fp32 = gen.seed_configs(cap_fp32_only, corpus)

    # All configs should use FP32
    for cfg in configs_fp32:
        encoder = cfg.get("encoder", "fp32")
        assert encoder == "fp32", f"Expected only fp32, got {encoder}"

    # Capabilities with FP32 and FP16
    cap_with_fp16 = Capabilities(
        version="2.17.1",
        dense_knn=True,
        quantization=("fp32", "fp16"),
    )

    configs_with_fp16 = gen.seed_configs(cap_with_fp16, corpus)

    # Should have FP32 configs AND FP16 configs
    encoders = {cfg.get("encoder", "fp32") for cfg in configs_with_fp16}
    assert "fp32" in encoders
    assert "fp16" in encoders

    print(f"✓ ConfigGenerator respects quantization: fp32_only={len(configs_fp32)}, "
          f"with_fp16={len(configs_with_fp16)}, encoders={encoders}")


def test_config_generator_caps_count():
    """ConfigGenerator should cap the total number of configs (hard limit ~12)."""
    plugin = DenseKnnPlugin()
    gen = plugin.config_generator()

    # Capabilities with many quantization options
    cap_many = Capabilities(
        version="2.17.1",
        dense_knn=True,
        quantization=("fp32", "fp16", "int8", "pq", "binary"),
    )

    docs = [Document(id=f"doc{i}", vector=[1.0, 2.0]) for i in range(10)]
    corpus = Corpus(documents=docs, dim=2)

    configs = gen.seed_configs(cap_many, corpus)

    # Should be capped at ~12
    assert len(configs) <= 12, f"Expected <= 12 configs, got {len(configs)}"

    print(f"✓ ConfigGenerator caps count: {len(configs)} configs (limit 12)")


def test_config_generator_sweeps_ef_search_first():
    """ConfigGenerator should sweep ef_search at fixed m/ef_construction."""
    plugin = DenseKnnPlugin()
    gen = plugin.config_generator()

    cap = Capabilities(version="2.17.1", dense_knn=True, quantization=("fp32",))
    docs = [Document(id=f"doc{i}", vector=[1.0, 2.0]) for i in range(5)]
    corpus = Corpus(documents=docs, dim=2)

    configs = gen.seed_configs(cap, corpus)

    # Extract ef_search values for FP32 configs
    ef_searches = [cfg.get("ef_search") for cfg in configs if cfg.get("encoder") == "fp32"]

    # Should have multiple ef_search values (sweeping the dominant knob)
    assert len(set(ef_searches)) > 1, f"Expected multiple ef_search values, got {ef_searches}"

    # Should include [50, 100, 200, 400] or a subset
    expected_ef_searches = {50, 100, 200, 400}
    assert set(ef_searches) & expected_ef_searches, f"Expected some of {expected_ef_searches}, got {ef_searches}"

    print(f"✓ ConfigGenerator sweeps ef_search: {sorted(set(ef_searches))}")


if __name__ == "__main__":
    # Run tests manually (pytest discovery will also work)
    test_full_loop_recall_methodology()
    test_cost_probe_scales_with_params()
    test_index_teardown_on_exception()
    test_index_teardown_on_success()
    test_config_generator_respects_capabilities()
    test_config_generator_caps_count()
    test_config_generator_sweeps_ef_search_first()
    print("\n✅ All tests passed!")


# --- Regression: quantization multi-ef sweep + refine escalation (2026-08 review) ---

def _dense_cfg_labels(cap, corpus):
    from dense_knn import DenseConfigGenerator
    return [c.label for c in DenseConfigGenerator().seed_configs(cap, corpus)]


def test_quant_encoder_tested_at_multiple_ef_search():
    """fp16 must be swept at BOTH a low and high ef_search so the agent can tell
    quantization precision loss (recall flat across ef) from traversal loss —
    without hand-writing a follow-up sweep (the friction seen in review)."""
    from model import Capabilities
    from corpus import Corpus, Document
    cap = Capabilities(version="3.8.0", dense_knn=True, quantization=("fp32", "fp16"))
    corpus = Corpus(documents=[Document(id=f"d{i}", vector=[0.1, 0.2, 0.3, 0.4]) for i in range(5)], dim=4)
    fp16_efs = sorted(
        int(lbl.split("efs")[1]) for lbl in _dense_cfg_labels(cap, corpus) if lbl.startswith("fp16-")
    )
    assert len(fp16_efs) >= 2, f"fp16 must be tested at >=2 ef_search values, got {fp16_efs}"
    assert min(fp16_efs) < max(fp16_efs), "fp16 ef_search points must span low..high"


def test_refine_escalates_ef_search_when_floor_unmet():
    """When no config meets the recall floor, dense refine() proposes higher
    ef_search on the best config (one-shot); returns [] otherwise."""
    from dense_knn import DenseConfigGenerator
    from model import Config, Cost, Measurement, Metric, Mode, QualityScore

    def meas(label, ef, recall):
        q = QualityScore(by_metric_k={(Metric.RECALL, 10): recall})
        cfg = Config.make(Mode.DENSE_KNN, label, {"m": 16, "ef_construction": 100, "ef_search": ef, "encoder": "fp32"})
        return Measurement(config=cfg, quality=q, latency_p50_ms=1, latency_p95_ms=1, latency_p99_ms=1, cost=Cost())

    gen = DenseConfigGenerator()
    gen._refined = False
    # nothing meets floor 0.95 -> escalate
    unmet = [meas("fp32-m16-efc100-efs400", 400, 0.90)]
    follow = gen.refine(unmet, quality_floor=0.95, latency_budget_ms=None)
    assert follow, "expected ef_search escalation when floor unmet"
    assert all(dict(c.params)["ef_search"] > 400 for c in follow)
    assert gen.refine(unmet, 0.95, None) == []  # one-shot: stop on 2nd call

    # something already meets floor -> no refine
    gen2 = DenseConfigGenerator(); gen2._refined = False
    met = [meas("fp32-m16-efc100-efs100", 100, 0.99)]
    assert gen2.refine(met, quality_floor=0.95, latency_budget_ms=None) == []
