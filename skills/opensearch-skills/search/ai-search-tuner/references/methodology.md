# Evaluation Methodology

This document defines how `ai-search-tuner` measures quality@k for each
retrieval mode and establishes the per-mode quality reference (ground truth).

## Per-mode quality reference table

The crux: **one harness, one report, but the reference and metrics vary by mode**
because dense k-NN and sparse ANN are *approximations* of exact search, while
traditional neural sparse (`rank_features`) is *exact Lucene scoring*.

| Mode | Approximate? | Reference (ground truth) | Primary metric | Secondary metric | Cost axis |
|---|---|---|---|---|---|
| Dense k-NN (HNSW) | **Yes** | FP32 exact brute-force (`script_score` cosine at `ef_search = N`) or labeled qrels | **Recall@k vs exact** | NDCG@k / MAP@k (if qrels) | HNSW graph memory |
| Sparse `rank_features` | **No (exact)** | Labeled qrels or un-pruned bi-encoder baseline | **NDCG@k / MAP@k** | — | Inverted-index / segment size |
| Sparse ANN (`sparse_vector`, SEISMIC) | **Yes** | Exact `rank_features` scoring on same tokens | **Recall@k vs exact sparse** | NDCG@k / MAP@k (if qrels) | Inverted-index size |
| Hybrid (search pipeline) | — | Best standalone mode (higher of dense-FP32 / sparse-unpruned on qrels) or labeled qrels | **NDCG@10 lift** vs best standalone | Latency overhead | Summed sub-index sizes |

## The exact vs approximate distinction

### Approximate modes (Dense k-NN, Sparse ANN)

These modes use graph-based or cluster-based acceleration (HNSW for dense,
SEISMIC for sparse ANN) that trades off recall for speed. The **ground truth**
is the *exact* top-k result set — computed by brute-force for dense (cosine
over all N vectors) or by exact `rank_features` scoring for sparse ANN.

**Metric emphasis:** **Recall@k** — what fraction of the true top-k neighbors
does the approximate engine find? Target: typically ≥ 0.90 or ≥ 0.95.

**Tuning goal:** Find the cheapest config (lowest graph memory / index size,
fastest latency) that holds a user-specified recall floor (e.g. ≥ 0.95).

**How recall ground truth is generated:**

- **Dense k-NN:** The tool builds a temporary FP32 index (or reuses the
  corpus embeddings in memory) and runs brute-force `script_score` queries with
  cosine similarity over all documents (conceptually `ef_search = corpus_size`).
  This is O(N × queries) and is computed on a *sample* only (never full
  production corpus).
- **Sparse ANN:** The tool builds a temporary `rank_features` index on the same
  tokens and runs exact Lucene scoring (no SEISMIC approximation). This is the
  true top-k for sparse retrieval.

If human relevance judgments (qrels) are provided, the tool *also* reports
NDCG@k / MAP@k as a secondary metric — but recall vs exact is the primary
tuning axis.

### Exact mode (Sparse rank_features)

Traditional neural sparse using `rank_features` field type is **exact Lucene
retrieval** — it scores every document that has at least one query-token overlap
and returns the true top-k by BM25-like weighted-sum scoring. There is no
graph or cluster approximation, so recall vs itself is trivially 1.0.

**The critical methodology statement (stated verbatim in SKILL.md):**

> *"Traditional neural sparse is exact Lucene retrieval — there is no
> HNSW-style recall to tune. We grade it on NDCG/MAP against labeled judgments
> (or against an un-pruned bi-encoder reference), and we grade pruning/two-phase
> purely on the relevance-preservation-vs-cost tradeoff."*

**Metric emphasis:** **NDCG@k / MAP@k** against human relevance judgments (if
available) or against an un-pruned bi-encoder baseline (if qrels are not
provided).

**Tuning goal:** Shrink the index (via `prune_ratio` / `prune_type`) and/or
accelerate queries (via `two_phase_parameter.*`) while preserving relevance.
Target: <1–2% NDCG@10 loss for 30–40% index-size reduction.

**How the reference is generated:**

- **If qrels are provided:** NDCG@k / MAP@k are computed against the labeled
  judgments. This is the gold standard.
- **If no qrels:** The tool establishes an *un-pruned bi-encoder baseline* (the
  richest sparse encoding: bi-encoder model, `prune_type=none`, all tokens
  retained) and measures result-set overlap and NDCG-like scoring relative to
  that baseline. This is a proxy for relevance.

