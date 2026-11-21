"""Neural Sparse ANN retrieval mode (sparse_vector / SEISMIC, APPROXIMATE, 3.3+).

This mode implements neural sparse search over OpenSearch's `sparse_vector` field
type backed by the SEISMIC ANN algorithm. Unlike traditional neural sparse
(`rank_features`, which is EXACT Lucene scoring), SEISMIC is an APPROXIMATION of
exact sparse scoring — it clusters posting lists and only visits the most
promising clusters at query time. That means, exactly like dense HNSW, it has a
genuine recall-vs-exact tradeoff to tune:

1. Recall via `method_parameters.heap_factor` — the `ef_search` analog: how
   aggressively query-time cluster selection explores (default 1.0, typ. [0.5, 2.0]).
   This is the dominant, cheapest recall dial, so we sweep it FIRST (DESIGN §7).
2. Recall/latency via `method_parameters.top_n` — top query tokens retained (rec. 10).
3. Index structure via ingest-time `n_postings` / `cluster_ratio` /
   `summary_prune_ratio` — escalate only if the heap_factor sweep can't reach the
   recall floor.

Quality reference: EXACT `rank_features` scoring on the SAME tokens. Because this
mode genuinely approximates exact sparse, recall-vs-exact is meaningful here
(mode.is_approximate is True) — this is the crux distinction from
sparse_rank_features (see model.Mode.is_approximate and DESIGN §6).

Scoring: Recall@k vs exact sparse (target ≥ 90%) + NDCG/MAP vs qrels when present.

Verified parameters (per DESIGN.md §5, Mode B2, since 3.3+):
- model_id (ingest): sparse encoding model (doc-only vs bi-encoder)
- analyzer (query, doc-only): tokenization lookup (fast vs inference)
- n_postings (ingest): max docs per posting list (default 0.0005 × seg doc count)
- cluster_ratio (ingest): cluster granularity ((0,1), default 0.1)
- summary_prune_ratio (ingest): cluster-summary weight retained ((0,1], default 0.4)
- approximate_threshold (ingest): min seg docs to activate ANN (default 1,000,000).
  ⚠ BELOW this, segments are indexed as plain rank_features and queried EXACTLY —
  heap_factor/top_n become no-ops and recall-vs-exact is trivially 1.0. Benchmarks
  on <1M-doc samples MUST set this to 0 (we do) or they measure exact-vs-exact.
- quantization_ceiling_ingest/search: weight → uint8 scaling
- method_parameters.top_n (query): top query tokens retained (int, rec. 10)
- method_parameters.heap_factor (query): cluster-selection recall/perf — the
  ef_search analog (float, default 1.0, typ. [0.5, 2.0])

Default strategy (§7): sweep heap_factor first at fixed n_postings; escalate to
n_postings / cluster_ratio only if the recall floor isn't met. Hard cap ~12 configs.
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
    Metric,
    Mode,
    QueryResult,
    RunResult,
)
from corpus import Corpus, QuerySet, Qrels
from interfaces import (
    BuiltConfig,
    ConfigGenerator,
    CostProbe,
    IndexBuilder,
    ModePlugin,
    QueryRunner,
    ReferenceProvider,
)

# Reuse the traditional-sparse (exact rank_features) builder + runner to
# materialize the recall ground truth. SEISMIC's reference IS exact sparse
# scoring on the same tokens, so the un-approximated rank_features path is
# precisely the right baseline — no need to reimplement it here.
from sparse_rank_features import (
    SparseRankFeaturesIndexBuilder,
    SparseRankFeaturesQueryRunner,
    _first_deployed_sparse_model,
)

if TYPE_CHECKING:
    from client import OSClient

logger = logging.getLogger(__name__)


# --- Verified parameter names (DESIGN §5 Mode B2, §10.3: these are ALLOWED) ---
VERIFIED_PARAMS = {
    "model_id",
    "analyzer",
    "n_postings",
    "cluster_ratio",
    "summary_prune_ratio",
    "approximate_threshold",
    "quantization_ceiling_ingest",
    "quantization_ceiling_search",
    "method_parameters",  # nests query-time top_n + heap_factor
}

# --- Forbidden parameter names (DESIGN §10.3: do NOT emit) ---
# SEISMIC does NOT reuse the dense-HNSW knobs, the rank_features ingest-pruning
# knobs, or two-phase (explicitly "NOT for sparse_vector", DESIGN §5 line 269).
# top_n / heap_factor belong UNDER method_parameters, never at the top level, so
# a bare top-level key is a bug we guard against here too.
FORBIDDEN_PARAMS = {
    "ef_search",
    "ef_construction",
    "m",
    "encoder",
    "prune_type",
    "prune_ratio",
    "two_phase_parameter",
    "heap_factor",  # must live under method_parameters
    "top_n",  # must live under method_parameters
    "wand",
    "block_max",
}


def _as_dict(v) -> dict:
    """method_parameters may arrive as a dict or as Config's frozen tuple of
    (key, value) pairs. Normalize to a plain dict."""
    if isinstance(v, dict):
        return dict(v)
    try:
        return dict(v)
    except Exception:
        return {}


def _seismic_size_factor(
    n_postings: int | None, cluster_ratio: float | None
) -> float:
    """Approximate SEISMIC on-disk overhead vs a plain inverted index.

    Used only to synthesize a plausible index size for the offline fake (real
    clusters report the actual store.size). SEISMIC trades index size for
    query-time approximation: it stores per-cluster summary vectors on top of
    the (capped) posting lists, so finer clustering (higher cluster_ratio) and
    longer postings (higher n_postings) both grow the footprint. Returns a
    multiplier ≥ 1.0 applied to the base inverted-index size.
    """
    factor = 1.0
    if cluster_ratio:
        # cluster_ratio ∈ (0,1); finer granularity ⇒ more summaries ⇒ larger.
        factor += 0.5 * float(cluster_ratio)
    if n_postings:
        # Longer posting caps retain more, up to a modest ceiling.
        factor += min(0.3, float(n_postings) / 20000.0)
    return factor


class SparseAnnIndexBuilder(IndexBuilder):
    """Builds a temporary index with a `sparse_vector` (SEISMIC) field + pipeline."""

    def __init__(self, client: OSClient):
        self.client = client

    @contextmanager
    def build(self, config: Config, corpus: Corpus):
        """Create index + ingest pipeline with a SEISMIC method block, yield a
        BuiltConfig, and tear everything down on exit (even on exception)."""
        index_name = f"rt-sparseann-{uuid.uuid4().hex[:8]}"
        pipeline_id = f"rt-sparseann-pipeline-{uuid.uuid4().hex[:8]}"

        model_id = config.get("model_id")
        n_postings = config.get("n_postings")
        cluster_ratio = config.get("cluster_ratio")
        summary_prune_ratio = config.get("summary_prune_ratio")
        approximate_threshold = config.get("approximate_threshold")
        quant_ingest = config.get("quantization_ceiling_ingest")

        try:
            # Ingest pipeline with the sparse_encoding processor (same as the
            # rank_features mode — the encoder produces token weights regardless
            # of the field's ANN backing).
            pipeline_body: dict[str, Any] = {
                "description": f"SEISMIC sparse encoding for {config.label}",
                "processors": [
                    {
                        "sparse_encoding": {
                            "model_id": model_id,
                            "field_map": {"text": "sparse_vector"},
                        }
                    }
                ],
            }
            self.client.put_pipeline(pipeline_id, pipeline_body)

            # SEISMIC lives in the sparse_vector field's `method` block. Only emit
            # ingest params that were actually set so we never send a null the
            # cluster would reject.
            method_params: dict[str, Any] = {}
            if n_postings is not None:
                method_params["n_postings"] = n_postings
            if cluster_ratio is not None:
                method_params["cluster_ratio"] = cluster_ratio
            if summary_prune_ratio is not None:
                method_params["summary_prune_ratio"] = summary_prune_ratio
            if approximate_threshold is not None:
                method_params["approximate_threshold"] = approximate_threshold
            if quant_ingest is not None:
                method_params["quantization_ceiling_ingest"] = quant_ingest

            sparse_vector_field: dict[str, Any] = {"type": "sparse_vector"}
            if method_params:
                sparse_vector_field["method"] = {
                    "name": "seismic",
                    "parameters": method_params,
                }

            index_body = {
                "settings": {
                    "default_pipeline": pipeline_id,
                    "number_of_shards": 1,
                    # REQUIRED for SEISMIC: without index.sparse=true the
                    # sparse_vector field is created but the SEISMIC token
                    # structures don't engage, and a neural_sparse query fails at
                    # parse time with "Query tokens should be valid integer".
                    # (Verified on OpenSearch 3.8: false -> that error; true -> works.)
                    "index.sparse": True,
                },
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword"},
                        "text": {"type": "text"},
                        "sparse_vector": sparse_vector_field,
                    }
                },
            }
            self.client.create_index(index_name, index_body)

            # Index documents. On a real cluster the ingest pipeline applies
            # sparse_encoding + builds the SEISMIC structures; in the fake we
            # index text (and any precomputed sparse tokens) and let the fake's
            # scoring path handle it.
            docs_to_bulk = []
            for doc in corpus.documents:
                doc_dict: dict[str, Any] = {"id": doc.id, "text": doc.text or ""}
                if "sparse_tokens" in doc.fields:
                    doc_dict["sparse_vector"] = doc.fields["sparse_tokens"]
                docs_to_bulk.append(doc_dict)

            if docs_to_bulk:
                self.client.bulk(index_name, docs_to_bulk)
                self.client.refresh(index_name)

            # Offline demo fidelity only: synthesize a SEISMIC-shaped index size
            # for the in-memory fake (which can't actually build the structures).
            # On a REAL cluster this is a no-op — cat_indices reports the true
            # store.size. Guarded by duck-typing so it never touches production.
            fake_indices = getattr(self.client, "indices", None)
            if isinstance(fake_indices, dict) and index_name in fake_indices:
                base = len(docs_to_bulk) * 1100  # ~unpruned postings per doc
                factor = _seismic_size_factor(n_postings, cluster_ratio)
                fake_indices[index_name]["_size_bytes"] = int(base * factor)

            built = BuiltConfig(
                config=config,
                index_name=index_name,
                extra={"pipeline_id": pipeline_id},
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


class SparseAnnQueryRunner(QueryRunner):
    """Executes neural_sparse queries over the SEISMIC field with method_parameters.

    The APPROXIMATE path is triggered by passing `method_parameters`
    (heap_factor / top_n) inside the neural_sparse clause — this is what
    distinguishes SEISMIC ANN from an exact rank_features query, and what the
    FakeOSClient reads to model recall as a function of heap_factor.
    """

    def __init__(self, client: OSClient):
        self.client = client

    def run(self, built: BuiltConfig, queries: QuerySet) -> RunResult:
        config = built.config
        index_name = built.index_name
        model_id = config.get("model_id")
        analyzer = config.get("analyzer")
        method_parameters = _as_dict(config.get("method_parameters"))
        quant_search = config.get("quantization_ceiling_search")
        if quant_search is not None:
            # Query-time quantization ceiling rides alongside the other
            # method_parameters on the neural_sparse clause.
            method_parameters = {**method_parameters, "quantization_ceiling_search": quant_search}

        # The SEISMIC ANN layer returns at most `method_parameters.k` candidates
        # per segment (default 10). If we leave it at 10 but request size=100, the
        # result set is SILENTLY capped below the eval depth — deflating every
        # recall@k number vs the exact reference (verified on 3.8: 40 matching
        # docs, size=100 → 20 hits without k, 40 with k=100). So pin k to the
        # result size so recall is measured at full depth.
        SIZE = 100
        method_parameters = {**method_parameters, "k": SIZE}

        per_query: list[QueryResult] = []

        for query in queries:
            # Doc-only model: use analyzer (fast lookup). Bi-encoder: model_id
            # inference at query time. Either way the SEISMIC method_parameters
            # ride on the neural_sparse clause.
            inner: dict[str, Any] = {"query_text": query.text or ""}
            if analyzer:
                inner["analyzer"] = analyzer
            else:
                inner["model_id"] = model_id
            if method_parameters:
                inner["method_parameters"] = method_parameters

            query_body = {
                "query": {"neural_sparse": {"sparse_vector": inner}},
                "size": SIZE,
            }

            resp = self.client.search(index_name, query_body)
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


class SparseAnnCostProbe(CostProbe):
    """Measures SEISMIC index size via cat_indices (store.size).

    SEISMIC's cost axis is index size — like rank_features, but with the added
    per-cluster summary structures. We read the real store.size on a live
    cluster; the fake synthesizes a SEISMIC-shaped size in the builder.
    """

    def __init__(self, client: OSClient):
        self.client = client

    def measure(self, built: BuiltConfig) -> Cost:
        index_name = built.index_name
        indices = self.client.cat_indices(index_name)
        if not indices:
            return Cost(index_size_bytes=0)
        size_str = indices[0].get("store.size", "0b")
        return Cost(index_size_bytes=_parse_size_to_bytes(size_str))


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
    try:
        return int(float(size_str))
    except ValueError:
        return 0


class SparseAnnReferenceProvider(ReferenceProvider):
    """Provides EXACT sparse (rank_features) scoring as the recall ground truth.

    SEISMIC approximates exact sparse scoring on the SAME tokens, so the correct
    reference is a rank_features index with NO pruning queried WITHOUT SEISMIC
    method_parameters (i.e. exact Lucene scoring). We reuse the rank_features
    builder/runner for this rather than reimplementing it. `kind = "exact-sparse"`
    is the honest label the report shows (recall-vs-exact, genuinely meaningful
    for this mode — see model.Mode.is_approximate).
    """

    kind = "exact-sparse"

    def __init__(self, client: OSClient, corpus: Corpus, qrels: Qrels | None):
        self.client = client
        self.corpus = corpus
        self.qrels = qrels
        self._reference_cache: dict[str, list[str]] | None = None
        # Re-derive a real DEPLOYED SPARSE model with the SAME filter probe uses,
        # so the exact baseline and the swept SEISMIC configs compare like-for-like
        # (never a raw ml_models()[0], which could be a text-embedding model that
        # 404s the neural_sparse baseline query). Falls back to the fake's stub.
        self._model_id = _first_deployed_sparse_model(client) or "sparse-doc-v3"

    def reference_ranking(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        """Build/query the exact rank_features baseline once, cache its rankings."""
        if self._reference_cache is not None:
            return {qid: docs[:k] for qid, docs in self._reference_cache.items()}

        logger.info("Building exact-sparse (rank_features) reference for sparse_ann...")

        # Exact rank_features baseline: same encoder model, NO pruning, and — via
        # the rank_features runner — a plain neural_sparse query with no SEISMIC
        # method_parameters, i.e. exact scoring.
        exact_config = Config.make(
            mode=Mode.SPARSE_RANK_FEATURES,
            label="exact-sparse-baseline",
            params={
                "model_id": self._model_id,
                "prune_type": "none",
                "prune_ratio": None,
            },
        )

        builder = SparseRankFeaturesIndexBuilder(self.client)
        runner = SparseRankFeaturesQueryRunner(self.client)
        with builder.build(exact_config, self.corpus) as built:
            result = runner.run(built, queries)

        self._reference_cache = {qr.query_id: qr.doc_ids for qr in result.per_query}
        return {qid: docs[:k] for qid, docs in self._reference_cache.items()}


class SparseAnnConfigGenerator(ConfigGenerator):
    """Generates configs for sparse_ann (SEISMIC) with agentic pruning.

    Strategy (DESIGN §7):
    1. Sweep heap_factor FIRST (the ef_search analog, cheapest recall dial):
       [0.5, 1.0, 1.5, 2.0] at fixed n_postings / cluster_ratio and top_n=10.
    2. Add a couple of n_postings variants at mid heap_factor to expose the
       index-size/recall knee (escalation the refine() step would otherwise reach).
    3. Offer doc-only vs bi-encoder if multiple models available.
    4. Hard cap ~12 configs.

    ONLY emit verified params (DESIGN §10.3). top_n / heap_factor go UNDER
    method_parameters, never at the top level.
    """

    mode = Mode.SPARSE_ANN

    # Query-time top_n values to try during refinement, smallest-latency first.
    # top_n < 10 keeps fewer query tokens ⇒ fewer posting lists visited ⇒ faster,
    # at some recall risk. We only explore these AFTER a config clears the recall
    # floor, so we're spending a proven-good config's headroom on latency.
    _REFINE_TOP_N = (7, 5, 3)

    def __init__(self) -> None:
        # Guard so refine() proposes the top_n ladder at most once (it returns []
        # on subsequent calls, terminating the CLI's refine loop).
        self._refined = False

    def seed_configs(self, cap: Capabilities, corpus: Corpus) -> list[Config]:
        self._refined = False
        configs: list[Config] = []

        models = list(cap.sparse_models)
        if not models:
            logger.warning("no deployed sparse model; skipping sparse_ann configs")
            return []

        model_id = models[0]
        is_doc_only = "doc" in model_id.lower()

        # Fixed, sensible ingest defaults for the primary sweep (DESIGN §5 B2).
        base_n_postings = 4000
        base_cluster_ratio = 0.1
        base_summary_prune = 0.4
        base_top_n = 10

        # CRITICAL: force the SEISMIC ANN path to ENGAGE on the benchmark sample.
        # SEISMIC only builds/uses its approximate structures once a segment holds
        # >= approximate_threshold docs (default ~1,000,000); below that it
        # SILENTLY scores exactly. We benchmark on a *sample*, which is far below
        # 1M, so without lowering this the whole mode would measure exact-vs-exact
        # (recall trivially 1.0) and heap_factor/top_n would be no-ops — verified
        # on OpenSearch 3.8: with the default threshold, heap_factor=0.3 and 2.0
        # return identical results; with approximate_threshold=0 they differ.
        # We set 0 so ANN is active for any sample size; on a full production
        # index the user can raise it via the emitted template.
        base_approximate_threshold = 0

        def _mk(model_id, n_postings, hf, top_n=base_top_n):
            params: dict[str, Any] = {
                "model_id": model_id,
                "n_postings": n_postings,
                "cluster_ratio": base_cluster_ratio,
                "summary_prune_ratio": base_summary_prune,
                "approximate_threshold": base_approximate_threshold,
                "method_parameters": {"top_n": top_n, "heap_factor": hf},
            }
            if is_doc_only:
                params["analyzer"] = "bert-uncased"
            return params

        # 1) Sweep heap_factor first (the ef_search analog).
        for hf in [0.5, 1.0, 1.5, 2.0]:
            label = f"{model_id[:12]}-heap={hf}-npost={base_n_postings}"
            configs.append(Config.make(self.mode, label, _mk(model_id, base_n_postings, hf)))

        # 2) A couple of n_postings variants at mid heap_factor to surface the
        #    index-size/recall knee (higher n_postings ⇒ better recall, bigger index).
        for n_postings in (2000, 8000):
            label = f"{model_id[:12]}-heap=1.0-npost={n_postings}"
            configs.append(Config.make(self.mode, label, _mk(model_id, n_postings, 1.0)))
            if len(configs) >= 12:
                break

        return configs[:12]

    def refine(
        self,
        measured,
        quality_floor: float | None,
        latency_budget_ms: float | None,
    ) -> list[Config]:
        """Agentic refinement (DESIGN §7): once a config clears the recall floor,
        spend its headroom on LATENCY by lowering top_n at the winning
        heap_factor.

        This is the "sweep the dominant recall knob first, then optimize the
        cheaper latency knob" step:
        1. heap_factor is swept in seed_configs (the recall dial).
        2. Here we find the fastest config that still meets `quality_floor`, and
           propose lower-top_n variants of it — fewer query terms retained ⇒
           fewer posting lists visited ⇒ lower latency. recall may dip, so the
           harness re-measures each and the recommender keeps only those that
           still clear the floor.

        Returns [] (stop) when: no floor is set, nothing met the floor, or we've
        already proposed the ladder once. That makes the CLI's refine loop
        terminate deterministically.
        """
        if self._refined or not quality_floor or not measured:
            return []
        self._refined = True

        # Candidates that met the recall floor; pick the lowest-latency one as
        # the base to speed up further (it has the most headroom to trade).
        qualified = [
            m for m in measured
            if (m.quality.get(Metric.RECALL, 10) or 0.0) >= quality_floor
        ]
        if not qualified:
            logger.info("sparse_ann refine: no config met the recall floor; stopping")
            return []
        base = min(qualified, key=lambda m: m.latency_p95_ms)
        base_params = base.config.as_dict()
        base_mp = _as_dict(base_params.get("method_parameters"))
        base_top_n = base_mp.get("top_n", 10)
        base_hf = base_mp.get("heap_factor", 1.0)

        follow_ups: list[Config] = []
        for top_n in self._REFINE_TOP_N:
            if top_n >= base_top_n:
                continue  # only try SMALLER top_n (faster than the base)
            params = dict(base_params)
            params["method_parameters"] = {"top_n": top_n, "heap_factor": base_hf}
            label = f"{str(base_params.get('model_id',''))[:12]}-heap={base_hf}-topn={top_n}"
            follow_ups.append(Config.make(self.mode, label, params))

        if follow_ups:
            probed = [tn for tn in self._REFINE_TOP_N if tn < base_top_n]
            logger.info(
                "sparse_ann refine: %d config(s) met the recall floor; probing "
                "top_n %s at heap_factor=%s to cut latency",
                len(qualified), probed, base_hf,
            )
        return follow_ups


class SparseAnnPlugin(ModePlugin):
    """Neural Sparse ANN mode plugin (sparse_vector / SEISMIC, approximate, 3.3+)."""

    mode = Mode.SPARSE_ANN

    def is_available(self, cap: Capabilities) -> bool:
        """Available only if SEISMIC (neural-search + 3.3+) AND a deployed sparse
        model are BOTH present. Requiring a model is essential graceful
        degradation: without one every neural_sparse query 404s with "Fail to
        find model", so we skip the mode entirely rather than fail — identical to
        the rank_features gate."""
        return cap.sparse_ann and bool(cap.sparse_models)

    def index_builder(self, client) -> IndexBuilder:
        return SparseAnnIndexBuilder(client)

    def query_runner(self, client) -> QueryRunner:
        return SparseAnnQueryRunner(client)

    def cost_probe(self, client) -> CostProbe:
        return SparseAnnCostProbe(client)

    def reference_provider(
        self, client, corpus: Corpus, qrels: Qrels | None
    ) -> ReferenceProvider:
        return SparseAnnReferenceProvider(client, corpus, qrels)

    def config_generator(self) -> ConfigGenerator:
        return SparseAnnConfigGenerator()
