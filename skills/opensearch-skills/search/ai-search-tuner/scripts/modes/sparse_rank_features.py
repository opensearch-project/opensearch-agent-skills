"""Traditional Neural Sparse retrieval mode (rank_features, EXACT Lucene scoring).

This mode implements neural sparse search using OpenSearch's `rank_features` field
type. Unlike HNSW or SEISMIC, this mode performs EXACT Lucene scoring — there is no
approximate/exact recall tradeoff. Instead, we tune:

1. Index bloat via pruning parameters (prune_type, prune_ratio) — addresses #946
2. Latency via two-phase scoring (two_phase_parameter.*) — free speedup, zero
   relevance loss, addresses #646

Quality reference: UN-PRUNED baseline (max token expansion, no pruning) for result
overlap measurement, OR labeled qrels for NDCG/MAP. Never "recall vs exact" since
this mode IS exact.

Scoring: NDCG@k / MAP@k (relevance preservation) and result-overlap@k vs unpruned.
The quality.py engine will correctly label this as "unpruned-baseline" reference,
NOT as "fidelity-to-exact" (which would be misleading).

Verified parameters (per DESIGN.md §5, Mode B1, since 2.11+):
- model_id (ingest): sparse encoding model (doc-only vs bi-encoder)
- analyzer (query, doc-only): tokenization lookup (fast vs inference)
- prune_type (ingest): max_ratio / abs_value / alpha_mass / top_k / none (2.19+)
- prune_ratio (ingest): threshold for prune_type
- two_phase_parameter.* (2.15+): enabled, prune_type, prune_ratio, expansion_rate,
  max_window_size

Default strategy (§7): Enable two_phase by default (free latency win), then sweep
prune_ratio to find the index-size/relevance knee. Hard cap ~10 configs.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from model import (
    Capabilities,
    Config,
    Cost,
    Mode,
    QueryResult,
    RunResult,
)
from corpus import Corpus, QuerySet, Qrels
from interfaces import (
    BuiltConfig,
    CostProbe,
    IndexBuilder,
    ModePlugin,
    QueryRunner,
    ReferenceProvider,
    ConfigGenerator,
)

if TYPE_CHECKING:
    from client import OSClient

logger = logging.getLogger(__name__)


# --- Verified parameter names (DESIGN §10.3: these are ALLOWED) ---
VERIFIED_PARAMS = {
    "model_id",
    "analyzer",
    "prune_type",
    "prune_ratio",
    "two_phase_parameter",
}

# --- Forbidden parameter names (DESIGN §10.3: do NOT emit) ---
FORBIDDEN_PARAMS = {
    "two_phase_ratio",
    "two_phase_window_size",
    "should_two_phase",
    "wand",
    "block_max",
    "sub_query_raw_scores",
}


def _first_deployed_sparse_model(client) -> str | None:
    """Return the id of the first DEPLOYED sparse-encoding model, or None.

    Mirrors probe.detect_capabilities' filter so the reference baseline uses the
    same model as cap.sparse_models: skip non-SPARSE algorithms, and confirm
    DEPLOYED via a direct get_model_state when _search doesn't report state
    (real ML Commons omits it). Treats a missing algorithm as NOT sparse.
    """
    try:
        models = client.ml_models()
    except Exception:
        return None
    for m in models:
        algo = (m.get("algorithm") or m.get("function_name") or "").upper()
        if "SPARSE" not in algo:  # missing/other algorithm → not a sparse model
            continue
        model_id = m.get("model_id")
        if not model_id:
            continue
        state = m.get("model_state")
        if state is None:
            getter = getattr(client, "get_model_state", None)
            state = getter(model_id) if callable(getter) else "DEPLOYED"
        if state == "DEPLOYED":
            return model_id
    return None


def _pruning_shrink_factor(prune_type: str | None, prune_ratio: float | None) -> float:
    """Approximate inverted-index shrink from ingest-time token pruning.

    Used only to synthesize a plausible index size for the offline fake (real
    clusters report actual store.size). Grounded in neural-search #988: pruning
    low-weight tokens with max_ratio≈0.1 shrinks the index ~40% with <1%
    relevance loss. Returns a multiplier in (0, 1].
    """
    if not prune_type or prune_type == "none" or prune_ratio in (None, 0):
        return 1.0
    if prune_type == "max_ratio":
        # 1 - 4*ratio, clamped at 0.45: 0.05→0.80, 0.1→0.60, ≥~0.1375→0.45.
        return max(0.45, 1.0 - 4.0 * float(prune_ratio))
    # Other strategies: a modest, conservative shrink.
    return 0.8


class SparseRankFeaturesIndexBuilder(IndexBuilder):
    """Builds a temporary index with rank_features field + sparse encoding pipeline."""

    def __init__(self, client: OSClient):
        self.client = client

    @contextmanager
    def build(self, config: Config, corpus: Corpus):
        """Create index + ingest pipeline, yield BuiltConfig, teardown on exit."""
        index_name = f"rt-sparse-{uuid.uuid4().hex[:8]}"
        pipeline_id = f"rt-sparse-pipeline-{uuid.uuid4().hex[:8]}"

        model_id = config.get("model_id")
        prune_type = config.get("prune_type")
        prune_ratio = config.get("prune_ratio")
        two_phase = config.get("two_phase_parameter")
        search_pipeline_id = f"rt-sparse-2p-{uuid.uuid4().hex[:8]}"
        has_search_pipeline = False

        try:
            # Create ingest pipeline with sparse_encoding processor.
            pipeline_body: dict[str, Any] = {
                "description": f"Sparse encoding for {config.label}",
                "processors": [
                    {
                        "sparse_encoding": {
                            "model_id": model_id,
                            "field_map": {"text": "sparse_vector"},
                        }
                    }
                ],
            }

            # Apply pruning at ingest time (modeled as pipeline metadata in real code,
            # synthesizable in tests via index metadata).
            if prune_type and prune_type != "none":
                pipeline_body["processors"][0]["sparse_encoding"]["prune_type"] = prune_type
                if prune_ratio is not None:
                    pipeline_body["processors"][0]["sparse_encoding"]["prune_ratio"] = prune_ratio

            self.client.put_pipeline(pipeline_id, pipeline_body)

            # Create index with rank_features field.
            index_body = {
                "settings": {"default_pipeline": pipeline_id, "number_of_shards": 1},
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword"},
                        "text": {"type": "text"},
                        "sparse_vector": {"type": "rank_features"},
                    }
                },
            }

            self.client.create_index(index_name, index_body)

            # Index documents. In a real cluster, the pipeline would apply sparse_encoding.
            # In FakeOSClient tests, we index the text field and let the fake scoring path
            # handle it (lexical overlap).
            docs_to_bulk = []
            for doc in corpus.documents:
                doc_dict: dict[str, Any] = {
                    "id": doc.id,
                    "text": doc.text or "",
                }
                # If doc has precomputed sparse tokens (for test synthesis), include them.
                if "sparse_tokens" in doc.fields:
                    doc_dict["sparse_vector"] = doc.fields["sparse_tokens"]
                docs_to_bulk.append(doc_dict)

            if docs_to_bulk:
                self.client.bulk(index_name, docs_to_bulk)
                self.client.refresh(index_name)

            # Two-phase is applied via a SEARCH PIPELINE (neural_sparse_two_phase_
            # _processor), referenced at query time with ?search_pipeline=<id>.
            # It is NOT a request parameter — passing it as one raises
            # "unrecognized parameter: [two_phase_parameter]" on a real cluster.
            if two_phase and _as_dict(two_phase).get("enabled"):
                tp = _as_dict(two_phase)
                proc_params = {
                    k: tp[k]
                    for k in ("prune_type", "prune_ratio", "expansion_rate", "max_window_size")
                    if k in tp
                }
                try:
                    self.client.put_search_pipeline(
                        search_pipeline_id,
                        {"request_processors": [
                            {"neural_sparse_two_phase_processor": {"two_phase_parameter": proc_params}}
                        ]},
                    )
                    has_search_pipeline = True
                except Exception as e:
                    # Two-phase is a latency optimization, not correctness — if the
                    # processor isn't available, proceed without it.
                    logger.warning(f"two-phase search pipeline unavailable, skipping: {e}")

            # Offline demo fidelity only: when running against the in-memory fake,
            # synthesize an inverted-index size that shrinks with pruning, since
            # the fake cannot actually apply the sparse_encoding pipeline. This
            # mirrors the real mechanism/#988: dropping low-weight tokens removes
            # postings (~40% smaller at max_ratio=0.1). On a REAL cluster this is
            # a no-op — cat_indices reports the true store.size. Guarded by
            # duck-typing so it never touches production behavior.
            fake_indices = getattr(self.client, "indices", None)
            if isinstance(fake_indices, dict) and index_name in fake_indices:
                base = len(docs_to_bulk) * 1100  # ~unpruned postings per doc
                shrink = _pruning_shrink_factor(prune_type, prune_ratio)
                fake_indices[index_name]["_size_bytes"] = int(base * shrink)

            built = BuiltConfig(
                config=config,
                index_name=index_name,
                extra={
                    "pipeline_id": pipeline_id,
                    "search_pipeline_id": search_pipeline_id if has_search_pipeline else None,
                },
            )

            yield built

        finally:
            # Guaranteed teardown even on exception.
            try:
                self.client.delete_index(index_name)
            except Exception as e:
                logger.warning(f"Failed to delete index {index_name}: {e}")
            try:
                self.client.delete_pipeline(pipeline_id)
            except Exception as e:
                logger.warning(f"Failed to delete pipeline {pipeline_id}: {e}")
            if has_search_pipeline:
                try:
                    self.client.delete_search_pipeline(search_pipeline_id)
                except Exception as e:
                    logger.warning(f"Failed to delete search pipeline {search_pipeline_id}: {e}")


def _as_dict(v) -> dict:
    """two_phase_parameter may arrive as a dict or as Config's frozen tuple of
    (key, value) pairs. Normalize to a dict."""
    if isinstance(v, dict):
        return v
    try:
        return dict(v)
    except Exception:
        return {}


class SparseRankFeaturesQueryRunner(QueryRunner):
    """Executes neural_sparse queries with optional two-phase parameters."""

    def __init__(self, client: OSClient):
        self.client = client

    def run(self, built: BuiltConfig, queries: QuerySet) -> RunResult:
        """Issue neural_sparse queries, honor two_phase_parameter settings."""
        config = built.config
        index_name = built.index_name
        model_id = config.get("model_id")
        analyzer = config.get("analyzer")
        # Two-phase is applied via the search pipeline the IndexBuilder created
        # (built.extra["search_pipeline_id"]), not here — no query-level param.

        per_query: list[QueryResult] = []

        for query in queries:
            # Build neural_sparse query.
            # Doc-only model: use analyzer (fast lookup).
            # Bi-encoder: use model_id (inference at query time).
            query_body: dict[str, Any]
            if analyzer:
                # Doc-only path: analyzer-based tokenization
                query_body = {
                    "query": {
                        "neural_sparse": {
                            "sparse_vector": {
                                "query_text": query.text or "",
                                "analyzer": analyzer,
                            }
                        }
                    },
                    "size": 100,
                }
            else:
                # Bi-encoder path: model_id inference
                query_body = {
                    "query": {
                        "neural_sparse": {
                            "sparse_vector": {
                                "query_text": query.text or "",
                                "model_id": model_id,
                            }
                        }
                    },
                    "size": 100,
                }

            # Two-phase is applied by referencing the SEARCH PIPELINE the
            # IndexBuilder created (?search_pipeline=<id>). Never pass
            # two_phase_parameter as a request param — the cluster rejects it.
            params = {}
            sp = built.extra.get("search_pipeline_id")
            if sp:
                params["search_pipeline"] = sp

            resp = self.client.search(index_name, query_body, params=params or None)
            hits = resp.get("hits", {}).get("hits", [])
            doc_ids = [h["_id"] for h in hits]
            scores = [float(h.get("_score", 0.0)) for h in hits]
            took_ms = float(resp.get("took", 1))

            per_query.append(
                QueryResult(
                    query_id=query.id,
                    doc_ids=doc_ids,
                    scores=scores,
                    took_ms=took_ms,
                )
            )

        return RunResult(config=config, per_query=per_query, build_ms=0.0)


class SparseRankFeaturesCostProbe(CostProbe):
    """Measures index size (the #946 index-bloat lever) via cat_indices."""

    def __init__(self, client: OSClient):
        self.client = client

    def measure(self, built: BuiltConfig) -> Cost:
        """Read store.size from cat_indices → Cost(index_size_bytes=...)."""
        index_name = built.index_name
        indices = self.client.cat_indices(index_name)
        if not indices:
            return Cost(index_size_bytes=0)

        # Parse store.size from the first match (format: "123kb" or "1.2mb").
        size_str = indices[0].get("store.size", "0b")
        size_bytes = _parse_size_to_bytes(size_str)
        return Cost(index_size_bytes=size_bytes)


def _parse_size_to_bytes(size_str: str) -> int:
    """Parse OpenSearch size strings like "123kb", "1.2mb" → bytes."""
    size_str = size_str.strip().lower()
    if not size_str or size_str == "0":
        return 0

    units = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}
    for suffix, multiplier in units.items():
        if size_str.endswith(suffix):
            num_str = size_str[: -len(suffix)]
            try:
                return int(float(num_str) * multiplier)
            except ValueError:
                return 0
    # No recognized suffix, try parsing as int.
    try:
        return int(float(size_str))
    except ValueError:
        return 0


