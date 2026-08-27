"""Shared data model for ai-search-tuner.

This module is the *contract* every mode and harness component depends on. It is
intentionally dependency-free (stdlib only) so it can be imported anywhere
without pulling in opensearch-py or numpy.

Vocabulary
----------
- **Mode**: a retrieval family — dense k-NN, traditional neural sparse
  (rank_features, exact), sparse ANN (sparse_vector/SEISMIC, approximate), or
  hybrid.
- **Config**: one concrete parameter assignment within a mode (e.g. HNSW
  m=16, ef_search=100, FP16).
- **RunResult**: what a QueryRunner returns for one config over the query set —
  ranked doc ids per query plus timings.
- **Measurement**: the fully-scored result for one config — quality@k + latency
  + footprint — ready for Pareto ranking.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class Mode(str, enum.Enum):
    """The four retrieval families the tuner can benchmark."""

    DENSE_KNN = "dense_knn"
    SPARSE_RANK_FEATURES = "sparse_rank_features"  # exact Lucene scoring
    SPARSE_ANN = "sparse_ann"  # SEISMIC, approximate (3.3+)
    HYBRID = "hybrid"

    @property
    def is_approximate(self) -> bool:
        """True when the mode is an approximation of an exact search.

        Recall@k is only meaningful for approximate modes. Traditional neural
        sparse (rank_features) is EXACT Lucene scoring, so recall vs itself is
        trivially 1.0 — it must be graded on relevance (NDCG/MAP) or on
        result-overlap-vs-unpruned instead. This property is the single source
        of truth for that distinction across the codebase.
        """
        return self in (Mode.DENSE_KNN, Mode.SPARSE_ANN)


class Metric(str, enum.Enum):
    """Quality metrics. RECALL is fidelity-vs-exact; NDCG/MAP are relevance."""

    RECALL = "recall"
    NDCG = "ndcg"
    MAP = "map"


@dataclass(frozen=True)
class Capabilities:
    """What the target cluster actually supports, from probe.py.

    Modes whose prerequisites are absent are cleanly skipped, never failed.
    """

    version: str  # e.g. "2.17.1"
    dense_knn: bool = False
    sparse_rank_features: bool = False
    sparse_ann: bool = False  # requires neural-search + SEISMIC (3.3+)
    hybrid: bool = False
    knn_engines: tuple[str, ...] = ()  # e.g. ("lucene", "faiss", "nmslib")
    quantization: tuple[str, ...] = ()  # detected, never assumed
    sparse_models: tuple[str, ...] = ()  # ml-commons model ids available
    notes: tuple[str, ...] = ()

    def supports(self, mode: Mode) -> bool:
        return {
            Mode.DENSE_KNN: self.dense_knn,
            Mode.SPARSE_RANK_FEATURES: self.sparse_rank_features,
            Mode.SPARSE_ANN: self.sparse_ann,
            Mode.HYBRID: self.hybrid,
        }[mode]


@dataclass(frozen=True)
class Config:
    """One concrete parameter assignment within a mode.

    `params` holds the mode-specific knobs (HNSW m/ef, prune_ratio, weights…).
    `label` is a short human-readable id used in reports and logs. Configs are
    frozen and hashable so they can key caches and dedupe sweeps.
    """

    mode: Mode
    label: str
    params: tuple[tuple[str, Any], ...]  # sorted (key, value) pairs — hashable

    @staticmethod
    def make(mode: Mode, label: str, params: dict[str, Any]) -> "Config":
        norm = tuple(sorted((k, _freeze(v)) for k, v in params.items()))
        return Config(mode=mode, label=label, params=norm)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.params}

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.params:
            if k == key:
                return v
        return default


def _freeze(v: Any) -> Any:
    """Make nested dicts/lists hashable for frozen Config storage."""
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    return v


@dataclass
class QueryResult:
    """Ranked doc ids for a single query, best-first, plus optional scores."""

    query_id: str
    doc_ids: list[str]
    scores: list[float] = field(default_factory=list)
    took_ms: float = 0.0


@dataclass
class RunResult:
    """Everything a QueryRunner returns for one config over the full query set."""

    config: Config
    per_query: list[QueryResult]
    build_ms: float = 0.0  # index/pipeline build time (approximate/informational)

    @property
    def latency_ms(self) -> list[float]:
        return [q.took_ms for q in self.per_query]


@dataclass
class Cost:
    """The cost axis for one config. Which fields are populated is mode-specific.

    dense  -> graph_memory_bytes
    sparse -> index_size_bytes
    hybrid -> (latency captured in RunResult; may set index_size_bytes for the
              union of sub-indices)
    """

    index_size_bytes: int | None = None
    graph_memory_bytes: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def primary_bytes(self) -> int | None:
        """The single 'footprint' number used on the Pareto axis, if any."""
        if self.graph_memory_bytes is not None:
            return self.graph_memory_bytes
        return self.index_size_bytes


@dataclass
class QualityScore:
    """Quality@k for one config against its per-mode reference.

    `by_metric_k` maps (metric, k) -> value, e.g. (RECALL, 10) -> 0.94.
    `reference` records what the ground truth was (for report honesty).
    """

    by_metric_k: dict[tuple[Metric, int], float] = field(default_factory=dict)
    reference: str = ""  # e.g. "fp32-brute-force", "qrels", "unpruned-baseline"

    def get(self, metric: Metric, k: int) -> float | None:
        return self.by_metric_k.get((metric, k))


@dataclass
class Measurement:
    """A fully-scored config: quality + latency percentiles + cost.

    This is the unit Pareto ranking consumes and the report renders.
    """

    config: Config
    quality: QualityScore
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    cost: Cost
    flags: list[str] = field(default_factory=list)  # e.g. "silent-recall-drop"

    def primary_quality(self, metric: Metric, k: int) -> float | None:
        return self.quality.get(metric, k)
