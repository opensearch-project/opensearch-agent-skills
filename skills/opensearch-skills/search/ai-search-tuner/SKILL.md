---
name: ai-search-tuner
description: >
  Benchmark and Pareto-tune OpenSearch retrieval across dense k-NN, neural
  sparse, and hybrid modes. Measures quality@k (Recall/NDCG/MAP) vs latency vs
  footprint, detects silent recall regressions, and recommends the cost-optimal
  config — emitting the exact index template and search-pipeline JSON. Read-only
  by default; runs on temporary sample indices. Use this skill when the user
  wants to tune or benchmark an EXISTING retrieval setup (not build a new app):
  choose HNSW/quantization that holds recall while cutting graph memory (OOM),
  set neural sparse prune_ratio to shrink an oversized index, tune SEISMIC
  heap_factor, find the optimal dense:sparse hybrid weight ratio, catch silent
  recall/NDCG regressions before production, or get a Pareto-optimal
  quality-vs-latency-vs-footprint recommendation rather than one config.
  Keywords: OpenSearch retrieval tuning, vector search optimization, k-NN recall,
  neural sparse pruning, hybrid search weights, HNSW graph memory, dense
  quantization, NDCG at k, Pareto frontier.
compatibility: Requires uv and a running OpenSearch cluster with the k-NN plugin. Neural sparse and hybrid modes additionally require the neural-search plugin and a deployed ML model; sparse ANN (SEISMIC) requires OpenSearch 3.3+.
metadata:
  author: zirui-song-18
  version: "1.0"
---

# ai-search-tuner

An OpenSearch Agent Skill that benchmarks and Pareto-tunes retrieval across
**dense k-NN**, **neural sparse**, and **hybrid** modes — grading *quality@k*
(Recall/NDCG/MAP) against *latency* and *footprint* — and recommends the
cost-optimal configuration for a given corpus.

## What it does

`ai-search-tuner` measures how well retrieval actually works and prescribes the
best configuration for your quality and cost budget. It:

1. **Probes capabilities** — inspects plugins, models, and cluster version to
   determine which modes (dense, sparse, hybrid) are available; modes whose
   prerequisites are absent are cleanly skipped.
2. **Establishes per-mode quality references** — brute-force exact for dense;
   labeled qrels or un-pruned baseline for sparse; best-standalone for hybrid.
3. **Agentically prunes the config space** — sweeps the dominant tuning axis
   first (e.g. `ef_search` for dense, `prune_ratio` for sparse) and early-stops
   on threshold breaches; never brute-forces the full Cartesian product.
4. **Builds temporary variant indices** on a sample, runs each config, and
   measures *quality@k* (k ∈ {5,10,100}), *latency* (p50/p95/p99), and
   *footprint* (graph memory for dense, index size for sparse).
5. **Flags silent quality regressions** — detects the class of failures where
   recall or NDCG silently drops when a storage optimization is enabled.
6. **Emits a Pareto report** — quality-vs-latency and quality-vs-footprint
   frontiers with the recommended config highlighted, plus the ready-to-apply
   index template or search-pipeline JSON.

## The three retrieval modes

### Dense k-NN (HNSW approximate)

Tunes HNSW graph parameters (`m`, `ef_construction`, `ef_search`) and
quantization (FP32/FP16/PQ/scalar/binary, distro-dependent). **Quality
reference:** FP32 exact brute-force cosine or labeled qrels. **Metric:** Recall@k
vs exact. **Cost:** HNSW graph memory (≈ `m × N × {4..16} bytes` by quantization).

**Use when:** Dense embeddings, approximate nearest-neighbor search, heap/OOM
concerns, or quantization tradeoffs.

### Neural Sparse, traditional (rank_features, EXACT)

Tunes sparse encoding (`prune_ratio`, `prune_type`, model choice: doc-only vs
bi-encoder), and two-phase scoring (`two_phase_parameter.*`). **Quality
reference:** labeled qrels or un-pruned bi-encoder baseline. **Metric:** NDCG@k
or MAP@k vs judgments; pruning/two-phase graded on relevance-preservation vs
cost. **Cost:** inverted-index / segment size (pruning combats 4.7–6.8× BM25
bloat).

