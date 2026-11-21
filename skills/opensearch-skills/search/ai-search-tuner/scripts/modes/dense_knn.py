"""Dense k-NN retrieval mode — HNSW approximate search with quantization.

This is the MVP core mode. It implements:
- HNSW index building with m, ef_construction, ef_search parameters
- Quantization/encoder support (FP32, FP16, etc. — detected from Capabilities)
- Approximate search via knn query (with ef_search)
- Exact brute-force reference via script_score cosine (for recall ground truth)
- HNSW graph memory cost estimation

HNSW graph memory formula (source: OpenSearch k-NN plugin documentation)
------------------------------------------------------------------------
The standard HNSW memory estimate is:
    graph_memory_bytes ≈ num_vectors × (4 × dim + 8 × m) × 1.1

Where:
    - 4 × dim = bytes per vector for FP32 coordinates (adjust for quantization)
    - 8 × m = bytes for HNSW graph edges (m = max connections per node)
    - 1.1 = overhead factor for metadata, alignment, etc.

For quantized encoders (FP16, etc.), the vector storage part (4×dim) should be
scaled accordingly: FP16 → 2×dim, INT8 → 1×dim, etc. For this MVP we use the
base formula and note that real deployments should calibrate via knn_stats.

References:
    - OpenSearch k-NN plugin docs (HNSW section)
    - Lucene HnswGraph memory layout
    - https://github.com/opensearch-project/k-NN/issues/3414 (OOM investigation)
"""

from __future__ import annotations

import hashlib
import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from model import Capabilities, Config, Cost, Metric, Mode, QueryResult, RunResult
from interfaces import (
    BuiltConfig,
    ConfigGenerator,
    CostProbe,
    IndexBuilder,
    ModePlugin,
    QueryRunner,
    ReferenceProvider,
)

if TYPE_CHECKING:
    from corpus import Corpus, Query, QuerySet, Qrels

logger = logging.getLogger(__name__)


# ============================= IndexBuilder =============================


class DenseIndexBuilder(IndexBuilder):
    """Builds temporary HNSW indices for dense k-NN configs."""

    def __init__(self, client):
        self.client = client

    @contextmanager
    def build(self, config: Config, corpus: Corpus):
        """Create a temporary knn_vector index with HNSW parameters from config.

        The index name is like `rt-dense-<label>-<shortid>` where shortid is a
        hash of the config params (for deterministic naming + collision avoidance).

        Index lifecycle:
            1. Create index with knn_vector mapping (HNSW, space_type=cosinesimil)
            2. Bulk-index corpus vectors
            3. Refresh
            4. Yield BuiltConfig
            5. On __exit__ (even on exception): delete_index

        Quantization/encoder:
            - FP32 is the default (no explicit encoder in mapping)
            - FP16, PQ, etc. are set via mapping.properties.<field>.method.parameters.encoder
            - The config's "encoder" param drives this; unsupported encoders should
              have been filtered out by ConfigGenerator using Capabilities.
        """
        # Extract config params
        params = config.as_dict()
        m = params.get("m", 16)
        ef_construction = params.get("ef_construction", 100)
        encoder = params.get("encoder", "fp32")
        # ef_search is query-time only, not in the index mapping

        # Generate deterministic index name
        label_safe = config.label.replace(" ", "-").replace("_", "-")[:20]
        param_hash = hashlib.md5(str(config.params).encode()).hexdigest()[:8]
        index_name = f"rt-dense-{label_safe}-{param_hash}"

        # Build knn_vector mapping
        vector_field_params: dict[str, Any] = {
            "type": "knn_vector",
            "dimension": corpus.dim or 128,  # fallback if dim is None
            "method": {
                "name": "hnsw",
                "space_type": "cosinesimil",
                "engine": "lucene",  # default, stable across distros
                "parameters": {
                    "m": m,
                    "ef_construction": ef_construction,
                },
            },
        }

        # Add encoder if not FP32 (FP32 is the implicit default).
        # The Lucene engine expresses quantization via a scalar-quantization
        # ("sq") encoder with a `bits` parameter — NOT a faiss-style
        # {"name": "fp16"} block, which raises "methodComponent is null". On
        # OpenSearch 3.6+ `bits` is REQUIRED and only specific values are
        # supported (verified against 3.8: bits ∈ {1, 7}). We map our abstract
        # encoder names to the Lucene sq bits accordingly:
        #   fp16  -> sq/bits=7  (half-ish precision, the standard memory saver)
        #   binary-> sq/bits=1
        enc = encoder.lower()
        if enc != "fp32":
            bits = {"fp16": 7, "binary": 1}.get(enc)
            if bits is not None:
                vector_field_params["method"]["parameters"]["encoder"] = {
                    "name": "sq",
                    "parameters": {"bits": bits},
                }
            else:
                # Unknown/unsupported encoder name for the Lucene engine — fall
                # back to FP32 rather than emit an invalid mapping. (Capability
                # detection should keep us from getting here.)
                logger.warning(
                    "encoder %r not supported on the lucene engine; using fp32", encoder
                )

        mapping = {
            "settings": {
                "index": {
                    "knn": True,
                }
            },
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "vector": vector_field_params,
                }
            },
        }

        logger.info(f"Creating dense index {index_name} (m={m}, ef_construction={ef_construction}, encoder={encoder})")

        try:
            # Create index
            self.client.create_index(index_name, mapping)

            # Bulk-index corpus vectors
            docs_to_index = []
            for doc in corpus.documents:
                if doc.vector is None:
                    logger.warning(f"Document {doc.id} has no vector; skipping")
                    continue
                docs_to_index.append({
                    "id": doc.id,
                    "vector": doc.vector,
                })

            if docs_to_index:
                self.client.bulk(index_name, docs_to_index)
                self.client.refresh(index_name)
                logger.info(f"Indexed {len(docs_to_index)} vectors into {index_name}")

            # Readiness gate: a freshly created+bulked index can briefly 404 on
            # the FIRST search while the shard/mapping becomes visible on a busy
            # node (observed intermittently on a shared cluster — it silently
            # dropped a config from the sweep and even shifted the recommended
            # value). Poll a cheap size:0 search until it answers before we hand
            # the index to the query phase. Best-effort: bounded, never fatal.
            for _attempt in range(20):
                try:
                    self.client.search(index_name, {"size": 0, "query": {"match_all": {}}})
                    break
                except Exception:  # not-yet-visible / transient — retry
                    time.sleep(0.25)

            # Yield control (pass dim in extra for CostProbe)
            built = BuiltConfig(
                config=config,
                index_name=index_name,
                extra={"dim": corpus.dim or 128}
            )
            yield built

        finally:
            # Guaranteed teardown: delete the index even on exception
            logger.info(f"Tearing down dense index {index_name}")
            self.client.delete_index(index_name)


