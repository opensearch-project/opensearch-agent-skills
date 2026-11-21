# Decision Guide: When to Use Which Mode

This guide helps you choose between **dense k-NN**, **neural sparse**, and
**hybrid** retrieval modes based on your use case, corpus, and role.

## Quick decision tree

```
Start here
    │
    ├─ Do you have dense embeddings (e.g. from BERT, sentence-transformers)?
    │   YES → Consider Dense k-NN (§1) or Hybrid (§4)
    │   NO  → Consider Neural Sparse (§2, §3)
    │
    ├─ Do you have a neural sparse model (OpenSearch 2.11+ with neural-search plugin)?
    │   YES → Consider Neural Sparse (§2, §3) or Hybrid (§4)
    │   NO  → Dense k-NN only (§1)
    │
    ├─ Can you afford to combine both?
    │   YES → Hybrid (§4) typically wins on relevance (8–12% NDCG lift)
    │   NO  → Pick the strongest standalone (run ai-search-tuner to decide)
    │
    └─ Large corpus (>10M docs) + latency-sensitive?
        YES → Consider Sparse ANN (SEISMIC, 3.3+) or Dense with aggressive quantization
        NO  → Dense or Sparse rank_features (exact) both viable
```

---

## 1. Dense k-NN (HNSW approximate)

### What it is

Approximate nearest-neighbor search over dense embeddings (e.g. 768-dim BERT
vectors) using an HNSW graph. Fast at query time but requires all embeddings
fit in HNSW graph memory (≈ `m × N × {4..16} bytes` depending on quantization).

### When to use it

- **You have pre-trained dense embeddings** (e.g. from `sentence-transformers`,
  OpenAI `text-embedding-ada-002`, Cohere, etc.) or can generate them at ingest.