**CRITICAL METHODOLOGY STATEMENT:** Traditional neural sparse is **exact Lucene
retrieval** — there is no HNSW-style recall to tune. We grade it on NDCG/MAP
against labeled judgments (or against an un-pruned bi-encoder reference), and we
grade pruning/two-phase purely on the **relevance-preservation-vs-cost
tradeoff**. Do not report "recall" for this mode; it is exact scoring by
definition.

**Use when:** Neural sparse search (OpenSearch 2.11+), inverted-index size
explosion, two-phase configuration uncertainty, or pruning parameter tuning.

### Sparse ANN (sparse_vector/SEISMIC, approximate, 3.3+)

Tunes SEISMIC parameters (`heap_factor`, `n_postings`, `cluster_ratio`). **Quality
reference:** EXACT `rank_features` scoring on the same tokens. **Metric:**
Recall@k vs exact sparse + NDCG vs qrels. **Cost:** similar to rank_features but
trades index size for query-time approximation.

**Use when:** OpenSearch 3.3+, sparse ANN over traditional exact sparse, large
corpora where even pruned rank_features is too slow.

### Hybrid (normalization + combination search pipeline)

Tunes dense:sparse weight ratios at fixed `min_max` normalization and
`arithmetic_mean` combination (v1 sweeps **weights only**; full
normalization/combination permutation is roadmap). **Quality reference:**
strongest standalone mode or qrels. **Metric:** NDCG@10 lift vs best standalone.
**Cost:** summed sub-query latency + normalization overhead (~6–8%).

**Use when:** Combining dense + sparse signals, hybrid RAG, or empirically
finding the best weight ratio (eliminates hand-guessing).

## Invocation

### Minimum input

The corpus alone. Recall ground truth for approximate modes is generated by the
tool (brute-force for dense; exact `rank_features` for sparse ANN). Queries can
be auto-sampled from the corpus.

```bash
ai-search-tuner --corpus ./data
```

### Optional qrels

Supply relevance judgments to also grade NDCG@k / MAP@k (human relevance):

```bash
ai-search-tuner --corpus ./data --qrels ./qrels.json
```

### Natural language invocation

> "I need at least 0.95 recall@10 on my embeddings index but I'm running out of
> heap. Benchmark quantization options and tell me the cheapest config that
> holds recall. If my cluster supports neural sparse and hybrid, compare those
> too."

The agent will:

1. Probe your cluster (`scripts/probe.py`) to detect which modes are available.
2. If dense k-NN is present, sweep `ef_search` at FP32 and available
   quantization options, plot Recall@10 vs graph-memory Pareto, and recommend
   the config meeting your 0.95 floor at lowest memory.
3. If neural-search plugin + deployed models are present, also run sparse
   benchmarks (pruning sweep) and hybrid (weight sweep).
4. Return the winning index template or search-pipeline JSON with the
   recommendation.

### Running it (agent quick-start — read this before shelling out)

Run the orchestrator; it prints per-config tables and (with `--report`) an HTML
Pareto. **Do not hand-write your own benchmark script — the CLI already sweeps
each mode and refines. Just pick the flags:**

```bash
# From the skill dir. localhost cluster is auto-detected (HTTP/HTTPS) — you do
# NOT need to set OPENSEARCH_URL for a local cluster.
python3 scripts/ai_search_tuner_cli.py \
  --corpus assets/scifact/corpus.jsonl \
  --queries assets/scifact/queries.jsonl \   # explicit labeled queries (ids match --qrels)
  --qrels  assets/scifact/qrels.json \
  --modes dense_knn \                         # comma list; omit to run all supported
  --k 10 --quality-floor 0.95 \               # floor drives flagging + refine()
  --report /tmp/report.html
```

- **Connection:** a local cluster on `localhost:9200` is auto-detected (HTTP
  first, then HTTPS; self-signed certs accepted). Only set env vars for a remote
  or secured cluster: `OPENSEARCH_URL`, `OPENSEARCH_USERNAME`/`PASSWORD` or
  `OPENSEARCH_API_KEY`, or `OPENSEARCH_AWS_REGION` (SigV4).
