"""Mode interface contracts — the three (plus one) seams every mode implements.

The harness is mode-agnostic. Each retrieval mode provides:

- **IndexBuilder**  : create a temporary index/pipeline for a config on a sample,
                      and tear it down (context-manager style via `build`).
- **QueryRunner**   : run the query set against a built config, return RunResult.
- **CostProbe**     : measure the mode's cost axis (graph memory / index size…).
- **ReferenceProvider** : supply the per-mode ground truth for quality scoring
                      (dense -> brute-force exact; sparse rank_features ->
                      un-pruned baseline / qrels; sparse ANN -> exact sparse;
                      hybrid -> best standalone).

Keeping these abstract is what lets dense, sparse, and hybrid be implemented in
parallel and dropped in without touching the harness. A mode bundles all four
into a `ModePlugin`.
"""

from __future__ import annotations

import abc
from contextlib import AbstractContextManager
from typing import Iterable

from model import Capabilities, Config, Cost, Mode, QueryResult, RunResult
from corpus import Corpus, QuerySet, Qrels


class BuiltConfig:
    """Handle to a live, benchmarkable index/pipeline for one Config.

    Concrete modes subclass or wrap this; the harness only needs `index_name`
    (or pipeline id) to route queries. Returned by IndexBuilder.build() as a
    context manager so teardown is guaranteed even on error.
    """

    def __init__(self, config: Config, index_name: str, extra: dict | None = None):
        self.config = config
        self.index_name = index_name
        self.extra = extra or {}


class IndexBuilder(abc.ABC):
    """Builds (and cleans up) a temporary index/pipeline for a config."""

    @abc.abstractmethod
    def build(self, config: Config, corpus: Corpus) -> AbstractContextManager[BuiltConfig]:
        """Return a context manager yielding a BuiltConfig.

        MUST create only *temporary* indices on the provided (sampled) corpus,
        and MUST tear them down on exit even if an exception is raised.
        """
        raise NotImplementedError


class QueryRunner(abc.ABC):
    """Executes the query set against a built config."""

    @abc.abstractmethod
    def run(self, built: BuiltConfig, queries: QuerySet) -> RunResult:
        """Run every query, capturing ranked doc ids and per-query took_ms."""
        raise NotImplementedError


class CostProbe(abc.ABC):
    """Measures the cost axis for a built config."""

    @abc.abstractmethod
    def measure(self, built: BuiltConfig) -> Cost:
        raise NotImplementedError


class ReferenceProvider(abc.ABC):
    """Supplies the per-mode ground truth used to score quality.

    `reference_ranking` returns, per query, the ordered list of 'correct' doc
    ids to compare a run against. For RECALL this is the exact top-k; for
    relevance metrics the ReferenceProvider may instead expose qrels and the
    scorer computes NDCG/MAP. `kind` labels the reference for report honesty.
    """

    kind: str  # e.g. "fp32-brute-force", "exact-sparse", "unpruned-baseline", "qrels"

    @abc.abstractmethod
    def reference_ranking(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        """query_id -> ordered 'ground truth' doc ids (len >= k where possible)."""
        raise NotImplementedError


class ConfigGenerator(abc.ABC):
    """Proposes the config space for a mode and prunes it agentically.

    `seed_configs` yields the initial sweep (dominant knob first). `refine`
    receives measurements so far and returns the next configs to try, or an
    empty list to stop (early-stop on threshold breach). This is where the
    §7 agentic pruning lives per mode.
    """

    mode: Mode

    @abc.abstractmethod
    def seed_configs(self, cap: Capabilities, corpus: Corpus) -> list[Config]:
        raise NotImplementedError

    @abc.abstractmethod
    def refine(self, measured, quality_floor: float, latency_budget_ms: float | None) -> list[Config]:
        """Return follow-up configs given results so far; [] to stop."""
        raise NotImplementedError


class ModePlugin(abc.ABC):
    """Bundles the seams for one mode. The harness drives ModePlugins uniformly."""

    mode: Mode

    @abc.abstractmethod
    def is_available(self, cap: Capabilities) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def index_builder(self, client) -> IndexBuilder:
        raise NotImplementedError

    @abc.abstractmethod
    def query_runner(self, client) -> QueryRunner:
        raise NotImplementedError

    @abc.abstractmethod
    def cost_probe(self, client) -> CostProbe:
        raise NotImplementedError

    @abc.abstractmethod
    def reference_provider(self, client, corpus: Corpus, qrels: Qrels | None) -> ReferenceProvider:
        raise NotImplementedError

    @abc.abstractmethod
    def config_generator(self) -> ConfigGenerator:
        raise NotImplementedError
