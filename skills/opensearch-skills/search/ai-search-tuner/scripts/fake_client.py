"""In-memory FakeOSClient implementing the OSClient protocol.

Lets the whole suite run with zero real cluster. It is intentionally *not* a
full OpenSearch — it implements just enough behavior that harness + mode logic
can be exercised deterministically:

- capability probing returns configurable canned responses
- create/delete index and bulk store docs in a dict
- search supports two shapes we actually use in tests:
    * exact dense k-NN via brute-force cosine over stored vectors (script_score
      style) — this is the recall ground truth path
    * an "approximate" dense path that deterministically drops a fraction of
      the true neighbors, so recall < 1.0 can be asserted
- footprint stats are synthesized from stored data + config

Determinism: no randomness, no wall-clock. Latency values are derived from
config so percentile math can be asserted exactly.
"""

from __future__ import annotations

import math
from typing import Any


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class FakeOSClient:
    """Deterministic in-memory stand-in for an OpenSearch cluster."""

    def __init__(
        self,
        *,
        version: str = "2.17.1",
        plugins: list[str] | None = None,
        ml_model_ids: list[str] | None = None,
    ):
        self._version = version
        self._plugins = plugins if plugins is not None else [
            "opensearch-knn", "opensearch-neural-search", "opensearch-ml",
        ]
        self._ml_model_ids = ml_model_ids if ml_model_ids is not None else ["sparse-doc-v3"]
        self.indices: dict[str, dict[str, Any]] = {}  # index -> {"docs": {id: doc}, "body": {...}}
        self.search_pipelines: dict[str, dict] = {}
        self.ingest_pipelines: dict[str, dict] = {}
        # Test hook: fraction of true neighbors an "approximate" search misses.
        # When >0 it is used directly (explicit, deterministic tests).
        self.approx_miss_fraction: float = 0.0
        # Demo hook: when True (and approx_miss_fraction==0), derive the miss
        # fraction from the query's ef_search + encoder so `--offline` reproduces
        # the #21 silent-recall-drop story. Off by default so tests are unaffected.
        self.model_recall_from_params: bool = False

    # --- probing ---
    def info(self) -> dict[str, Any]:
        return {"version": {"number": self._version}}

    def cat_plugins(self) -> list[dict[str, Any]]:
        return [{"component": p} for p in self._plugins]

    def cluster_stats(self) -> dict[str, Any]:
        # Synthesize a plausible graph-memory number from stored vectors.
        total_vecs = sum(
            sum(1 for d in ix["docs"].values() if d.get("vector"))
            for ix in self.indices.values()
        )
        return {"nodes": {"count": {"total": 1}}, "_synthetic_vectors": total_vecs}

    def knn_stats(self) -> dict[str, Any]:
        return {"nodes": {}}

    def cat_indices(self, index: str) -> list[dict[str, Any]]:
        out = []
        for name, ix in self.indices.items():
            if _match(index, name):
                # store.size ~ bytes; synthesize from doc count + a per-config factor
                size = int(ix.get("_size_bytes", len(ix["docs"]) * 1024))
                out.append({"index": name, "store.size": str(size), "docs.count": str(len(ix["docs"]))})
        return out

    def ml_models(self) -> list[dict[str, Any]]:
        return [
            {"model_id": m, "name": m, "model_state": "DEPLOYED", "algorithm": "SPARSE_ENCODING"}
            for m in self._ml_model_ids
        ]

    def get_model_state(self, model_id: str) -> str | None:
        return "DEPLOYED" if model_id in self._ml_model_ids else None

    # --- lifecycle ---
    def create_index(self, index: str, body: dict[str, Any]) -> dict[str, Any]:
        # Store the mapping body so the recall model can read the index's encoder
        # at query time (see _miss_fraction_for).
        self.indices[index] = {"docs": {}, "body": body}
        return {"acknowledged": True}

    def delete_index(self, index: str) -> dict[str, Any]:
        self.indices.pop(index, None)
        return {"acknowledged": True}

    def bulk(self, index: str, docs: list[dict[str, Any]]) -> dict[str, Any]:
        store = self.indices.setdefault(index, {"docs": {}, "body": {}})["docs"]
        for d in docs:
            store[str(d.get("id"))] = d
        return {"errors": False, "items": []}

    def refresh(self, index: str) -> dict[str, Any]:
        return {"_shards": {"successful": 1}}

    def put_pipeline(self, pipeline_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.ingest_pipelines[pipeline_id] = body
        return {"acknowledged": True}

    def delete_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        self.ingest_pipelines.pop(pipeline_id, None)
        return {"acknowledged": True}

    def put_search_pipeline(self, pipeline_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.search_pipelines[pipeline_id] = body
        return {"acknowledged": True}

    def delete_search_pipeline(self, pipeline_id: str) -> dict[str, Any]:
        self.search_pipelines.pop(pipeline_id, None)
        return {"acknowledged": True}

    # --- search ---
    def search(self, index: str, body: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        ix = self.indices.get(index)
        if ix is None:
            return {"hits": {"hits": []}, "took": 0}
        size = int(body.get("size", 10))
        docs = ix["docs"]

        # Check for hybrid query first (has a search_pipeline param)
        pipeline_id = (params or {}).get("search_pipeline")
        if pipeline_id and _is_hybrid_query(body):
            return self._search_hybrid(index, body, size, pipeline_id, docs)

        qvec = _extract_query_vector(body)
        approximate = _is_approximate_knn(body)

        if qvec is not None:
            scored = sorted(
                (
                    (cosine(qvec, d["vector"]), did)
                    for did, d in docs.items()
                    if d.get("vector")
                ),
                key=lambda t: t[0],
                reverse=True,
            )
            if approximate:
                miss = self._miss_fraction_for(body, ix)
                if miss > 0:
                    scored = self._drop_neighbors(scored, size, miss)
            top = scored[:size]
        else:
            # Text path: trivial lexical overlap score (deterministic).
            qtext = _extract_query_text(body).lower().split()
            scored = sorted(
                (
                    (float(sum(t in (d.get("text") or "").lower() for t in qtext)), did)
                    for did, d in docs.items()
                ),
                key=lambda t: t[0],
                reverse=True,
            )
            # Sparse ANN (SEISMIC) path: a neural_sparse query carrying
            # method_parameters (heap_factor) is APPROXIMATE — it visits only the
            # most promising clusters, so it misses some of the exact top hits.
            # We deterministically drop a fraction of the true ranking that
            # SHRINKS as heap_factor grows (heap_factor is the ef_search analog),
            # reproducing the recall-vs-exact story. A plain rank_features query
            # (no method_parameters) is exact and never enters this branch.
            if _is_approximate_sparse(body):
                miss = self._sparse_miss_fraction_for(body)
                if miss > 0:
                    # Evict from a canonical top-k window (not the raw request
                    # size, which the sparse runner fixes at 100 — larger than a
                    # small test corpus, so nothing would ever drop).
                    scored = _evict_from_window(scored, window=10, miss_fraction=miss)
            top = scored[:size]

        hits = [{"_id": did, "_score": sc} for sc, did in top]
        return {"took": _sparse_took_ms(body), "hits": {"hits": hits}}

    def _search_hybrid(
        self, index: str, body: dict, size: int, pipeline_id: str, docs: dict
    ) -> dict[str, Any]:
        """Execute a hybrid query: combine dense + sparse with normalization + weights.

        This implements min_max normalization + arithmetic_mean combination using
        the weights from the search pipeline. Designed so a mid-weight (e.g. 0.5:0.5
        or 0.6:0.4) yields HIGHER NDCG than either standalone for well-crafted test
        corpora (the "lift" story from DESIGN §6).
        """
        pipeline = self.search_pipelines.get(pipeline_id, {})
        # Extract weights from the pipeline processors
        weights = self._extract_weights_from_pipeline(pipeline)
        w_dense, w_sparse = weights

        # Extract the two sub-queries from the hybrid query
        q = body.get("query", {})
        hybrid_node = q.get("hybrid", {})
        sub_queries = hybrid_node.get("queries", [])

        # Separate dense (knn) and sparse (neural_sparse or match) sub-queries
        dense_scores: dict[str, float] = {}
        sparse_scores: dict[str, float] = {}

        for sub_q in sub_queries:
            if "knn" in sub_q:
                # Dense path: cosine similarity
                qvec = _extract_query_vector({"query": sub_q})
                if qvec:
                    for did, d in docs.items():
                        if d.get("vector"):
                            dense_scores[did] = cosine(qvec, d["vector"])
            elif "neural_sparse" in sub_q or "match" in sub_q:
                # Sparse path: lexical overlap
                qtext = _extract_query_text({"query": sub_q}).lower().split()
                for did, d in docs.items():
                    text = (d.get("text") or "").lower()
                    sparse_scores[did] = float(sum(t in text for t in qtext))

        # Min-max normalization for each signal
        def normalize_min_max(scores: dict[str, float]) -> dict[str, float]:
            if not scores:
                return {}
            vals = list(scores.values())
            min_s, max_s = min(vals), max(vals)
            if max_s == min_s:
                return {k: 1.0 for k in scores}
            return {k: (v - min_s) / (max_s - min_s) for k, v in scores.items()}

        dense_norm = normalize_min_max(dense_scores)
        sparse_norm = normalize_min_max(sparse_scores)

        # Arithmetic mean combination with weights
        all_docs = set(dense_norm.keys()) | set(sparse_norm.keys())
        combined = {}
        for did in all_docs:
            d_score = dense_norm.get(did, 0.0)
            s_score = sparse_norm.get(did, 0.0)
            # If a doc is missing from one signal, treat as 0 (as OpenSearch does)
            combined[did] = w_dense * d_score + w_sparse * s_score

        # Sort and take top-k
        ranked = sorted(combined.items(), key=lambda kv: kv[1], reverse=True)[:size]
        hits = [{"_id": did, "_score": score} for did, score in ranked]

        # Latency: slightly higher than standalone (model the 6-8% overhead)
        base_took = 1
        hybrid_took = int(base_took * 1.07)

        return {"took": hybrid_took, "hits": {"hits": hits}}

    def _extract_weights_from_pipeline(self, pipeline: dict) -> tuple[float, float]:
        """Extract dense and sparse weights from the search pipeline definition."""
        # Real OpenSearch puts the normalization-processor under
        # `phase_results_processors`; accept the legacy `response_processors`
        # location too so older fixtures keep working.
        processors = (
            pipeline.get("phase_results_processors")
            or pipeline.get("response_processors", [])
        )
        for proc in processors:
            if "normalization-processor" in proc:
                norm = proc["normalization-processor"]
                combo = norm.get("combination", {})
                # OpenSearch puts weights under combination.parameters.weights;
                # accept the flatter combination.weights too for robustness.
                weights = combo.get("parameters", {}).get("weights")
                if not weights:
                    weights = combo.get("weights")
                if weights and len(weights) >= 2:
                    return (float(weights[0]), float(weights[1]))
        # Default: equal weights
        return (0.5, 0.5)

    def _miss_fraction_for(self, body: dict, ix: dict) -> float:
        """Decide how many true neighbors an approximate query misses.

        Two modes:
        - If `approx_miss_fraction` is set (>0), use it directly. This keeps
          existing tests deterministic and explicit.
        - Else, if `model_recall_from_params` is enabled, DERIVE a miss fraction
          from the query's ef_search and the QUERIED INDEX'S encoder so the
          offline demo reproduces the real #21 story: low ef_search and
          aggressive quantization lose recall. Purely deterministic (no RNG).
        """
        if self.approx_miss_fraction > 0:
            return self.approx_miss_fraction
        if not self.model_recall_from_params:
            return 0.0
        ef = _extract_ef_search(body) or 100
        # Recall rises with ef_search and saturates. ef=50→~0.20 miss,
        # 100→~0.10, 200→~0.05, 400→~0.02.
        ef_miss = min(0.5, 10.0 / float(ef))
        # Encoder of the specific index being queried (not a global hint).
        enc = (_extract_encoder(ix.get("body") or {}) or "fp32").lower()
        enc_penalty = {"fp32": 0.0, "fp16": 0.03, "pq": 0.12, "binary": 0.18}.get(enc, 0.05)
        return min(0.9, ef_miss + enc_penalty)

    def _sparse_miss_fraction_for(self, body: dict) -> float:
        """Fraction of the exact sparse top-k a SEISMIC query misses.

        Deterministic function of two query-time knobs, no RNG / wall-clock:
        - heap_factor (the ef_search analog): recall rises with it and saturates.
          hf=0.5 → ~0.20 miss, 1.0 → ~0.10, 1.5 → ~0.067, 2.0 → ~0.05.
        - top_n (query tokens retained): dropping below the recommended 10 retains
          fewer terms ⇒ fewer posting lists visited ⇒ a small extra miss. top_n≥10
          adds nothing; each token below 10 adds ~1% miss (top_n=5 → +0.05).
        Keyed on the query shape so it mirrors how both knobs really trade recall
        for speed, and needs no opt-in for the offline demo.
        """
        hf = _extract_heap_factor(body) or 1.0
        hf_miss = 0.5 if hf <= 0 else min(0.5, 0.1 / float(hf))
        top_n = _extract_top_n(body)
        top_n_miss = 0.0 if top_n is None else max(0, 10 - int(top_n)) * 0.01
        return min(0.6, hf_miss + top_n_miss)

    def _drop_neighbors(self, scored, size, miss_fraction: float | None = None):
        """Deterministically remove a fraction of the TRUE top neighbors so the
        approximate result recall is < 1.0 and computable in tests."""
        frac = self.approx_miss_fraction if miss_fraction is None else miss_fraction
        # Clamp the window to what's actually available so a small corpus
        # (size > len(scored)) can't make the slices below overlap/duplicate.
        window = min(size, len(scored))
        n_drop = int(round(window * frac))
        if n_drop <= 0:
            return scored
        keep = scored[:window]
        tail = scored[window:]
        # Drop the last n_drop of the true top-window; backfill from the tail
        # only as far as it actually goes (may be empty for a short corpus).
        survivors = keep[: window - n_drop]
        backfill = tail[:n_drop]
        return survivors + backfill + keep[window - n_drop:]


def _match(pattern: str, name: str) -> bool:
    if pattern in ("", "*", "_all"):
        return True
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return pattern == name


def _extract_query_vector(body: dict) -> list[float] | None:
    q = body.get("query", {})
    knn = q.get("knn")
    if isinstance(knn, dict):
        for _field, spec in knn.items():
            if isinstance(spec, dict) and "vector" in spec:
                return spec["vector"]
    ss = q.get("script_score")
    if isinstance(ss, dict):
        params = ss.get("script", {}).get("params", {})
        if "query_value" in params:
            return params["query_value"]
        if "queryVector" in params:
            return params["queryVector"]
    return None


def _is_approximate_knn(body: dict) -> bool:
    q = body.get("query", {})
    return "knn" in q  # script_score = exact; knn query = approximate


def _is_hybrid_query(body: dict) -> bool:
    """Check if the query is a hybrid query (has a 'hybrid' node with sub-queries)."""
    q = body.get("query", {})
    return "hybrid" in q


def _neural_sparse_inner(body: dict) -> dict | None:
    """Return the inner spec of a neural_sparse query (e.g. the sparse_vector
    block holding query_text / method_parameters), or None if not one."""
    ns = body.get("query", {}).get("neural_sparse")
    if isinstance(ns, dict):
        for _field, spec in ns.items():
            if isinstance(spec, dict):
                return spec
    return None


def _is_approximate_sparse(body: dict) -> bool:
    """A neural_sparse query is APPROXIMATE (SEISMIC) iff it carries
    method_parameters (heap_factor / top_n). A plain rank_features query has none
    and is exact — the recall ground truth."""
    inner = _neural_sparse_inner(body)
    return bool(inner and inner.get("method_parameters"))


def _extract_heap_factor(body: dict) -> float | None:
    """Pull method_parameters.heap_factor out of a neural_sparse query, if present."""
    inner = _neural_sparse_inner(body)
    if inner:
        mp = inner.get("method_parameters") or {}
        if "heap_factor" in mp:
            try:
                return float(mp["heap_factor"])
            except (TypeError, ValueError):
                return None
    return None


def _extract_top_n(body: dict) -> int | None:
    """Pull method_parameters.top_n out of a neural_sparse query, if present."""
    inner = _neural_sparse_inner(body)
    if inner:
        mp = inner.get("method_parameters") or {}
        if "top_n" in mp:
            try:
                return int(mp["top_n"])
            except (TypeError, ValueError):
                return None
    return None


def _sparse_took_ms(body: dict) -> int:
    """Deterministic synthetic latency (ms) for a search.

    Only SEISMIC queries (with method_parameters) get a modeled cost; everything
    else returns the baseline 1ms so unrelated paths/tests are unaffected. SEISMIC
    latency grows with BOTH query-time knobs — heap_factor (more clusters visited)
    and top_n (more posting lists traversed) — so lowering top_n once recall is met
    is a visible latency win (the refine story). No RNG / wall-clock.
    """
    if not _is_approximate_sparse(body):
        return 1
    hf = _extract_heap_factor(body) or 1.0
    top_n = _extract_top_n(body)
    top_n = 10 if top_n is None else int(top_n)
    # base 10ms + ~10ms per heap_factor unit + ~1ms per retained query token.
    return int(round(10 + 10 * float(hf) + 1.0 * top_n))


def _evict_from_window(scored, window: int, miss_fraction: float):
    """Deterministically evict a fraction of the TRUE top-`window` neighbors so
    approximate recall is < 1.0 and exactly computable in tests.

    Standalone (module-level) twin of FakeOSClient._drop_neighbors used by the
    sparse-ANN path. It operates on a fixed top-k WINDOW rather than the raw
    request size (the sparse runner fixes size=100, which is larger than a small
    test corpus — so window-based eviction is what actually models recall loss).
    The evicted true neighbors are pushed below the window and backfilled from
    the tail, so recall@k for k ≤ window drops by exactly n_drop/window.
    """
    n = min(window, len(scored))
    n_drop = int(round(n * miss_fraction))
    if n_drop <= 0:
        return scored
    keep = scored[:n]
    tail = scored[n:]
    survivors = keep[: n - n_drop]
    backfill = tail[:n_drop]
    # Dropped true neighbors go after the backfill (below the window).
    return survivors + backfill + keep[n - n_drop:] + tail[n_drop:]


def _extract_ef_search(body: dict) -> int | None:
    q = body.get("query", {})
    knn = q.get("knn")
    if isinstance(knn, dict):
        for _field, spec in knn.items():
            if isinstance(spec, dict):
                mp = spec.get("method_parameters") or {}
                if "ef_search" in mp:
                    return int(mp["ef_search"])
    return None


def _extract_encoder(body: dict) -> str | None:
    """Pull the abstract encoder name out of a knn_vector mapping, if present.

    dense_knn.py encodes quantization the real-OpenSearch (Lucene) way:
    encoder {name: "sq", parameters: {bits: 7|1}}. Map that BACK to the abstract
    names the recall model understands (bits 7 → fp16, 1 → binary), so the
    offline #21 demo story still works after the sq/bits mapping change.
    """
    props = (body.get("mappings") or {}).get("properties") or {}
    for _name, spec in props.items():
        if isinstance(spec, dict) and spec.get("type") == "knn_vector":
            method = spec.get("method") or {}
            enc = (method.get("parameters") or {}).get("encoder") or {}
            if isinstance(enc, dict) and enc.get("name"):
                name = str(enc["name"]).lower()
                if name == "sq":
                    bits = (enc.get("parameters") or {}).get("bits")
                    return {7: "fp16", 1: "binary"}.get(bits, "fp16")
                return name
            return "fp32"  # knn_vector without explicit encoder = fp32
    return None


def _extract_query_text(body: dict) -> str:
    q = body.get("query", {})
    for key in ("match", "neural_sparse", "match_all"):
        node = q.get(key)
        if isinstance(node, dict):
            for _f, spec in node.items():
                if isinstance(spec, dict):
                    return str(spec.get("query", spec.get("query_text", "")))
                if isinstance(spec, str):
                    return spec
    return ""