- **Semantic similarity is the primary signal** (e.g. "find documents
  semantically similar to this query", "nearest neighbors in embedding space").
- **Corpus is small-to-medium** (<10M docs) or you can afford the HNSW graph
  memory (2–4 GB per 1M 768-dim FP32 vectors at `m=16`).
- **Latency is critical** — HNSW is fast (single-digit ms p95 for 10k–100k
  corpora) once the graph is built.

### When NOT to use it

- **Corpus is huge** (>50M docs) and you're hitting heap OOM — consider sparse
  (which scales better with inverted-index sharding) or aggressive quantization
  (FP16, PQ, binary).
- **Lexical / exact-match is important** — dense embeddings sometimes miss
  lexical overlaps (e.g. searching for "SKU-4471" won't hit if the embedding
  doesn't encode product IDs well). Consider hybrid to blend lexical + semantic.
- **No embeddings exist** and generating them is too expensive — fall back to
  BM25 or neural sparse (which can be doc-only, no query-time inference).

### Tuning surface (what ai-search-tuner sweeps)

- **`ef_search`** (query-time search breadth) — cheapest recall dial, sweep
  [50, 100, 200, 400].
- **Quantization** (FP32 → FP16 → PQ) — trades graph memory for recall; FP16
  typically −50% memory at <2% recall loss.
- **`m`, `ef_construction`** (build-time) — escalate only if `ef_search` sweep
  doesn't meet the recall floor.

### Role-specific advice

- **Search engineer:** Default to FP32 + `ef_search=100`; run `ai-search-tuner
  --mode dense` to find the memory-optimal config.
- **ML engineer:** If you're training custom embeddings, benchmark dense recall
  vs your validation set before shipping; silent recall drops are real (issue
  #21).
- **SRE:** Monitor HNSW graph memory (`_plugins/_knn/stats`) in prod; set heap
  alerts at 80% to catch OOM before it crashes. Use `ai-search-tuner` in CI to
  regression-test recall.

---

## 2. Neural Sparse, traditional (rank_features, exact)

### What it is

Exact Lucene scoring over learned sparse token weights (e.g. SPLADE-like models).
Documents and queries are encoded as {token → weight} dicts, and OpenSearch
scores them with BM25-like weighted-sum math. **No approximation** (unlike HNSW
or SEISMIC); every document with at least one query-token overlap is scored.

### When to use it

- **You want the best of both worlds** — semantic understanding (from a neural
  model) + lexical interpretability (you can see which tokens matched).
- **Corpus is medium-to-large** (1M–50M docs) — sparse scales better than dense
  via inverted-index sharding.
- **Latency is acceptable** — exact scoring is slower than HNSW (50–100ms p95
  for 10M docs, doc-only model; 100–200ms for bi-encoder).
- **You have a deployed neural sparse model** (OpenSearch 2.11+ with
  `opensearch-neural-search` plugin + a model like
  `opensearch-neural-sparse-encoding-doc-v3-distill`).
- **Index bloat is a concern** — sparse indexes are 4.7–6.8× BM25 un-pruned
  (issue #946), but `prune_ratio=0.1` shrinks them −40% with <1% NDCG loss.

### When NOT to use it

- **Latency must be <10ms** — exact sparse is slower than HNSW. Consider dense
  or sparse ANN (SEISMIC, 3.3+) for sub-10ms.
- **Corpus is tiny** (<10k docs) — BM25 or dense are simpler and fast enough.
- **You need every query-token to be re-ranked by a bi-encoder** and corpus is
  huge — bi-encoder inference at query time is expensive for large corpora;
  consider doc-only + two-phase or dense.

### Tuning surface (what ai-search-tuner sweeps)

- **`prune_ratio`** (ingest-time token pruning) — sweep [0.0, 0.1, 0.2, 0.3] to
  find the relevance-vs-index-size knee.
- **`two_phase_parameter.enabled`** — enable by default (free 28–60% latency
  cut, zero relevance loss).
- **Model choice** (doc-only vs bi-encoder) — doc-only is faster (no query-time
  inference), bi-encoder is more accurate; let `ai-search-tuner` compare.

### Role-specific advice

- **Search engineer:** Start with doc-only model + `prune_ratio=0.1` +
  `two_phase_parameter.enabled=true`. Run `ai-search-tuner --mode sparse` to
  validate the pruning knee.
- **ML engineer:** If you have qrels, use them to benchmark NDCG@10 vs un-pruned
  baseline; <1–2% loss is acceptable for 30–40% index shrink.
- **SRE:** Monitor inverted-index size (`_cat/indices?bytes=b`) and query
  latency (p95); two-phase is a free win but verify `expansion_rate=5.0` works
  for your corpus (check NDCG@k stays flat).

---

## 3. Sparse ANN (sparse_vector/SEISMIC, approximate, 3.3+)

### What it is

SEISMIC cluster-based approximate scoring over sparse vectors. **Approximate**
(unlike rank_features); trades recall for speed. Only available OpenSearch 3.3+.

### When to use it

- **Corpus is huge** (>50M docs) and exact `rank_features` is too slow.
- **Latency must be <50ms p95** — SEISMIC is faster than exact sparse.
- **You can tolerate 5–10% recall loss** — SEISMIC is approximate, target
  Recall@k ≥ 0.90.
- **You have OpenSearch 3.3+** with the neural-search plugin.

### When NOT to use it

- **OpenSearch < 3.3** — feature not available, fall back to rank_features.
- **Exact scoring is required** — e.g. compliance/audit where you must score
  every token overlap; use rank_features.
- **Corpus is small** (<1M docs) — exact rank_features is fast enough, no need
  for approximation.

### Tuning surface (what ai-search-tuner sweeps)

- **`method_parameters.heap_factor`** (query-time cluster-selection breadth) —
  the `ef_search` analog for sparse ANN; sweep [0.5, 1.0, 1.5, 2.0].
- **`n_postings`, `cluster_ratio`** — escalate only if `heap_factor` doesn't
  meet the recall floor.

### Role-specific advice

- **Search engineer:** SEISMIC is new (3.3+); default to rank_features unless
  latency forces approximation. Run `ai-search-tuner --mode sparse` to compare
  exact vs ANN Pareto.
- **ML engineer:** Benchmark Recall@k vs exact rank_features (ai-search-tuner
  does this automatically); target ≥ 0.90.
- **SRE:** SEISMIC cache concurrency was fixed in 3.5.0 (issue #1691); if
  on <3.5, upgrade or monitor for cache contention.

---

## 4. Hybrid (normalization + combination)

### What it is

Combines dense + sparse signals via a search pipeline with normalization
(min_max / l2 / z_score) and combination (arithmetic_mean / harmonic_mean /
geometric_mean). Requires both a dense k-NN index and a sparse index
(`rank_features` or `sparse_vector`).

### When to use it

- **You have both dense embeddings and sparse models** and want the best of
  both.
- **Relevance is paramount** — hybrid typically lifts NDCG@10 by 8–12% vs the
  best standalone mode (issue #1273).
- **Latency budget allows +6–8% overhead** — hybrid runs both sub-queries plus
  normalization/combination.
- **You can afford double the index footprint** — dense graph + sparse
  inverted-index.

### When NOT to use it

- **Latency is critical** (<10ms p95) — hybrid adds overhead; stick to the
  faster standalone mode.
- **Only one signal is available** — if you only have dense embeddings or only
  sparse, hybrid doesn't apply.
- **Storage budget is tight** — hybrid doubles index footprint (dense graph +
  sparse inverted-index).

### Tuning surface (what ai-search-tuner sweeps)

- **Dense:sparse weight ratio** — sweep [0.1, 0.2, ..., 0.9] at fixed
  `min_max` + `arithmetic_mean` (v1 weights-only sweep).
- **v2 roadmap:** Full normalization × combination permutation (27 combos).

### Role-specific advice

- **Search engineer:** Start with equal weights `[0.5, 0.5]`; run
  `ai-search-tuner --mode hybrid` to find the optimal ratio (typically 0.3–0.6
  for dense, 0.4–0.7 for sparse, depending on corpus).
- **ML engineer:** If you have qrels, measure NDCG@10 lift vs best standalone;
  8–12% is typical and worth the latency/storage cost.
- **SRE:** Monitor sub-query latencies separately (dense + sparse) to isolate
  bottlenecks; normalization/combination adds ~6–8% overhead (cheap).

---

## Cross-mode comparison table

| Dimension | Dense k-NN | Sparse rank_features | Sparse ANN (SEISMIC) | Hybrid |
|---|---|---|---|---|
| **Approximate?** | Yes (HNSW) | No (exact Lucene) | Yes (cluster-based) | Depends on sub-modes |
| **Min OpenSearch version** | 1.x (k-NN plugin) | 2.11 (neural-search) | 3.3 (SEISMIC) | 2.11 (neural-search) |
| **Primary metric** | Recall@k vs exact | NDCG@k / MAP@k | Recall@k vs exact sparse | NDCG@10 lift |
| **Latency (10M docs)** | <10ms p95 | 50–100ms p95 (doc-only) | 20–50ms p95 | +6–8% vs slower sub-mode |
| **Footprint** | HNSW graph (2–4 GB / 1M FP32 vecs) | Inverted-index (4.7–6.8× BM25 unpruned) | Similar to rank_features | Double (dense + sparse) |
| **Tuning complexity** | Low (ef_search + quantization) | Medium (prune_ratio + two-phase) | Medium (heap_factor + n_postings) | High (weights + normalization + combination) |
| **Best for** | Semantic similarity, speed | Lexical + semantic, interpretability | Large corpora, speed | Best relevance, no budget constraints |

---

## Decision scenarios (by role)

### Search Engineer

**Scenario 1:** "I have 5M product descriptions with BERT embeddings. Latency
must be <50ms p95. Budget allows 20 GB heap."

→ **Dense k-NN** (FP32 at m=16 → ~8 GB graph, <10ms p95). Run `ai-search-tuner
--mode dense` to verify recall and find the memory-optimal quantization.

**Scenario 2:** "I have 10M docs with a neural sparse model (doc-only). Index is
70 GB (7× BM25). Can I shrink it?"

→ **Sparse rank_features** with `prune_ratio=0.1` → ~42 GB (−40%), <1% NDCG
loss. Enable `two_phase_parameter.enabled=true` for free latency win. Run
`ai-search-tuner --mode sparse` to validate.

**Scenario 3:** "I have both dense and sparse. Which is better?"

→ **Hybrid** typically wins (+8–12% NDCG). Run `ai-search-tuner` with both modes
to compare and find the optimal dense:sparse weight ratio.

### ML Engineer

**Scenario 1:** "I'm training a custom dense embedding model. How do I know if
recall regresses?"

→ Use `ai-search-tuner --mode dense --qrels ./val_qrels.json` in CI to
benchmark Recall@10 vs FP32 brute-force. Flag any config <0.95 recall.

**Scenario 2:** "I have sparse qrels. Should I prune aggressively or not?"

→ Run `ai-search-tuner --mode sparse --qrels ./qrels.json` to plot NDCG@10 vs
index-size Pareto. The knee is typically `prune_ratio=0.1` (<1% NDCG loss, −40%
size).

**Scenario 3:** "Hybrid weights: what's the optimal ratio?"

→ Run `ai-search-tuner --mode hybrid --qrels ./qrels.json` to sweep [0.1 : 0.1 :
0.9]. The tool will recommend the ratio with highest NDCG@10 at acceptable
latency.

### SRE

**Scenario 1:** "HNSW graph is eating all our heap. What can I do?"

→ Quantization: FP16 typically −50% memory at <2% recall loss. Run
`ai-search-tuner --mode dense` to validate. If that's not enough, consider
sparse (inverted-index scales better with sharding).

**Scenario 2:** "Sparse queries are slow (100ms p95). How to speed up?"

→ Enable `two_phase_parameter.enabled=true` (free 28–60% latency cut). If
still too slow, consider doc-only model (no query-time inference) or SEISMIC
ANN (3.3+, approximate).

**Scenario 3:** "We're combining dense + sparse but latency is high."

→ Profile sub-query latencies separately (dense + sparse). Optimize the slower
one first (e.g. prune sparse, quantize dense). Normalization/combination
overhead is only ~6–8%.

---

## Summary

- **Dense k-NN:** Fast, semantic, heap-hungry. Best for <10M docs or when
  latency is critical. Tune `ef_search` and quantization.
- **Sparse rank_features:** Exact, lexical + semantic, index-bloat risk. Best
  for 1M–50M docs. Tune `prune_ratio` and enable two-phase.
- **Sparse ANN (SEISMIC):** Approximate, fast, 3.3+ only. Best for >50M docs.
  Tune `heap_factor`.
- **Hybrid:** Best relevance, double the cost. Best when budget allows and
  relevance is paramount. Tune dense:sparse weight ratio.

Use `ai-search-tuner` to run empirical benchmarks and let the Pareto frontiers
guide your choice.