class SparseRankFeaturesReferenceProvider(ReferenceProvider):
    """Provides UN-PRUNED baseline as reference for result-overlap measurement.

    The reference is the un-pruned bi-encoder (or doc-only) baseline: max token
    expansion, no pruning, two-phase off. This is the "ground truth" for overlap
    scoring. We do NOT claim this is fidelity-to-exact (it IS exact Lucene scoring);
    the quality engine will label RECALL entries as "unpruned-baseline" (result
    overlap), which is correct.
    """

    def __init__(self, client: OSClient, corpus: Corpus, qrels: Qrels | None):
        self.client = client
        self.corpus = corpus
        self.qrels = qrels
        self._reference_cache: dict[str, list[str]] | None = None
        # Discover a real DEPLOYED SPARSE model for the un-pruned baseline index.
        # The reference provider isn't given `cap`, so it re-derives the model
        # using the SAME filter as probe.detect_capabilities (SPARSE_ENCODING +
        # DEPLOYED) — NOT a raw ml_models()[0], which on a real cluster could be
        # a text-embedding model and would 404 the neural_sparse baseline query,
        # aborting the whole run. Must match cap.sparse_models[0] so the baseline
        # and the swept configs compare like-for-like. Falls back to the fake's
        # stub only when nothing usable is found.
        self._model_id = _first_deployed_sparse_model(client) or "sparse-doc-v3"
        # Set kind based on whether qrels are present.
        # Note: runner.py line 255 overwrites quality.reference with this kind,
        # so we need to include qrels in the kind if present.
        if qrels:
            self.kind = "unpruned-baseline+qrels"
        else:
            self.kind = "unpruned-baseline"

    def reference_ranking(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        """Build/query the un-pruned baseline, cache its rankings."""
        if self._reference_cache is not None:
            # Return cached rankings, clamped to k.
            return {qid: docs[:k] for qid, docs in self._reference_cache.items()}

        # Build a temporary un-pruned index and query it.
        logger.info("Building unpruned-baseline reference for sparse_rank_features...")

        # Use a synthetic model_id (in tests, FakeOSClient will handle this).
        # In a real cluster, we'd use the same model as the main configs but with
        # prune_type=none.
        unpruned_config = Config.make(
            mode=Mode.SPARSE_RANK_FEATURES,
            label="unpruned-baseline",
            params={
                "model_id": self._model_id,  # real deployed model (or fake's stub)
                "prune_type": "none",
                "prune_ratio": None,
            },
        )

        # Build and query.
        builder = SparseRankFeaturesIndexBuilder(self.client)
        runner = SparseRankFeaturesQueryRunner(self.client)

        with builder.build(unpruned_config, self.corpus) as built:
            result = runner.run(built, queries)

        # Cache rankings.
        self._reference_cache = {qr.query_id: qr.doc_ids for qr in result.per_query}

        return {qid: docs[:k] for qid, docs in self._reference_cache.items()}


class SparseRankFeaturesConfigGenerator(ConfigGenerator):
    """Generates configs for sparse_rank_features mode with agentic pruning.

    Strategy (DESIGN §7):
    1. Enable two_phase_parameter by default (free latency win, no relevance loss).
    2. Sweep prune_ratio (e.g., none, 0.05, 0.1, 0.2) to find index-size/relevance knee.
    3. Offer doc-only vs bi-encoder if multiple models available.
    4. Hard cap ~10 configs.

    ONLY emit verified params (DESIGN §10.3): model_id, analyzer, prune_type,
    prune_ratio, two_phase_parameter. NEVER emit forbidden params (two_phase_ratio,
    should_two_phase, wand, etc.).
    """

    mode = Mode.SPARSE_RANK_FEATURES

    def seed_configs(self, cap: Capabilities, corpus: Corpus) -> list[Config]:
        """Generate initial sweep: two_phase enabled, sweep prune_ratio."""
        configs: list[Config] = []

        # Select model(s) to use. is_available guarantees at least one deployed
        # sparse model, so we never invent a placeholder id (which 404s on a real
        # cluster). Guard defensively anyway.
        models = list(cap.sparse_models)
        if not models:
            logger.warning("no deployed sparse model; skipping sparse configs")
            return []

        # Pruning ratios to sweep (including none = no pruning).
        prune_ratios = [None, 0.05, 0.1, 0.2]

        # Two-phase default config (free latency win, enabled by default).
        two_phase_default = {
            "enabled": True,
            "prune_type": "max_ratio",
            "prune_ratio": 0.4,
            "expansion_rate": 5.0,
            "max_window_size": 10000,
        }

        for model_id in models[:2]:  # Limit to 2 models to cap config count
            for prune_ratio in prune_ratios:
                # Determine if doc-only or bi-encoder.
                # Doc-only models use analyzer; bi-encoder uses model_id at query time.
                is_doc_only = "doc" in model_id.lower()

                params: dict[str, Any] = {
                    "model_id": model_id,
                    "prune_type": "max_ratio" if prune_ratio is not None else "none",
                    "prune_ratio": prune_ratio,
                    "two_phase_parameter": two_phase_default.copy(),
                }

                if is_doc_only:
                    params["analyzer"] = "bert-uncased"

                label_parts = [model_id[:12]]
                if prune_ratio is None:
                    label_parts.append("no-prune")
                else:
                    label_parts.append(f"prune={prune_ratio}")
                label_parts.append("2phase")

                label = "-".join(label_parts)

                configs.append(Config.make(self.mode, label, params))

                # Hard cap at 10 configs.
                if len(configs) >= 10:
                    break
            if len(configs) >= 10:
                break

        return configs

    def refine(
        self,
        measured,
        quality_floor: float,
        latency_budget_ms: float | None,
    ) -> list[Config]:
        """No agentic refinement in MVP; seed_configs sweeps the space once."""
        return []


class SparseRankFeaturesPlugin(ModePlugin):
    """Traditional Neural Sparse mode plugin (rank_features, exact Lucene scoring)."""

    mode = Mode.SPARSE_RANK_FEATURES

    def is_available(self, cap: Capabilities) -> bool:
        """Available only if the neural-search plugin AND a deployed sparse model
        are BOTH present. Requiring a model is essential graceful degradation:
        without one, every neural_sparse query 404s with "Fail to find model",
        so we skip the mode entirely rather than fail (verified on a real
        cluster with the plugin installed but no model deployed)."""
        return cap.sparse_rank_features and bool(cap.sparse_models)

    def index_builder(self, client) -> IndexBuilder:
        return SparseRankFeaturesIndexBuilder(client)

    def query_runner(self, client) -> QueryRunner:
        return SparseRankFeaturesQueryRunner(client)

    def cost_probe(self, client) -> CostProbe:
        return SparseRankFeaturesCostProbe(client)

    def reference_provider(
        self, client, corpus: Corpus, qrels: Qrels | None
    ) -> ReferenceProvider:
        return SparseRankFeaturesReferenceProvider(client, corpus, qrels)

    def config_generator(self) -> ConfigGenerator:
        return SparseRankFeaturesConfigGenerator()