# ============================= QueryRunner =============================


class DenseQueryRunner(QueryRunner):
    """Executes knn queries (approximate) with ef_search from config."""

    def __init__(self, client):
        self.client = client

    def run(self, built: BuiltConfig, queries: QuerySet) -> RunResult:
        """Run each query as a knn query with ef_search and k from config.

        The knn query is the APPROXIMATE path (HNSW graph traversal). This is
        what the FakeOSClient understands as approximate (via _is_approximate_knn).
        """
        params = built.config.as_dict()
        k = params.get("k", 10)
        ef_search = params.get("ef_search", 100)

        per_query = []
        for query in queries:
            if query.vector is None:
                logger.warning(f"Query {query.id} has no vector; skipping")
                continue

            # knn query (approximate). ef_search is a query-time knob set via
            # method_parameters.ef_search (Lucene/faiss engines). Passing it here
            # makes the sweep real on live clusters; the FakeOSClient reads it to
            # model recall as a function of ef_search (higher ef → higher recall).
            body = {
                "size": k,
                "query": {
                    "knn": {
                        "vector": {
                            "vector": query.vector,
                            "k": k,
                            "method_parameters": {"ef_search": ef_search},
                        }
                    }
                },
            }

            resp = self.client.search(built.index_name, body)
            took_ms = float(resp.get("took", 0))

            # Extract ranked doc ids
            hits = resp.get("hits", {}).get("hits", [])
            doc_ids = [h["_id"] for h in hits]
            scores = [float(h.get("_score", 0.0)) for h in hits]

            per_query.append(
                QueryResult(
                    query_id=query.id,
                    doc_ids=doc_ids,
                    scores=scores,
                    took_ms=took_ms,
                )
            )

        return RunResult(config=built.config, per_query=per_query)


# ============================= CostProbe =============================


