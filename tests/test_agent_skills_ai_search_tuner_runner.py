"""Tests for runner.py: percentiles, run_config, and benchmark harness."""

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
    Config,
    Cost,
    Measurement,
    Metric,
    Mode,
    QualityScore,
    QueryResult,
    RunResult,
)
from corpus import Corpus, Document, Query, QuerySet
from interfaces import (
    BuiltConfig,
    CostProbe,
    IndexBuilder,
    ModePlugin,
    QueryRunner,
    ReferenceProvider,
)
from runner import benchmark, percentiles, run_config


# --- Tests for percentiles ---


def test_percentiles_empty():
    """Empty list → (0, 0, 0)."""
    assert percentiles([]) == (0.0, 0.0, 0.0)


def test_percentiles_single():
    """Single element → (val, val, val)."""
    assert percentiles([42.5]) == (42.5, 42.5, 42.5)


def test_percentiles_known_list():
    """Known list [10, 20, 30, ..., 100] → hand-computed p50/p95/p99.

    Method: linear interpolation between closest ranks.
    N=10, values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    p50: rank = 0.50 * 9 = 4.5 → interpolate between values[4]=50 and values[5]=60
         → 50 + 0.5*(60-50) = 55.0
    p95: rank = 0.95 * 9 = 8.55 → interpolate between values[8]=90 and values[9]=100
         → 90 + 0.55*(100-90) = 95.5
    p99: rank = 0.99 * 9 = 8.91 → interpolate between values[8]=90 and values[9]=100
         → 90 + 0.91*(100-90) = 99.1
    """
    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50, p95, p99 = percentiles(latencies)
    assert p50 == 55.0
    assert abs(p95 - 95.5) < 1e-9  # floating point tolerance
    assert abs(p99 - 99.1) < 1e-9  # floating point tolerance


def test_percentiles_two_elements():
    """Two elements → linear interpolation for all percentiles."""
    latencies = [10.0, 20.0]
    p50, p95, p99 = percentiles(latencies)
    # p50: rank = 0.50 * 1 = 0.5 → 10 + 0.5*(20-10) = 15.0
    # p95: rank = 0.95 * 1 = 0.95 → 10 + 0.95*(20-10) = 19.5
    # p99: rank = 0.99 * 1 = 0.99 → 10 + 0.99*(20-10) = 19.9
    assert p50 == 15.0
    assert p95 == 19.5
    assert abs(p99 - 19.9) < 1e-9


# --- Tests for run_config ---


class FakeQueryRunner(QueryRunner):
    """Deterministic runner for testing: returns fixed latencies per query."""

    def __init__(self, latencies: dict[str, float]):
        self.latencies = latencies

    def run(self, built: BuiltConfig, queries: QuerySet) -> RunResult:
        per_query = [
            QueryResult(
                query_id=q.id,
                doc_ids=[f"doc{i}" for i in range(5)],
                scores=[1.0 - 0.1 * i for i in range(5)],
                took_ms=self.latencies.get(q.id, 10.0),
            )
            for q in queries
        ]
        return RunResult(config=built.config, per_query=per_query, build_ms=0.0)


def test_run_config_single_repeat():
    """Single repeat: latencies are as returned by runner."""
    config = Config.make(Mode.DENSE_KNN, "test", {})
    built = BuiltConfig(config, "test-index")
    queries = QuerySet([Query("q1", text="foo"), Query("q2", text="bar")])
    runner = FakeQueryRunner({"q1": 10.0, "q2": 20.0})

    result = run_config(built, queries, runner, repeats=1)

    assert len(result.per_query) == 2
    assert result.per_query[0].took_ms == 10.0
    assert result.per_query[1].took_ms == 20.0


def test_run_config_multiple_repeats_median():
    """Multiple repeats: latencies are the MEDIAN across repeats per query.

    Simulate 3 repeats for q1: [10, 15, 20] → median 15.
    """

    class MultiRepeatRunner(QueryRunner):
        def __init__(self):
            self.call_count = 0
            self.latencies_sequence = [
                {"q1": 10.0},  # first call
                {"q1": 15.0},  # second call
                {"q1": 20.0},  # third call
            ]

        def run(self, built, queries):
            lats = self.latencies_sequence[self.call_count % len(self.latencies_sequence)]
            self.call_count += 1
            per_query = [
                QueryResult(query_id=q.id, doc_ids=["doc1"], took_ms=lats.get(q.id, 5.0))
                for q in queries
            ]
            return RunResult(config=built.config, per_query=per_query)

    config = Config.make(Mode.DENSE_KNN, "test", {})
    built = BuiltConfig(config, "test-index")
    queries = QuerySet([Query("q1", text="foo")])
    runner = MultiRepeatRunner()

    result = run_config(built, queries, runner, repeats=3)

    # Median of [10, 15, 20] is 15.
    assert result.per_query[0].took_ms == 15.0


# --- Tests for benchmark (the core harness loop) ---


class FakeIndexBuilder(IndexBuilder):
    """Minimal builder that tracks lifecycle and can be told to fail."""

    def __init__(self, fail_on_label: str | None = None):
        self.built_labels = []
        self.torn_down_labels = []
        self.fail_on_label = fail_on_label

    @contextmanager
    def build(self, config: Config, corpus: Corpus):
        self.built_labels.append(config.label)
        if config.label == self.fail_on_label:
            try:
                raise RuntimeError(f"Simulated build failure for {config.label}")
            finally:
                # Teardown MUST happen even on failure.
                self.torn_down_labels.append(config.label)
        try:
            yield BuiltConfig(config, f"index-{config.label}")
        finally:
            self.torn_down_labels.append(config.label)


