"""Benchmark runner — the core harness loop, mode-agnostic.

This module executes the config sweep for any mode plugin: builds each config
(via IndexBuilder context manager), runs the query set (via QueryRunner),
measures cost (via CostProbe), and scores quality (via quality.score_run). It
is robust to per-config failures and guarantees teardown even on error.

Key functions
-------------
- percentiles: compute p50/p95/p99 from latencies (linear-interpolation
  nearest-rank, documented below).
- run_config: execute query set (with optional repeats for latency stability),
  return RunResult with MEDIAN across repeats per query.
- benchmark: the main harness loop, mode-agnostic, produces Measurements.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING

from model import (
    Config,
    Cost,
    Measurement,
    Metric,
    QualityScore,
    QueryResult,
    RunResult,
)
from corpus import QuerySet

if TYPE_CHECKING:
    from interfaces import BuiltConfig, ModePlugin, QueryRunner
    from corpus import Corpus, Qrels

logger = logging.getLogger(__name__)


def percentiles(latencies_ms: list[float]) -> tuple[float, float, float]:
    """Compute (p50, p95, p99) from latencies using linear-interpolation nearest-rank.

    Method
    ------
    For a sorted list of N values, the p-th percentile (p in [0,1]) is computed as:
        rank = p * (N - 1)
        i = floor(rank)
        fraction = rank - i
        result = values[i] + fraction * (values[i+1] - values[i])   if i < N-1
                 values[i]                                           if i == N-1

    This is the "linear interpolation between closest ranks" method (R-7 in R,
    numpy "linear" mode) — it matches typical benchmarking practice and is
    smooth with respect to sample size.

    Edge cases
    ----------
    - Empty list → (0.0, 0.0, 0.0)
    - Single element → (val, val, val)
    - Two elements → linear interpolation for all three percentiles
    """
    if not latencies_ms:
        return (0.0, 0.0, 0.0)
    if len(latencies_ms) == 1:
        val = latencies_ms[0]
        return (val, val, val)

    sorted_lat = sorted(latencies_ms)
    n = len(sorted_lat)

    def _percentile(p: float) -> float:
        rank = p * (n - 1)
        i = int(rank)
        fraction = rank - i
        if i >= n - 1:
            return sorted_lat[-1]
        return sorted_lat[i] + fraction * (sorted_lat[i + 1] - sorted_lat[i])

    return (_percentile(0.50), _percentile(0.95), _percentile(0.99))


def run_config(
    built: BuiltConfig,
    queries: QuerySet,
    runner: QueryRunner,
    repeats: int = 1,
) -> RunResult:
    """Execute the query set against a built config, optionally repeated.

    When repeats > 1, each query is run multiple times for latency stability,
    and the returned RunResult's per_query timings are the MEDIAN across
    repeats for that query. Using the median (rather than mean or min) filters
    out transient outliers while staying representative of typical performance —
    important for Pareto ranking where we don't want a single lucky run to
    dominate the recommendation.

    Parameters
    ----------
    built : BuiltConfig
        A live, benchmarkable index/pipeline.
    queries : QuerySet
        The query set to execute.
    runner : QueryRunner
        Mode-specific query executor.
    repeats : int, default 1
        Number of times to run each query for latency stability.

    Returns
    -------
    RunResult
        One QueryResult per query with the median took_ms across repeats.
        `build_ms` is informational (copied from built if available).
    """
    if repeats < 1:
        repeats = 1

    if repeats == 1:
        # Fast path: no repetition needed.
        return runner.run(built, queries)

    # Multi-repeat path: run each query `repeats` times, take median latency.
    query_results: dict[str, QueryResult] = {}
    timings_per_query: dict[str, list[float]] = {q.id: [] for q in queries}

    for _rep in range(repeats):
        batch_result = runner.run(built, queries)
        for qr in batch_result.per_query:
            if qr.query_id not in query_results:
                # First time we see this query — store doc_ids, scores.
                query_results[qr.query_id] = QueryResult(
                    query_id=qr.query_id,
                    doc_ids=qr.doc_ids,
                    scores=qr.scores,
                    took_ms=qr.took_ms,
                )
            timings_per_query[qr.query_id].append(qr.took_ms)

    # Compute median latency per query.
    for qid, qr in query_results.items():
        times = timings_per_query[qid]
        if times:
            qr.took_ms = _median(times)

    # Return per_query in the INPUT query order, not dict-insertion order, so the
    # result order is stable regardless of how runner.run() ordered its response.
    ordered = [query_results[q.id] for q in queries if q.id in query_results]
    return RunResult(
        config=built.config,
        per_query=ordered,
        build_ms=getattr(built, "build_ms", 0.0),
    )


def _median(values: list[float]) -> float:
    """Simple median: middle element if odd length, average of two middle if even."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def benchmark(
    plugin: ModePlugin,
    client,
    corpus: Corpus,
    queries: QuerySet,
    configs: list[Config],
    qrels: Qrels | None = None,
    ks: tuple[int, ...] = (5, 10, 100),
    quality_floor: float | None = None,
    latency_budget_ms: float | None = None,
) -> list[Measurement]:
    """The core harness loop, mode-agnostic.

    For each config:
        1. Build the index/pipeline via IndexBuilder.build (context manager).
        2. Run the query set and measure latencies.
        3. Score quality via quality.score_run (against per-mode reference).
        4. Measure cost via CostProbe.
        5. Assemble Measurement with latency percentiles.

    The reference ranking is computed ONCE (via ReferenceProvider) and reused
    across all configs. Per-config failures are logged and skipped (no
    Measurement is appended, so the config is absent from results); teardown
    MUST still happen (the IndexBuilder.build context manager guarantees this).

    Parameters
    ----------
    plugin : ModePlugin
        The mode being benchmarked (dense/sparse/hybrid).
    client
        OpenSearch client or FakeOSClient.
    corpus : Corpus
        Document corpus (sampled).
    queries : QuerySet
        Query set to run.
    configs : list[Config]
        Configs to sweep.
    qrels : Qrels | None
        Optional relevance judgments for NDCG/MAP.
    ks : tuple[int, ...], default (5, 10, 100)
        k values for quality@k metrics.
    quality_floor : float | None
        Optional quality threshold (not enforced here; used by pareto.py).
    latency_budget_ms : float | None
        Optional latency budget (not enforced here; used by pareto.py).

    Returns
    -------
    list[Measurement]
        One Measurement per successfully-benchmarked config. Configs that
        failed during build/run/score are skipped (logged but not fatal).
    """
    # Import quality.score_run lazily so tests can monkeypatch it.
    try:
        from quality import score_run
    except ImportError:
        logger.warning("quality.score_run not available; quality scores will be empty")

        def score_run(run, mode, reference_ranking, qrels, ks):
            return QualityScore(reference="unavailable")

    index_builder = plugin.index_builder(client)
    query_runner = plugin.query_runner(client)
    cost_probe = plugin.cost_probe(client)
    reference_provider = plugin.reference_provider(client, corpus, qrels)

    # Compute reference ranking ONCE (reused across configs). Wrap the whole
    # scored loop in try/finally so any temp index the reference provider built
    # is torn down even on error (DESIGN §4.3). close() is optional on the
    # ReferenceProvider contract — call it only when present.
    logger.info(
        f"Computing {plugin.mode.value} reference ranking via {reference_provider.kind}..."
    )
    max_k = max(ks) if ks else 100
    measurements: list[Measurement] = []
    try:
        reference_ranking = reference_provider.reference_ranking(queries, k=max_k)

        for config in configs:
            logger.info(f"Benchmarking {config.label} ({config.mode.value})...")
            try:
                # Build the config (context manager guarantees teardown).
                with index_builder.build(config, corpus) as built:
                    # Run the query set.
                    run_result = run_config(built, queries, query_runner, repeats=1)

                    # Score quality against reference.
                    quality = score_run(
                        run=run_result,
                        mode=plugin.mode,
                        reference_ranking=reference_ranking,
                        qrels=qrels,
                        ks=ks,
                    )
                    # Prefer the provider's SPECIFIC reference identity
                    # (e.g. "fp32-brute-force", "unpruned-baseline") over the
                    # generic label score_run assigns, but preserve the qrels
                    # suffix. Idempotent if the provider already encodes qrels.
                    base = reference_provider.kind or quality.reference
                    if qrels and "qrels" not in base:
                        base = f"{base}+qrels" if base else "qrels"
                    quality.reference = base

                    # Measure cost.
                    cost = cost_probe.measure(built)

                    # Compute latency percentiles.
                    latencies = run_result.latency_ms
                    p50, p95, p99 = percentiles(latencies)

                    measurement = Measurement(
                        config=config,
                        quality=quality,
                        latency_p50_ms=p50,
                        latency_p95_ms=p95,
                        latency_p99_ms=p99,
                        cost=cost,
                        flags=[],
                    )
                    measurements.append(measurement)

            except Exception as e:
                logger.error(
                    f"Config {config.label} failed during build/run/score: {e}",
                    exc_info=True,
                )
                # Skip this config — do NOT append a Measurement.
                # The IndexBuilder context manager ensures teardown happened.
                continue
    finally:
        # Always tear down the reference provider's temp index, if it has one.
        close = getattr(reference_provider, "close", None)
        if callable(close):
            close()

    logger.info(
        f"Benchmark complete: {len(measurements)} of {len(configs)} configs succeeded."
    )
    return measurements