class DenseCostProbe(CostProbe):
    """Measures HNSW graph memory for a built config.

    Uses the formula: graph_memory_bytes ≈ 1.1 × (4×dim + 8×m) × num_vectors

    This is the standard OpenSearch k-NN memory estimate. In a real deployment,
    prefer reading knn_stats or cluster_stats if available, but fall back to
    this formula when those aren't accessible (or for FakeOSClient).
    """

    def __init__(self, client):
        self.client = client

    def measure(self, built: BuiltConfig) -> Cost:
        params = built.config.as_dict()
        m = params.get("m", 16)
        encoder = params.get("encoder", "fp32")

        # Try to get real stats from the client
        try:
            # Check cat_indices for actual doc count
            indices_info = self.client.cat_indices(built.index_name)
            num_vectors = 0
            if indices_info:
                docs_count_str = indices_info[0].get("docs.count", "0")
                num_vectors = int(docs_count_str)

            # Infer dimensionality from the index mapping (or use a fallback)
            # For simplicity, we'll infer from the config if it has a corpus reference
            # In real usage, we'd inspect the index mapping. For now, use a heuristic.
            # The built config should have extra info if needed.
            dim = built.extra.get("dim", 128)  # fallback

            # Bytes per vector coordinate (quantization-aware)
            bytes_per_coord = _bytes_per_coordinate(encoder)

            # Formula: graph_memory_bytes ≈ 1.1 × (bytes_per_coord×dim + 8×m) × num_vectors
            graph_memory_bytes = int(1.1 * (bytes_per_coord * dim + 8 * m) * num_vectors)

            return Cost(graph_memory_bytes=graph_memory_bytes)

        except Exception as e:
            logger.warning(f"Could not measure cost for {built.index_name}: {e}")
            return Cost(graph_memory_bytes=0)


def _bytes_per_coordinate(encoder: str) -> int:
    """Return bytes per vector coordinate for a given encoder."""
    encoder_lower = encoder.lower()
    if encoder_lower == "fp32":
        return 4
    elif encoder_lower == "fp16":
        return 2
    elif "int8" in encoder_lower or "scalar" in encoder_lower:
        return 1
    elif "pq" in encoder_lower or "binary" in encoder_lower:
        return 1  # approximate, depends on PQ params
    else:
        return 4  # default fallback


# ============================= ReferenceProvider =============================