**Why two-phase is "free":** The two-phase processor splits tokens into
high-weight (phase 1) and low-weight (phase 2) and scores only the top
`expansion_rate × size` candidates from phase 1 in phase 2. This is a
query-time optimization that does **not** change the scoring formula or the
final ranking (when `expansion_rate` is set correctly, typically 5.0). It
trades latency (28–60% reduction) for zero relevance loss. The tool verifies
this by asserting NDCG@k stays flat when two-phase is enabled.

## Metrics definitions

### Recall@k

What fraction of the true top-k (from exact ground truth) does the approximate
engine return in its top-k?

```
Recall@k = |approximate_top_k ∩ exact_top_k| / k
```

Averaged over all queries. Range [0, 1]. Target: typically ≥ 0.90 or ≥ 0.95.

**Only meaningful for approximate modes** (dense k-NN, sparse ANN).

### NDCG@k (Normalized Discounted Cumulative Gain)

A ranking metric that rewards relevant documents appearing higher in the
results, with exponential position discount. Requires human relevance judgments
(qrels) with graded relevance (e.g. 0 = not relevant, 1 = somewhat relevant, 2
= highly relevant).

```
DCG@k = Σ_{i=1..k} (2^{rel_i} - 1) / log2(i + 1)
NDCG@k = DCG@k / ideal_DCG@k
```

Averaged over all queries. Range [0, 1]. Higher is better.

**Primary metric for exact sparse** (`rank_features`); secondary for approximate
modes (when qrels are available).

### MAP@k (Mean Average Precision at k)

A binary relevance metric that rewards relevant documents appearing higher and
penalizes missing relevant documents. Requires qrels with binary relevance (0/1).

```
AP@k = (1/min(R, k)) × Σ_{i=1..k} P(i) × rel(i)
where P(i) = precision at position i, rel(i) = 1 if relevant else 0
MAP@k = mean of AP@k over all queries
```

Range [0, 1]. Higher is better.

**Secondary metric** for all modes (when qrels are available).

## Quality thresholds and flags

The tool flags configs that breach user-specified thresholds:

- **Recall floor breach:** Any approximate config with Recall@k < user-specified
  floor (e.g. 0.95). Flagged as `"below-recall-floor"`.
- **Silent quality regression:** Any config that drops quality >5% vs the
  baseline/reference (e.g. NDCG@10 falls from 0.68 to 0.64) when a "cost-saving"
  option is enabled (e.g. aggressive pruning, heavy quantization). Flagged as
  `"silent-recall-drop"` or `"silent-ndcg-drop"`.
- **Latency budget breach:** Any config with p95 latency > user-specified budget
  (e.g. 100ms). Flagged as `"over-latency-budget"`.

Flagged configs are visually marked in the Pareto report and ranked lower in
recommendations (all else equal).

## Confidence intervals

Latency and quality metrics are computed over multiple query batches (typically
3–5 runs) to establish confidence intervals. The tool reports p50/p95/p99
latency with 95% CIs. Quality metrics (Recall@k, NDCG@k) are averaged over
batches with standard error reported.

For deterministic correctness testing, the test suite uses FakeOSClient with
zero randomness and fixed synthetic latencies.

## Cost measurement per mode

- **Dense k-NN:** HNSW graph memory in bytes, estimated as ≈ `m × N × {4..16}`
  (4 bytes for FP32, 2 for FP16, variable for PQ/scalar/binary), probed via
  `_cluster/stats` and `_plugins/_knn/stats`.
- **Sparse (rank_features, sparse_vector):** Inverted-index / segment size in
  bytes, probed via `_cat/indices?format=json&bytes=b` (`store.size`).
- **Hybrid:** Summed sub-index sizes (dense graph + sparse inverted-index) plus
  normalization/combination overhead (typically 6–8% latency penalty), measured
  by timing hybrid queries vs standalone queries.

## Sample size and scale caveats

Exact ground truth (brute-force dense, exact rank_features) is O(N × queries)
and is computed on a **sample** only (default: 10k documents, 100 queries) to
bound runtime. The tool documents scale caveats in the report:

- Small-sample recall may be optimistic (fewer distractors).
- Latency is measured on the sample, not production load.
- Recommendations include a "re-validate on larger sample" note for production
  deployment.

For large production corpora (>10M docs), the tool warns and prompts for an
explicit `--sample-size` cap or `--full-corpus` confirmation (gated).