class FakeCostProbe(CostProbe):
    def measure(self, built: BuiltConfig) -> Cost:
        # Deterministic cost: try to extract number from label, otherwise use 1000.
        try:
            size = int(built.config.label.split("-")[-1]) * 1000
        except (ValueError, IndexError):
            size = 1000
        return Cost(graph_memory_bytes=size)


class FakeReferenceProvider(ReferenceProvider):
    def __init__(self):
        self.kind = "fake-exact"

    def reference_ranking(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        # Fake reference: always return doc0..doc{k-1}.
        return {q.id: [f"doc{i}" for i in range(k)] for q in queries}


class FakeModePlugin(ModePlugin):
    """Minimal plugin for testing the harness loop."""

    def __init__(self, builder: IndexBuilder | None = None):
        self.mode = Mode.DENSE_KNN
        self._builder = builder or FakeIndexBuilder()

    def is_available(self, cap):
        return True

    def index_builder(self, client):
        return self._builder

    def query_runner(self, client):
        return FakeQueryRunner({"q1": 10.0, "q2": 20.0})

    def cost_probe(self, client):
        return FakeCostProbe()

    def reference_provider(self, client, corpus, qrels):
        return FakeReferenceProvider()

    def config_generator(self):
        raise NotImplementedError


def _stub_score_run(run, mode, reference_ranking, qrels, ks):
    """Minimal quality scorer for tests: fixed recall."""
    quality = QualityScore(reference="test-stub")
    for k in ks:
        quality.by_metric_k[(Metric.RECALL, k)] = 0.95  # fixed for simplicity
    return quality


def test_benchmark_single_config_success(monkeypatch):
    """Single config succeeds; teardown is called."""
    # Monkeypatch quality module to inject our stub.
    import sys
    import types

    quality_module = types.ModuleType("quality")
    quality_module.score_run = _stub_score_run
    monkeypatch.setitem(sys.modules, "quality", quality_module)

    builder = FakeIndexBuilder()
    plugin = FakeModePlugin(builder=builder)
    corpus = Corpus([Document("doc0", text="foo"), Document("doc1", text="bar")])
    queries = QuerySet([Query("q1", text="foo")])
    configs = [Config.make(Mode.DENSE_KNN, "cfg-1000", {})]

    measurements = benchmark(plugin, None, corpus, queries, configs, ks=(10,))

    assert len(measurements) == 1
    assert measurements[0].config.label == "cfg-1000"
    assert measurements[0].quality.get(Metric.RECALL, 10) == 0.95
    assert measurements[0].latency_p50_ms == 10.0  # FakeQueryRunner returns 10.0 for q1
    assert builder.built_labels == ["cfg-1000"]
    assert builder.torn_down_labels == ["cfg-1000"]


def test_benchmark_one_config_fails_teardown_still_called(monkeypatch):
    """One config fails during build; teardown is still called, and other configs proceed."""
    # Monkeypatch quality module to inject our stub.
    import sys
    import types

    quality_module = types.ModuleType("quality")
    quality_module.score_run = _stub_score_run
    monkeypatch.setitem(sys.modules, "quality", quality_module)

    builder = FakeIndexBuilder(fail_on_label="cfg-fail")
    plugin = FakeModePlugin(builder=builder)
    corpus = Corpus([Document("doc0", text="foo")])
    queries = QuerySet([Query("q1", text="foo")])
    configs = [
        Config.make(Mode.DENSE_KNN, "cfg-ok", {}),
        Config.make(Mode.DENSE_KNN, "cfg-fail", {}),
        Config.make(Mode.DENSE_KNN, "cfg-ok2", {}),
    ]

    measurements = benchmark(plugin, None, corpus, queries, configs, ks=(5,))

    # cfg-fail should be skipped, only cfg-ok and cfg-ok2 in results.
    assert len(measurements) == 2
    assert {m.config.label for m in measurements} == {"cfg-ok", "cfg-ok2"}
    # Teardown called for all three configs (including the failed one).
    assert set(builder.torn_down_labels) == {"cfg-ok", "cfg-fail", "cfg-ok2"}


def test_benchmark_no_quality_py_available(monkeypatch):
    """If quality.py is unavailable, benchmark still runs but quality is empty."""
    # Remove quality from sys.modules so the import fails.
    import sys

    if "quality" in sys.modules:
        monkeypatch.delitem(sys.modules, "quality")

    # Make the import fail by temporarily adding a broken module.
    class BrokenQuality:
        def __getattr__(self, name):
            raise ImportError("quality module not found")

    monkeypatch.setitem(sys.modules, "quality", BrokenQuality())

    builder = FakeIndexBuilder()
    plugin = FakeModePlugin(builder=builder)
    corpus = Corpus([Document("doc0", text="foo")])
    queries = QuerySet([Query("q1", text="foo")])
    configs = [Config.make(Mode.DENSE_KNN, "cfg-1", {})]

    # The benchmark should not crash; it logs a warning and uses a stub score_run.
    measurements = benchmark(plugin, None, corpus, queries, configs, ks=(5,))

    # We expect 1 measurement, but quality will be empty/unavailable.
    assert len(measurements) == 1
    # The quality reference should indicate unavailability (overridden by ReferenceProvider).
    # Actually, the reference is set by the ReferenceProvider, not by score_run.
    # The quality.by_metric_k will be empty since we use the fallback stub.
    assert measurements[0].quality.get(Metric.RECALL, 5) is None or measurements[0].quality.reference == "unavailable"