class DenseReferenceProvider(ReferenceProvider):
    """Computes EXACT top-k via brute-force cosine over the full corpus.

    This is the recall ground truth for approximate HNSW. It uses script_score
    with cosine, which FakeOSClient recognizes as the EXACT path (not approximate).

    In production, this is O(N × queries) and should only run on sampled indices.
    """

    kind = "fp32-brute-force"

    def __init__(self, client, corpus: Corpus):
        self.client = client
        self.corpus = corpus
        self._index_name: str | None = None

    def close(self) -> None:
        """Tear down the temporary reference index. Idempotent; safe on error.

        The harness calls this in a finally block so the exact-reference index
        never leaks (DESIGN §4.3). Optional part of the ReferenceProvider
        contract — the runner calls it only if present.
        """
        if self._index_name is not None:
            try:
                self.client.delete_index(self._index_name)
                logger.info(f"Tearing down reference index {self._index_name}")
            except Exception as e:  # pragma: no cover - best-effort cleanup
                logger.warning(f"Reference index teardown had issues: {e}")
            finally:
                self._index_name = None

    def reference_ranking(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        """Compute exact top-k for each query via brute-force script_score.

        This MUST use script_score with params.query_value so FakeOSClient
        recognizes it as EXACT (not approximate).
        """
        # Ensure we have a reference index with the corpus
        ref_index = self._ensure_reference_index()

        ranking = {}
        for query in queries:
            if query.vector is None:
                logger.warning(f"Query {query.id} has no vector for reference; skipping")
                continue

            # Exact brute-force via the k-NN plugin's `knn_score` painless
            # script (lang="knn"). This is the CORRECT exact-scoring API:
            #   - `cosineSimilarity(params.query_value, 'vector')` fails on real
            #     OpenSearch with a class_cast_exception (the k-NN field can't be
            #     addressed by a string literal in stock Painless).
            #   - `knn_score` computes exact cosine over every doc (no ANN graph),
            #     which is exactly the brute-force ground truth we want.
            # We keep `params.query_value` so FakeOSClient still recognizes this
            # as the EXACT path in _extract_query_vector.
            body = {
                "size": k,
                "query": {
                    "script_score": {
                        "query": {"match_all": {}},
                        "script": {
                            "source": "knn_score",
                            "lang": "knn",
                            "params": {
                                "field": "vector",
                                "query_value": query.vector,
                                "space_type": "cosinesimil",
                            },
                        },
                    }
                },
            }

            resp = self.client.search(ref_index, body)
            hits = resp.get("hits", {}).get("hits", [])
            doc_ids = [h["_id"] for h in hits]
            ranking[query.id] = doc_ids

        return ranking

    def _ensure_reference_index(self) -> str:
        """Create a temporary reference index if not already built.

        This creates a simple index with vectors that we can query via script_score
        for exact brute-force. For FakeOSClient, any index with vectors works.
        """
        if self._index_name is not None:
            return self._index_name

        # UNIQUE name per provider instance. A fixed name would collide on a real
        # cluster: create_index raises resource_already_exists_exception, the code
        # falls through, and we'd query a PRE-EXISTING index whose vectors may be
        # from a different corpus — silently producing a wrong recall ground truth.
        suffix = hashlib.sha1(
            f"{id(self)}:{len(self.corpus)}".encode()
        ).hexdigest()[:8]
        index_name = f"rt-dense-reference-exact-{suffix}"

        # The brute-force reference queries with Painless
        # cosineSimilarity(params.query_value, 'vector'), which requires the
        # field to be typed knn_vector (a plain float array raises a
        # class_cast_exception / compile error on real OpenSearch).
        #
        # IMPORTANT: we force the LUCENE engine. The default (faiss) needs a
        # native library (opensearchknn_faiss) that may be absent on dev builds
        # and, when missing, crashes the node on refresh with UnsatisfiedLinkError.
        # Lucene's k-NN is pure Java, always present, and we only need exact
        # cosineSimilarity scoring here (not an ANN graph). dimension is required.
        dim = self.corpus.dim or (
            len(self.corpus.documents[0].vector)
            if self.corpus.documents and self.corpus.documents[0].vector
            else 0
        )
        mapping = {
            "settings": {"index": {"knn": True}},
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "vector": {
                        "type": "knn_vector",
                        "dimension": dim,
                        "method": {
                            "name": "hnsw",
                            "space_type": "cosinesimil",
                            "engine": "lucene",
                        },
                    },
                }
            },
        }

        try:
            # Delete-then-create so the reference is always fresh for THIS corpus,
            # even if a prior run leaked an index with a colliding name.
            self.client.delete_index(index_name)
            self.client.create_index(index_name, mapping)

            # Bulk-index corpus
            docs_to_index = []
            for doc in self.corpus.documents:
                if doc.vector is None:
                    continue
                docs_to_index.append({"id": doc.id, "vector": doc.vector})

            if docs_to_index:
                self.client.bulk(index_name, docs_to_index)
                self.client.refresh(index_name)
                logger.info(f"Created reference index {index_name} with {len(docs_to_index)} vectors")

        except Exception as e:
            logger.warning(f"Reference index creation had issues: {e}")

        self._index_name = index_name
        return index_name


# ============================= ConfigGenerator =============================