- **Slow modes:** sparse / hybrid index every doc through the ML model, so a
  few-thousand-doc corpus takes minutes. Set `OPENSEARCH_TIMEOUT=300` and be
  patient; for a fast demo use `--modes dense_knn` (seconds) or a smaller corpus.
- **Per-mode metric:** dense & sparse-ANN report **recall@k vs exact**; sparse
  `rank_features` & hybrid report **NDCG@k** (they're exact / relevance-graded).
  A config below the floor is tagged `silent-quality-drop` — that's the #21
  detector, not an error.
- **Quantization reads:** the dense sweep already tests fp16 at a low AND high
  `ef_search`. If fp16 recall stays flat across both, it's precision loss that
  ef_search can't recover — recommend fp32. (You don't need to re-test this.)
- **Reading results programmatically** (if you inspect `Measurement` objects
  directly instead of the printed table): quality = `m.quality.get(Metric.RECALL, k)`
  or `Metric.NDCG`; latency = `m.latency_p95_ms`; footprint = `m.cost.primary_bytes()`.

## Safety model

- **Read-only by default.** Benchmarking operates on *temporary* indices built
  from a *sample* of the corpus; it never mutates your production index.
- **Confirmation-gated writes.** Applying a recommended template/pipeline to a
  real index requires explicit user confirmation.
- **Bounded blast radius.** Sample-size caps, variant-count caps, auto-cleanup
  of temp indices even on error.
- **Least privilege.** Auth via environment variables (basic / API key / SigV4);
  no credentials in context or logs.

## Capability-based graceful degradation

The tool detects what your cluster actually supports and lights up modes
accordingly:

- **Dense always** (if `opensearch-knn` plugin is present) — the baseline, works
  on any k-NN distro.
- **Sparse + Hybrid light up** when `opensearch-neural-search` plugin is present
  and a deployed ML model is found (OpenSearch 2.11+).
- **Sparse ANN (SEISMIC)** requires neural-search + version 3.3+.

Modes whose prerequisites are absent are **cleanly skipped**, never failed. A
cluster with only the k-NN plugin will run dense-only benchmarks; a 3.3+ cluster
with neural-search + models will run all four modes.

## Scripts reference

The skill is organized as:

```
ai-search-tuner/
  SKILL.md                     # this file
  references/
    methodology.md             # quality@k per mode; the "sparse is exact" statement
    parameters.md              # verified tunable-parameter tables
    decision-guide.md          # dense vs sparse vs hybrid: when to use which
  assets/                      # sample corpus + qrels for a no-cluster demo
  scripts/
    ai_search_tuner_cli.py     # orchestrator: probe -> sweep -> benchmark -> report
    probe.py                   # capability detection -> {dense, sparse_*, hybrid}
    harness/                   # shared evaluation harness (~60% of code)
      model.py                 # data model + Mode.is_approximate (exact-vs-approx rule)
      interfaces.py            # IndexBuilder / QueryRunner / CostProbe / ReferenceProvider
      runner.py                # config sweep loop + latency capture (p50/p95/p99)
      quality.py               # Recall@k / NDCG@k / MAP@k from qrels or reference
      pareto.py                # frontier computation + threshold flagging
      report.py                # self-contained HTML Pareto report
      corpus.py                # corpus/qrels loading + query sampling
      client.py                # OpenSearch client wrapper (auth via env vars)
    modes/                     # per-mode logic (~40%); agentic pruning lives here
      dense_knn.py             # IndexBuilder + QueryRunner + CostProbe for k-NN/HNSW
      sparse_rank_features.py  # traditional neural sparse (exact)
      sparse_ann.py            # SEISMIC sparse_vector (approximate)
      hybrid.py                # normalization/combination search pipeline
```

Key entry points:

- `scripts/probe.py` — standalone capability detection; run directly or import
  `detect_capabilities(client)`.
- `scripts/harness/quality.py` — Recall@k / NDCG@k / MAP@k computation.
- `scripts/harness/pareto.py` — Pareto frontier and recommendation ranking.
- `scripts/modes/dense_knn.py` — dense k-NN index builder and query runner.
- `scripts/modes/sparse_rank_features.py` — sparse rank_features index builder
  and query runner.

