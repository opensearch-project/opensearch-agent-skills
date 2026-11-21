# Tunable Parameters Reference

This document lists **verified tunable parameters** for each retrieval mode,
cross-referenced against official OpenSearch documentation and source. Only
parameters that are stable, user-facing, and confirmed in docs/issues/source are
included. Version-gated features are noted.

**DO NOT TUNE** (unverified) parameters are listed at the end — these are
explicitly excluded from the sweep.

---

## Mode A: Dense k-NN (approximate, HNSW)

HNSW graph-based approximate nearest-neighbor search over dense embeddings.

### Tunable parameters

| Parameter | Type | Controls | Range / values | Tradeoff | Verified in |
|---|---|---|---|---|---|
| `m` | int | HNSW graph connectivity (max edges per node) | Typical: 16, 32, 48 (default 16) | Higher → recall↑, memory↑, build slower | [OpenSearch k-NN docs](https://opensearch.org/docs/latest/search-plugins/knn/knn-index/#method-definitions), [Lucene HNSW](https://lucene.apache.org/core/9_0_0/core/org/apache/lucene/util/hnsw/HnswGraph.html) |
| `ef_construction` | int | Build-time search breadth (candidate list size during construction) | Typical: 100, 200, 512 (default 100) | Higher → recall↑, build time↑↑ | k-NN docs |
| `ef_search` | int | Query-time search breadth (candidate list size during search) | Typical: 50, 100, 200, 400 (default 100) | Higher → recall↑, latency↑ (cheapest recall dial) | k-NN docs |
| `method.encoder` / quantization | string | Vector precision / compression | `"fp32"` (default), `"fp16"` (2.13+), `"pq"`, `"sq"`, `"binary"` (distro/engine-dependent) | Lower precision → memory↓↓, recall risk | [OpenSearch quantization docs](https://opensearch.org/docs/latest/search-plugins/knn/approximate-knn/#quantization-for-knn), issue [k-NN #21](https://github.com/opensearch-project/k-NN/issues/21) (silent recall drop 0.91→0.79 on quantization toggle) |

**Quality reference:** FP32 exact brute-force (`script_score` cosine) or labeled
qrels.

**Metric:** **Recall@k** vs exact (primary); NDCG@k / MAP@k (if qrels, secondary).

**Cost axis:** HNSW graph memory ≈ `m × N × {4..16} bytes` (4 for FP32, 2 for
FP16, variable for PQ/sq/binary), probed via `_cluster/stats` /
`_plugins/_knn/stats`.

### Tuning strategy (agentic pruning)

1. Fix `m` and `ef_construction` at defaults (or prior known-good).
2. Sweep `ef_search` first (query-time, cheapest recall dial): [50, 100, 200, 400].
3. If recall floor is unmet at `ef_search=400`, escalate to higher `m` or
   `ef_construction` (build-time, more expensive).
4. Once a config meets the recall floor, sweep quantization (FP32 → FP16 → PQ)
   to find the memory-optimal point on the Pareto frontier.

---

## Mode B1: Neural Sparse, traditional rank_features (EXACT, 2.11+)

Exact Lucene scoring over learned sparse token weights. **No HNSW-style
approximation; recall vs itself is trivially 1.0.**

### Tunable parameters

| Parameter | Type | Controls | Range / default | Tradeoff | Since | Verified in |
|---|---|---|---|---|---|---|
| `model_id` (ingest pipeline) | string | Sparse encoding model | `"opensearch-neural-sparse-encoding-doc-v3-distill"` (doc-only), `"...-v2-distill"` (bi-encoder) | Doc-only: faster ingest/query, slight relevance loss vs bi-encoder | 2.11 | [Neural search docs](https://opensearch.org/docs/latest/search-plugins/neural-sparse-search/), issue [#988 prune PR](https://github.com/opensearch-project/neural-search/pull/988) |
| `analyzer` (query, doc-only) | string | Query tokenization via lookup (for doc-only models only) | `"bert-uncased"`, `"mbert-uncased"` | Fast (no bi-encoder inference at query time); slight relevance loss vs bi-encoder | 2.11 | Neural search docs |
| `prune_type` (ingest) | string | Token-pruning strategy | `"max_ratio"`, `"abs_value"`, `"alpha_mass"`, `"top_k"`, `"none"` (default none) | Shrinks index; slight relevance loss | 2.19 | Issue [#988](https://github.com/opensearch-project/neural-search/pull/988) |
| `prune_ratio` (ingest) | float | Threshold for `prune_type` (when `prune_type="max_ratio"`) | [0.0, 1.0), typical 0.1 | Lower → smaller/faster index, slight relevance loss (~40% index shrink at 0.1, <1% NDCG loss) | 2.19 | #988, issue [#946 index bloat](https://github.com/opensearch-project/neural-search/issues/946) (sparse indexes 4.7–6.8× BM25) |
| `two_phase_parameter.enabled` | bool | Two-phase scoring acceleration | `true` (default), `false` | When `true`: doc-only ~28% / bi-encoder ~60% latency cut, **no relevance loss** (NOT for `sparse_vector` ANN) | 2.15 | [Two-phase processor docs](https://opensearch.org/docs/latest/search-plugins/neural-sparse-two-phase/), issue [#646 two-phase confusion](https://github.com/opensearch-project/neural-search/issues/646) |
| `two_phase_parameter.prune_type` | string | High/low-weight token split strategy | `"max_ratio"` (default), `"alpha_mass"`, `"top_k"`, `"abs_value"` | Phase-1 cost vs phase-2 coverage | 2.15 | Two-phase docs |
| `two_phase_parameter.prune_ratio` | float | Split threshold (for `prune_type="max_ratio"`) | [0.0, 1.0], default 0.4 | Lower → faster phase 1 (fewer high-weight tokens) | 2.15 | Two-phase docs |
| `two_phase_parameter.expansion_rate` | float | Phase-1 doc count = `size × expansion_rate` | >1.0, default 5.0 | Higher → recall↑ latency↑ (typically 5.0 is zero-loss) | 2.15 | Two-phase docs |
| `two_phase_parameter.max_window_size` | int | Max docs eligible for two-phase | >50, default 10000 | Higher → wider applicability, more memory | 2.15 | Two-phase docs |

**Quality reference:** Labeled qrels (gold standard) or un-pruned bi-encoder
baseline (proxy).

**Metric:** **NDCG@k / MAP@k** (primary, vs judgments or baseline); pruning and
two-phase graded on **relevance-preservation vs cost** (two-phase should show
*zero* relevance loss — latency gain only).

**Cost axis:** Inverted-index / segment size in bytes, probed via
`_cat/indices?format=json&bytes=b` (`store.size`).

### Tuning strategy (agentic pruning)

1. Enable `two_phase_parameter.enabled=true` by default (free latency win, no
   relevance loss). Use default `expansion_rate=5.0`.
2. Sweep `prune_ratio` for `prune_type="max_ratio"`: [0.0, 0.1, 0.2, 0.3].
3. Plot NDCG@10 vs index-size Pareto.
4. Recommend the knee: typically `prune_ratio=0.1` (−40% index size, <1% NDCG
   loss).
5. If bi-encoder is too slow for the corpus size, fall back to doc-only model
   with `analyzer="bert-uncased"`.

---

## Mode B2: Neural Sparse ANN, sparse_vector / SEISMIC (approximate, 3.3+)

SEISMIC cluster-based approximate scoring over sparse vectors. **Approximate**
(unlike rank_features); ground truth is exact `rank_features` on same tokens.

### Tunable parameters

| Parameter | Type | Controls | Range / default | Since | Verified in |
|---|---|---|---|---|---|
| Field type | string | Exact vs approximate | `"rank_features"` (exact) vs `"sparse_vector"` (SEISMIC ANN) | 3.3 | [Sparse ANN docs](https://opensearch.org/docs/latest/field-types/supported-field-types/sparse/) |
| `n_postings` | float | Max docs per posting list (as fraction of segment doc count) | Default 0.0005 × seg doc count | 3.3 | Sparse ANN docs |
| `cluster_ratio` | float | Cluster granularity | (0, 1), default 0.1 | 3.3 | Sparse ANN docs |
| `summary_prune_ratio` | float | Cluster-summary weight retained | (0, 1], default 0.4 | 3.3 | Sparse ANN docs |
| `approximate_threshold` | int | Min segment docs to activate ANN | int, default 1,000,000 | 3.3 | Sparse ANN docs |
| `quantization_ceiling_ingest` | float | Weight → uint8 scaling at ingest | float | 3.3 | Sparse ANN docs |
| `quantization_ceiling_search` | float | Weight → uint8 scaling at query | float | 3.3 | Sparse ANN docs |
| `method_parameters.top_n` (query) | int | Top query tokens retained | int, typical 10 | 3.3 | Sparse ANN docs |
| `method_parameters.heap_factor` (query) | float | Cluster-selection recall/perf — **the `ef_search` analog for sparse ANN** | float, default 1.0, typical [0.5, 2.0] | 3.3 | Sparse ANN docs |
| `method_parameters.k` (query) | int | Candidates the ANN layer returns per segment | int, default 10 | 3.3 | Sparse ANN docs |

> ⚠ **Two silent traps (both verified on 3.8, both handled in code):**
> 1. **`approximate_threshold`** — below it, segments are stored as plain
>    `rank_features` and queried **exactly**, so `heap_factor`/`top_n` do nothing
>    and recall-vs-exact is trivially 1.0. Benchmarking on a <1M-doc sample MUST
>    set it to `0` (the tool does) or the whole mode measures exact-vs-exact.
> 2. **`method_parameters.k`** (default 10) — caps ANN candidates per segment. If
>    left at 10 while `size` > 10, results are silently truncated below the eval
>    depth, deflating recall. The tool pins `k` to the result size.

**Quality reference:** EXACT `rank_features` scoring on same tokens.

**Metric:** **Recall@k vs exact sparse** (primary, target ≥ 0.90); NDCG@k vs
qrels (secondary, if qrels available).

**Cost axis:** Inverted-index size (similar to rank_features but trades index
size for query-time approximation).

### Tuning strategy (agentic pruning)

1. Fix `n_postings`, `cluster_ratio`, `approximate_threshold` at defaults.
2. Sweep `method_parameters.heap_factor` first (query-time, cheapest recall
   dial): [0.5, 1.0, 1.5, 2.0].
3. If recall floor is unmet at `heap_factor=2.0`, escalate to higher
   `n_postings` or `cluster_ratio` (index-build-time, more expensive).
4. Plot Recall@k vs latency Pareto.

---

## Mode C: Hybrid (search-pipeline normalization + combination)

Combines dense + sparse signals via a search pipeline with normalization and
combination processors.

### Tunable parameters (v1: weights only)

| Dimension | Type | Verified values | Default | Verified in |
|---|---|---|---|---|
| `normalization` | string | `"min_max"`, `"l2"`, `"z_score"` | `"min_max"` | [Normalization processor docs](https://opensearch.org/docs/latest/search-plugins/search-pipelines/normalization-processor/), issue [#1209 z-score RFC](https://github.com/opensearch-project/neural-search/issues/1209) |
| `combination` | string | `"arithmetic_mean"`, `"harmonic_mean"`, `"geometric_mean"` | `"arithmetic_mean"` | [Score combination docs](https://opensearch.org/docs/latest/search-plugins/search-pipelines/score-combination/), issue [#1273 weight tuning](https://github.com/opensearch-project/neural-search/issues/1273) (8–12% NDCG lift from tuning) |
| `weights` | array of float | Dense:sparse weight ratio | `[0.5, 0.5]` (default equal), sweep [0.1:0.1:0.9] | Score combination docs, #1273 |

**Quality reference:** Best standalone mode (higher of dense-FP32 / sparse-unpruned
on qrels) or labeled qrels.

**Metric:** **NDCG@10 lift** vs best standalone (primary); latency overhead
(typically +6–8%).

**Cost axis:** Summed sub-query latency + normalization/combination overhead
(~6–8% of sub-query latencies).

### Tuning strategy (v1: weights-only sweep)

1. Fix `normalization="min_max"` and `combination="arithmetic_mean"` (proven
   prior from issue #1273).
2. Sweep the dense:sparse weight ratio in [0.1, 0.2, ..., 0.9] (9 points).
3. Plot NDCG@10 vs latency Pareto.
4. Recommend the weight ratio with highest NDCG@10 at acceptable latency
   overhead.
5. **v2 roadmap:** Permute normalization × combination × weights (full Cartesian
   or agentic pruning).

---

## DO NOT TUNE (unverified)

The following parameters are **explicitly excluded** from the sweep because they
are not stable, user-facing, or verified:

### Dense quantization enumeration beyond fp32/fp16

- **PQ / scalar / binary quantization availability** is engine-dependent
  (faiss/lucene/nmslib) and version-dependent. The tool detects fp32 (always) +
  fp16 (2.13+) conservatively and adds a note that further quantization should
  be re-verified at index-build time. Full enumeration is roadmap, not MVP.

### Legacy sparse param aliases

- `two_phase_ratio`, `two_phase_window_size`, `should_two_phase` — appear in
  older issue evidence (pre-2.15). The **verified current API** is
  `two_phase_parameter.{enabled,prune_type,prune_ratio,expansion_rate,max_window_size}`
  (2.15+). Use the latter.

### Hybrid sub-query raw scores

- Issue [#658](https://github.com/opensearch-project/neural-search/issues/658),
  [#1419](https://github.com/opensearch-project/neural-search/issues/1419) —
  open RFC for exposing sub-query raw scores. Not a stable API; excluded.

### WAND / block-max toggle for hybrid

- Issue [#1829](https://github.com/opensearch-project/neural-search/issues/1829) —
  no confirmed user-facing knob. Excluded.

### Sparse ANN cache concurrency

- Issue [#1691](https://github.com/opensearch-project/neural-search/issues/1691) —
  a *fixed internal issue* (v3.5.0), not a user tunable. Report as a caveat in
  notes, not a swept param.

### Dynamic normalization / combination

- Issue [#1005](https://github.com/opensearch-project/neural-search/issues/1005) —
  open RFC. Not stable; excluded.

---

## Version gates and detection

Parameters that are version-gated are detected at runtime by `scripts/probe.py`:

- **fp16 quantization:** Available when cluster version >= 2.13 (parsed semver,
  component-wise).
- **Sparse rank_features:** Available when `opensearch-neural-search` plugin is
  present (any version >= 2.11).
- **Two-phase processor:** Available when neural-search is present and version
  >= 2.15.
- **Sparse ANN (SEISMIC):** Available when neural-search is present and version
  >= 3.3.

The probe *never assumes* a feature is available based solely on version; it
queries `_cat/plugins` and the ml-commons model registry to confirm.

---

## Cross-references

- OpenSearch k-NN plugin docs: <https://opensearch.org/docs/latest/search-plugins/knn/>
- Neural sparse search docs: <https://opensearch.org/docs/latest/search-plugins/neural-sparse-search/>
- Two-phase processor docs: <https://opensearch.org/docs/latest/search-plugins/neural-sparse-two-phase/>
- Sparse ANN (SEISMIC) docs: <https://opensearch.org/docs/latest/field-types/supported-field-types/sparse/>
- Hybrid search normalization processor: <https://opensearch.org/docs/latest/search-plugins/search-pipelines/normalization-processor/>
- Score combination processor: <https://opensearch.org/docs/latest/search-plugins/search-pipelines/score-combination/>
- k-NN issue #21 (silent recall drop): <https://github.com/opensearch-project/k-NN/issues/21>
- Neural-search issue #946 (index bloat): <https://github.com/opensearch-project/neural-search/issues/946>
- Neural-search issue #988 (pruning PR): <https://github.com/opensearch-project/neural-search/pull/988>
- Neural-search issue #646 (two-phase confusion): <https://github.com/opensearch-project/neural-search/issues/646>
- Neural-search issue #1273 (weight tuning): <https://github.com/opensearch-project/neural-search/issues/1273>