class DenseConfigGenerator(ConfigGenerator):
    """Agentic config-space pruning for dense k-NN.

    Strategy (per DESIGN.md §7):
        1. Fix reasonable m and ef_construction (baseline: m=16, ef_construction=100)
        2. Sweep ef_search FIRST (cheapest query-time recall dial): [50, 100, 200, 400]
        3. Include FP32 baseline + any Capabilities-supported quantization at mid ef_search
        4. Only escalate to varying m/ef_construction if recall floor isn't met
        5. Hard cap: ~12 configs total

    This keeps the sweep bounded and sweeps the dominant knob first.
    """

    mode = Mode.DENSE_KNN

    # ef_search escalation ladder for refine() — the cheap, query-time recall
    # dial. Larger values recover HNSW *traversal* loss (but NOT quantization
    # precision loss), so refine can distinguish the two by whether recall moves.
    _REFINE_EF_SEARCH = (800, 1600)

    def __init__(self) -> None:
        # refine() proposes its escalation at most once, then returns [] so the
        # CLI's refine loop terminates deterministically.
        self._refined = False

    def seed_configs(self, cap: Capabilities, corpus: Corpus) -> list[Config]:
        """Generate initial config sweep."""
        self._refined = False
        configs = []

        # Baseline build params (sweep these only if recall floor unmet)
        m_baseline = 16
        ef_construction_baseline = 100

        # Sweep ef_search FIRST (query-time recall dial, cheapest)
        ef_search_values = [50, 100, 200, 400]

        # FP32 baseline across ef_search values
        for ef_search in ef_search_values:
            configs.append(
                Config.make(
                    mode=Mode.DENSE_KNN,
                    label=f"fp32-m{m_baseline}-efc{ef_construction_baseline}-efs{ef_search}",
                    params={
                        "m": m_baseline,
                        "ef_construction": ef_construction_baseline,
                        "ef_search": ef_search,
                        "encoder": "fp32",
                        "k": 10,
                    },
                )
            )

        # Add quantized encoders at BOTH a low and a high ef_search. Testing a
        # quantized encoder at a single ef_search is a trap: quantization recall
        # loss looks worst at low ef_search, so a single mid point can't tell
        # "precision loss" (recall stays low even at high ef_search) from
        # "traversal loss" (recall recovers as ef_search rises). Sweeping two
        # points surfaces that distinction directly — the recommender then knows
        # whether spending ef_search buys the cheaper encoder back to the floor.
        # Only emit encoders the IndexBuilder can MAP to a Lucene mapping
        # (fp16→sq/bits=7, binary→sq/bits=1); probe reports fp32/fp16 today.
        buildable = {"fp16", "binary"}
        quant_ef_search = [100, 400]  # low + high, to expose precision-vs-traversal
        supported_encoders = [
            enc for enc in cap.quantization
            if enc.lower() != "fp32" and enc.lower() in buildable
        ]

        for encoder in supported_encoders:
            for ef_search in quant_ef_search:
                configs.append(
                    Config.make(
                        mode=Mode.DENSE_KNN,
                        label=f"{encoder}-m{m_baseline}-efc{ef_construction_baseline}-efs{ef_search}",
                        params={
                            "m": m_baseline,
                            "ef_construction": ef_construction_baseline,
                            "ef_search": ef_search,
                            "encoder": encoder,
                            "k": 10,
                        },
                    )
                )

        # Cap at 12 configs (design constraint)
        return configs[:12]

    def refine(
        self, measured, quality_floor: float | None, latency_budget_ms: float | None
    ) -> list[Config]:
        """Escalate ef_search when nothing met the recall floor (DESIGN §7).

        ef_search is the cheapest recall dial (query-time, zero extra heap). If no
        seed config cleared the floor, re-test the highest-recall config at much
        larger ef_search. This also disambiguates the failure mode: if recall
        rises, the seed just under-searched (traversal loss); if it stays flat,
        it's quantization precision loss that ef_search can't fix (e.g. fp16 on
        high-dim vectors) — either way the recommender then has the evidence.

        Returns [] (stop) when: no floor set, everything already met the floor, or
        we've already escalated once.
        """
        if self._refined or not quality_floor or not measured:
            return []
        # If something already clears the floor, no escalation needed.
        best = max(measured, key=lambda m: (m.quality.get(Metric.RECALL, 10) or 0.0))
        if (best.quality.get(Metric.RECALL, 10) or 0.0) >= quality_floor:
            return []
        self._refined = True

        base = best.config.as_dict()
        base_ef = base.get("ef_search", 100)
        follow_ups: list[Config] = []
        for ef in self._REFINE_EF_SEARCH:
            if ef <= base_ef:
                continue
            params = dict(base)
            params["ef_search"] = ef
            enc = params.get("encoder", "fp32")
            label = f"{enc}-m{params.get('m')}-efc{params.get('ef_construction')}-efs{ef}"
            follow_ups.append(Config.make(Mode.DENSE_KNN, label, params))
        if follow_ups:
            logger.info(
                "dense refine: best recall %.3f < floor %.2f; escalating ef_search to %s",
                best.quality.get(Metric.RECALL, 10) or 0.0, quality_floor,
                [ef for ef in self._REFINE_EF_SEARCH if ef > base_ef],
            )
        return follow_ups


# ============================= ModePlugin =============================


class DenseKnnPlugin(ModePlugin):
    """Dense k-NN mode plugin — the MVP core mode."""

    mode = Mode.DENSE_KNN

    def is_available(self, cap: Capabilities) -> bool:
        return cap.dense_knn

    def index_builder(self, client) -> IndexBuilder:
        return DenseIndexBuilder(client)

    def query_runner(self, client) -> QueryRunner:
        return DenseQueryRunner(client)

    def cost_probe(self, client) -> CostProbe:
        return DenseCostProbe(client)

    def reference_provider(self, client, corpus: Corpus, qrels) -> ReferenceProvider:
        return DenseReferenceProvider(client, corpus)

    def config_generator(self) -> ConfigGenerator:
        return DenseConfigGenerator()
