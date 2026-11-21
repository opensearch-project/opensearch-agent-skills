"""Hybrid retrieval mode — combining dense + sparse via search pipeline.

This mode implements OpenSearch hybrid search: a search pipeline with normalization
and combination processors that merge dense k-NN and neural sparse signals. Per
DESIGN §5 Mode C, §7, and §8, v1 fixes normalization=min_max and
combination=arithmetic_mean, and sweeps ONLY the weight ratio dense:sparse.

Quality reference: BEST STANDALONE mode (higher of dense-only or sparse-only NDCG).
This is NOT an approximate vs exact comparison (hybrid.is_approximate == False);
we grade hybrid on NDCG lift vs the best single signal.

Verified parameters (per DESIGN §5, references/parameters.md):
- normalization: min_max / l2 / z_score (v1: FIXED at min_max)
- combination: arithmetic_mean / harmonic_mean / geometric_mean (v1: FIXED at arithmetic_mean)
- weights: [w_dense, w_sparse] where w_dense + w_sparse = 1.0 (v1: SWEEP this)

DO NOT TUNE (§10.3): sub_query_raw_scores (#1419), WAND (#1829), dynamic
normalization (#1005) — these are open RFCs, not stable APIs.

Default strategy (§7): Fix arithmetic_mean + min_max, sweep weight ratio
[0.1:0.9, 0.3:0.7, 0.5:0.5, 0.7:0.3, 0.9:0.1]. Hard cap ~6 configs.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from model import Capabilities, Config, Cost, Mode, QueryResult, RunResult
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


class HybridIndexBuilder(IndexBuilder):
    """Builds a UNION index with BOTH dense (knn_vector) and sparse (rank_features) fields.

    Also creates a search pipeline with normalization + combination processors using
    the config's weights.
    """

    def __init__(self, client):
        self.client = client

    @contextmanager
    def build(self, config: Config, corpus: Corpus):
        """Create index with both vector and sparse fields, plus a search pipeline.

        Lifecycle:
            1. Create search pipeline with normalization-processor (min_max, arithmetic_mean, weights)
            2. Create index with knn_vector + rank_features fields
            3. Bulk-index corpus (both .vector and .text)
            4. Refresh
            5. Yield BuiltConfig
            6. On __exit__: delete index AND search pipeline

        The search pipeline is referenced at query time via ?search_pipeline=<id>.
        """
        params = config.as_dict()
        weights = params.get("weights", [0.5, 0.5])
        normalization = params.get("normalization", "min_max")
        combination = params.get("combination", "arithmetic_mean")
        model_id = params.get("model_id")

        # Generate unique names
        label_safe = config.label.replace(" ", "-").replace("_", "-")[:20]
        param_hash = hashlib.md5(str(config.params).encode()).hexdigest()[:8]
        index_name = f"rt-hybrid-{label_safe}-{param_hash}"
        pipeline_id = f"rt-hybrid-pipeline-{param_hash}"
        ingest_pipeline_id = f"rt-hybrid-ingest-{param_hash}"
        has_ingest = False

        try:
            # Create the hybrid search pipeline. The normalization-processor MUST
            # live under `phase_results_processors` (it operates between the query
            # and fetch phases); putting it in `response_processors` raises
            # "Invalid processor type normalization-processor" on a real cluster.
            pipeline_body = {
                "description": f"Hybrid search pipeline for {config.label}",
                "phase_results_processors": [
                    {
                        "normalization-processor": {
                            "normalization": {"technique": normalization},
                            "combination": {
                                "technique": combination,
                                "parameters": {"weights": weights},
                            },
                        }
                    }
                ],
            }
            self.client.put_search_pipeline(pipeline_id, pipeline_body)
            logger.info(
                "Created search pipeline %s (weights=%s, norm=%s, comb=%s)",
                pipeline_id, weights, normalization, combination,
            )

            # Ingest pipeline: encode text -> sparse_vector with the SPLADE model
            # so the neural_sparse sub-query has something to match. Without this
            # the sparse leg returns nothing on a real cluster.
            if model_id:
                try:
                    self.client.put_pipeline(
                        ingest_pipeline_id,
                        {"processors": [
                            {"sparse_encoding": {"model_id": model_id, "field_map": {"text": "sparse_vector"}}}
                        ]},
                    )
                    has_ingest = True
                except Exception as e:
                    logger.warning(f"sparse ingest pipeline unavailable for hybrid: {e}")

            # Create union index with both knn_vector and rank_features.
            # default_pipeline runs sparse_encoding on ingest to fill sparse_vector.
            index_settings: dict[str, Any] = {"knn": True, "number_of_shards": 1}
            if has_ingest:
                index_settings["default_pipeline"] = ingest_pipeline_id
            mapping = {
                "settings": {"index": index_settings},
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword"},
                        "text": {"type": "text"},
                        "vector": {
                            "type": "knn_vector",
                            "dimension": corpus.dim or 128,
                            "method": {
                                "name": "hnsw",
                                "space_type": "cosinesimil",
                                "engine": "lucene",
                                "parameters": {
                                    "m": 16,
                                    "ef_construction": 100,
                                },
                            },
                        },
                        "sparse_vector": {"type": "rank_features"},
                    }
                },
            }

            self.client.create_index(index_name, mapping)

            # Bulk-index corpus (both vector and text)
            docs_to_index = []
            for doc in corpus.documents:
                doc_dict: dict[str, Any] = {
                    "id": doc.id,
                }
                if doc.text:
                    doc_dict["text"] = doc.text
                if doc.vector:
                    doc_dict["vector"] = doc.vector
                # Sparse tokens if present (for test synthesis)
                if "sparse_tokens" in doc.fields:
                    doc_dict["sparse_vector"] = doc.fields["sparse_tokens"]

                docs_to_index.append(doc_dict)

            if docs_to_index:
                self.client.bulk(index_name, docs_to_index)
                self.client.refresh(index_name)
                logger.info(f"Indexed {len(docs_to_index)} documents into {index_name}")

            built = BuiltConfig(
                config=config,
                index_name=index_name,
                extra={"pipeline_id": pipeline_id, "dim": corpus.dim or 128},
            )
            yield built

        finally:
            # Guaranteed teardown: delete index AND search pipeline
            try:
                self.client.delete_index(index_name)
                logger.info(f"Tearing down hybrid index {index_name}")
            except Exception as e:
                logger.warning(f"Failed to delete index {index_name}: {e}")
            try:
                self.client.delete_search_pipeline(pipeline_id)
                logger.info(f"Tearing down search pipeline {pipeline_id}")
            except Exception as e:
                logger.warning(f"Failed to delete pipeline {pipeline_id}: {e}")
            if has_ingest:
                try:
                    self.client.delete_pipeline(ingest_pipeline_id)
                except Exception as e:
                    logger.warning(f"Failed to delete ingest pipeline {ingest_pipeline_id}: {e}")


# ============================= QueryRunner =============================


class HybridQueryRunner(QueryRunner):
    """Executes hybrid queries with two sub-queries (knn + neural_sparse) via search pipeline."""

    def __init__(self, client):
        self.client = client

    def run(self, built: BuiltConfig, queries: QuerySet) -> RunResult:
        """Issue hybrid queries with dense + sparse sub-queries, applying the search pipeline."""
        config = built.config
        index_name = built.index_name
        pipeline_id = built.extra.get("pipeline_id")
        k = config.get("k", 10)

        per_query: list[QueryResult] = []

        for query in queries:
            # Hybrid query structure: two sub-queries
            # 1. Dense: knn query on vector field
            # 2. Sparse: neural_sparse query on sparse_vector field
            sub_queries = []

            if query.vector:
                sub_queries.append({
                    "knn": {
                        "vector": {
                            "vector": query.vector,
                            "k": k,
                        }
                    }
                })

            if query.text:
                sparse_sub: dict[str, Any] = {"query_text": query.text}
                model_id = config.get("model_id")
                if model_id:
                    sparse_sub["model_id"] = model_id
                sub_queries.append({"neural_sparse": {"sparse_vector": sparse_sub}})

            if not sub_queries:
                logger.warning(f"Query {query.id} has neither vector nor text; skipping")
                continue

            body = {
                "size": k,
                "query": {
                    "hybrid": {
                        "queries": sub_queries,
                    }
                },
            }

            # Apply the search pipeline via query param
            params = {"search_pipeline": pipeline_id} if pipeline_id else {}
            resp = self.client.search(index_name, body, params=params or None)
            took_ms = float(resp.get("took", 0))

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

        return RunResult(config=config, per_query=per_query)


# ============================= CostProbe =============================


class HybridCostProbe(CostProbe):
    """Measures the union index size (dense graph + sparse inverted-index).

    Hybrid cost = latency overhead (captured in RunResult) + footprint.
    For footprint, we report the union index size from cat_indices. Alternatively,
    we could return Cost() with None to indicate no separate footprint metric
    (Pareto handles missing footprint gracefully).
    """

    def __init__(self, client):
        self.client = client

    def measure(self, built: BuiltConfig) -> Cost:
        """Read store.size from cat_indices for the union index."""
        index_name = built.index_name
        try:
            indices = self.client.cat_indices(index_name)
            if not indices:
                return Cost(index_size_bytes=None)

            # Parse store.size
            size_str = indices[0].get("store.size", "0b")
            size_bytes = _parse_size_to_bytes(size_str)
            return Cost(index_size_bytes=size_bytes)
        except Exception as e:
            logger.warning(f"Could not measure cost for {index_name}: {e}")
            return Cost(index_size_bytes=None)


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


# ============================= ReferenceProvider =============================


class HybridReferenceProvider(ReferenceProvider):
    """Reference = BEST STANDALONE ranking (dense-only or sparse-only, per query).

    Hybrid quality is graded on NDCG lift vs the best single signal. We build
    temporary dense-only and sparse-only indices, query both, and per query pick
    the one that scores better against qrels (if present) or default to dense-only.

    UNIQUE index names + close() teardown to avoid leaks (per code review lesson).
    """

    kind = "best-standalone"

    def __init__(self, client, corpus: Corpus, qrels):
        self.client = client
        self.corpus = corpus
        self.qrels = qrels
        self._dense_index: str | None = None
        self._sparse_index: str | None = None
        self._reference_cache: dict[str, list[str]] | None = None

    def close(self) -> None:
        """Tear down temporary dense and sparse indices. Idempotent; safe on error."""
        if self._dense_index:
            try:
                self.client.delete_index(self._dense_index)
                logger.info(f"Tearing down reference dense index {self._dense_index}")
            except Exception as e:
                logger.warning(f"Dense reference teardown had issues: {e}")
            finally:
                self._dense_index = None

        if self._sparse_index:
            try:
                self.client.delete_index(self._sparse_index)
                logger.info(f"Tearing down reference sparse index {self._sparse_index}")
            except Exception as e:
                logger.warning(f"Sparse reference teardown had issues: {e}")
            finally:
                self._sparse_index = None

    def reference_ranking(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        """Per query, return the best-standalone top-k (dense or sparse, whichever is better).

        If qrels are present, we score both against qrels and pick the better one per query.
        Otherwise, default to dense-only.
        """
        if self._reference_cache is not None:
            return {qid: docs[:k] for qid, docs in self._reference_cache.items()}

        logger.info("Building best-standalone reference for hybrid (dense + sparse)...")

        # Build and query dense-only
        dense_rankings = self._query_dense_standalone(queries, k)

        # Build and query sparse-only
        sparse_rankings = self._query_sparse_standalone(queries, k)

        # Per query, pick the better ranking
        best_rankings = {}
        for query in queries:
            qid = query.id
            dense_docs = dense_rankings.get(qid, [])
            sparse_docs = sparse_rankings.get(qid, [])

            if self.qrels and qid in self.qrels:
                # Score both against qrels using NDCG-like relevance
                dense_score = self._score_ranking(dense_docs, self.qrels[qid])
                sparse_score = self._score_ranking(sparse_docs, self.qrels[qid])
                best_rankings[qid] = dense_docs if dense_score >= sparse_score else sparse_docs
            else:
                # Default to dense-only
                best_rankings[qid] = dense_docs

        self._reference_cache = best_rankings
        return {qid: docs[:k] for qid, docs in best_rankings.items()}

    def _query_dense_standalone(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        """Build and query a dense-only index (script_score cosine)."""
        if self._dense_index is None:
            suffix = hashlib.sha1(f"dense-{id(self)}".encode()).hexdigest()[:8]
            self._dense_index = f"rt-hybrid-ref-dense-{suffix}"

            # knn_vector (lucene engine) is required for the knn_score exact
            # scoring script; a plain float array raises class_cast_exception,
            # and the faiss engine crashes the node without its native lib.
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
            self.client.delete_index(self._dense_index)
            self.client.create_index(self._dense_index, mapping)

            docs = []
            for doc in self.corpus.documents:
                if doc.vector:
                    docs.append({"id": doc.id, "vector": doc.vector})
            if docs:
                self.client.bulk(self._dense_index, docs)
                self.client.refresh(self._dense_index)

        # Query via script_score (exact)
        rankings = {}
        for query in queries:
            if not query.vector:
                continue
            body = {
                "size": k,
                "query": {
                    "script_score": {
                        "query": {"match_all": {}},
                        "script": {
                            # k-NN exact-scoring script (see dense_knn.py) — the
                            # cosineSimilarity(...'field') form fails to compile.
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
            resp = self.client.search(self._dense_index, body)
            hits = resp.get("hits", {}).get("hits", [])
            rankings[query.id] = [h["_id"] for h in hits]

        return rankings

    def _query_sparse_standalone(self, queries: QuerySet, k: int) -> dict[str, list[str]]:
        """Build and query a sparse-only index (lexical match)."""
        if self._sparse_index is None:
            suffix = hashlib.sha1(f"sparse-{id(self)}".encode()).hexdigest()[:8]
            self._sparse_index = f"rt-hybrid-ref-sparse-{suffix}"

            mapping = {
                "mappings": {
                    "properties": {
                        "id": {"type": "keyword"},
                        "text": {"type": "text"},
                    }
                }
            }
            self.client.delete_index(self._sparse_index)
            self.client.create_index(self._sparse_index, mapping)

            docs = []
            for doc in self.corpus.documents:
                if doc.text:
                    docs.append({"id": doc.id, "text": doc.text})
            if docs:
                self.client.bulk(self._sparse_index, docs)
                self.client.refresh(self._sparse_index)

        # Query via match (lexical)
        rankings = {}
        for query in queries:
            if not query.text:
                continue
            body = {
                "size": k,
                "query": {
                    "match": {
                        "text": query.text,
                    }
                },
            }
            resp = self.client.search(self._sparse_index, body)
            hits = resp.get("hits", {}).get("hits", [])
            rankings[query.id] = [h["_id"] for h in hits]

        return rankings

    def _score_ranking(self, doc_ids: list[str], qrels_for_query: dict[str, int]) -> float:
        """Simple NDCG-like scoring: sum of graded relevance with position discount."""
        score = 0.0
        for i, doc_id in enumerate(doc_ids):
            rel = qrels_for_query.get(doc_id, 0)
            if rel > 0:
                # Position discount: 1 / log2(i+2) (standard DCG)
                import math
                score += rel / math.log2(i + 2)
        return score


# ============================= ConfigGenerator =============================


class HybridConfigGenerator(ConfigGenerator):
    """Generates hybrid configs: FIX normalization + combination, SWEEP weights only.

    Per DESIGN §7 and §8 v1 scope:
    - normalization = min_max (FIXED)
    - combination = arithmetic_mean (FIXED)
    - weights: sweep [0.1:0.9, 0.3:0.7, 0.5:0.5, 0.7:0.3, 0.9:0.1] (5 configs)

    DO NOT emit forbidden params (§10.3): sub_query_raw_scores, WAND, dynamic_normalization.
    """

    mode = Mode.HYBRID

    def seed_configs(self, cap: Capabilities, corpus: Corpus) -> list[Config]:
        """Generate initial sweep: fixed min_max + arithmetic_mean, sweep weights."""
        configs: list[Config] = []

        # Fixed parameters (v1 scope)
        normalization = "min_max"
        combination = "arithmetic_mean"

        # The sparse leg needs a deployed model to encode text at ingest/query.
        # is_available guarantees one exists; thread it through every config.
        model_id = cap.sparse_models[0] if cap.sparse_models else None

        # Weight ratios to sweep: dense:sparse
        weight_pairs = [
            (0.1, 0.9),
            (0.3, 0.7),
            (0.5, 0.5),
            (0.7, 0.3),
            (0.9, 0.1),
        ]

        for w_dense, w_sparse in weight_pairs:
            params = {
                "weights": [w_dense, w_sparse],
                "normalization": normalization,
                "combination": combination,
                "model_id": model_id,
                "k": 10,
            }
            label = f"w{int(w_dense*10)}d-{int(w_sparse*10)}s-{normalization}-{combination}"
            configs.append(Config.make(self.mode, label, params))

        return configs

    def refine(
        self,
        measured,
        quality_floor: float,
        latency_budget_ms: float | None,
    ) -> list[Config]:
        """No adaptive refinement in v1; seed_configs covers the weight sweep."""
        return []


# ============================= ModePlugin =============================


class HybridPlugin(ModePlugin):
    """Hybrid search mode plugin (v1: weights-only sweep at fixed normalization/combination)."""

    mode = Mode.HYBRID

    def is_available(self, cap: Capabilities) -> bool:
        """Hybrid needs the dense sub-query (dense_knn), the hybrid pipeline
        processors (hybrid), AND a deployed sparse model for the sparse
        sub-query. The sparse-model requirement is essential graceful
        degradation: without a model the sparse leg 404s ("Fail to find
        model"), so we skip hybrid entirely rather than fail — verified on a
        real cluster that had the plugins but no model deployed.
        """
        return cap.hybrid and cap.dense_knn and bool(cap.sparse_models)

    def index_builder(self, client) -> IndexBuilder:
        return HybridIndexBuilder(client)

    def query_runner(self, client) -> QueryRunner:
        return HybridQueryRunner(client)

    def cost_probe(self, client) -> CostProbe:
        return HybridCostProbe(client)

    def reference_provider(self, client, corpus: Corpus, qrels) -> ReferenceProvider:
        return HybridReferenceProvider(client, corpus, qrels)

    def config_generator(self) -> ConfigGenerator:
        return HybridConfigGenerator()