## Output artifacts

1. **Top-3 configs per mode** + one **cross-mode recommendation** for your
   budget.
2. The **index template** (dense/sparse) and/or **search-pipeline definition**
   (hybrid) implementing the recommendation.
3. An **HTML Pareto report** (self-contained, no heavy SPA).
4. A machine-readable results file (JSON) for CI / regression tracking.

## Example use cases

### Use case 1: Dense k-NN quantization tradeoff

**Scenario:** You have a 10M-document dense index with 768-dim embeddings
(~30GB FP32 graph). You're running out of heap and considering FP16 or PQ, but
you're unsure of the recall impact.

**Command:**

```bash
ai-search-tuner --corpus ./embeddings --qrels ./qrels.json \
  --mode dense --min-recall 0.95
```

**Output:** Pareto plot of Recall@10 vs graph-memory showing:

- FP32 baseline: Recall@10 0.97, 30.2 GB
- FP16 recommended: Recall@10 0.95, 15.1 GB (−50% memory, floor held)
- PQ: Recall@10 0.89, 7.5 GB (below floor, flagged)

Plus the index template JSON with `method.encoder.fp16` set.

### Use case 2: Neural sparse pruning

**Scenario:** Your sparse index is 6.8× larger than BM25 (issue #946). You want
to set `prune_ratio` to shrink it without killing relevance.

**Command:**

```bash
ai-search-tuner --corpus ./docs --qrels ./qrels.json \
  --mode sparse
```

**Output:** NDCG@10 vs index-size Pareto showing:

- Unpruned: NDCG@10 0.68, 5.0 GB
- `prune_ratio=0.1` (max_ratio) recommended: NDCG@10 0.67 (−1%), 3.0 GB (−40%)
- `prune_ratio=0.3`: NDCG@10 0.62 (−9%), 1.8 GB (too aggressive, flagged)

Plus two-phase processor config (`two_phase_parameter.enabled=true`, free
latency win).

### Use case 3: Hybrid weight tuning

**Scenario:** You're hand-guessing `[0.3, 0.7]` for dense:sparse weights (issue
#1273). You want the empirically optimal ratio.

**Command:**

```bash
ai-search-tuner --corpus ./docs --qrels ./qrels.json \
  --mode hybrid
```

**Output:** NDCG@10 vs latency Pareto showing:

- Dense-only: NDCG@10 0.51, 45ms p95
- Sparse-only: NDCG@10 0.54, 62ms p95
- Hybrid 0.3/0.7 (your guess): NDCG@10 0.56, 78ms p95
- **Hybrid 0.6/0.4 recommended**: NDCG@10 0.61 (+9% vs best standalone), 71ms p95

Plus the search-pipeline JSON with `normalization_processor` (min_max) and
`combination` (arithmetic_mean, weights=[0.6,0.4]).

## Known limitations & roadmap

- **Quantization enumeration** (FP16/PQ/scalar/binary) is detected at runtime
  from what the cluster supports; full enumeration is engine/version-dependent.
  The tool always includes fp32 and adds fp16 for OpenSearch 2.13+; more
  aggressive quantization is roadmap.
- **Hybrid v1 sweeps weights only** at fixed `min_max` + `arithmetic_mean`.
  Full normalization/combination permutation is roadmap.
- **Sparse ANN (SEISMIC)** mode is implemented but requires OpenSearch 3.3+.
- **Exact brute-force ground truth** is O(N × queries) and is computed on a
  *sample* only; document scale caveats in reports.
- **Config-space pruning** is agentic but greedy; exhaustive Cartesian sweeps
  are out of scope.

## Further reading

- `references/methodology.md` — quality@k reference table per mode, exact vs
  approximate semantics, how recall ground truth is generated.
- `references/parameters.md` — verified tunable-parameter tables for dense,
  sparse rank_features, sparse ANN, and hybrid (OpenSearch docs cross-referenced).
- `references/decision-guide.md` — when to use dense vs sparse vs hybrid
  (role-oriented: search engineer / ML engineer / SRE).
