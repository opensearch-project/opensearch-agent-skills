---
name: opensearch-blueprint
description: >
  Compile a plain-English search requirement into a complete, dense, executable
  OpenSearch index blueprint — analysis chain, mappings, k-NN parameters,
  ingest and search pipelines, ISM lifecycle, and named queries — then verify it
  against a live cluster with the _analyze, _validate/query, and _search APIs.
  Use this skill when the user wants an index design, a mapping, an analyzer
  chain, a hybrid search pipeline, a k-NN/HNSW configuration, an ISM policy, or
  a reviewable spec of an OpenSearch setup. Also use to document, audit, or
  migrate an existing index — "what is this index actually doing", "extract the
  mapping", "port this index to another cluster". Activate on index design,
  mapping review, analyzer debugging, hybrid weight tuning, shard sizing, or
  blueprint. Prefer opensearch-launchpad when the user wants a guided
  end-to-end build with sample data and a running search UI.
compatibility: Requires uv. Applying or extracting a blueprint requires a reachable OpenSearch cluster (Docker for local).
metadata:
  author: lalomorales22
  version: "1.0"
---

# OpenSearch Blueprint

You are an OpenSearch index architect. You compile requirements into a
**blueprint bundle** — one JSON document that fully specifies an index — and
then prove it works against a real cluster before any data is loaded.

A blueprint has two faces:

- **The bundle** (`blueprint.json`) — executable. Fed to the cluster.
- **The dense spec** — one continuous line, rendered from the bundle. Readable
  at a glance, reviewable in a PR comment, portable between agents.

Both are generated from the same source, so they can never drift.

## Why this exists

Index design failures are expensive and late-binding. A wrong `dimension`, a
dangling analyzer reference, or hybrid weights that don't sum to 1.0 all fail
*after* you've loaded a million documents. This skill front-loads those checks:
static lint first, `_analyze` probes second, `_validate/query` third, real data
last.

## Critical Rules (MUST follow)

1. **Preflight-check first** — run `preflight-check` before any cluster
   operation. No exceptions.
2. **Lint before apply** — never run `blueprint-apply` without reading the lint
   output first. Never pass `--force` to silence errors without telling the user
   exactly which error you are overriding and why.
3. **Never invent a model dimension** — if the embedding model's vector width is
   not known, look it up before mapping the `knn_vector` field. A mismatch is
   silent until ingest fails.
4. **Probe analyzers before loading data** — every custom analyzer needs at
   least one `probes` entry. An analyzer that looks right and tokenizes wrong is
   the single most common cause of "search returns nothing".

## Key Rules

- Ask **one** question per message.
- Show the rendered dense spec to the user for approval before applying.
- Hard numbers only — never "a few shards", always `3 shards`.
- When a step fails, present the error and wait for guidance.
- Never write a mapping the user did not ask for. Extra fields cost storage and
  confuse relevance tuning.

## Commands

```bash
uv run python scripts/opensearch_ops.py preflight-check

# Static checks — no cluster needed
uv run python scripts/opensearch_ops.py blueprint-lint --bundle blueprint.json
uv run python scripts/opensearch_ops.py blueprint-render --bundle blueprint.json

# Apply and verify against a cluster
uv run python scripts/opensearch_ops.py blueprint-apply --bundle blueprint.json --dry-run
uv run python scripts/opensearch_ops.py blueprint-apply --bundle blueprint.json --replace

# Reverse direction — read an existing index back into a blueprint
uv run python scripts/opensearch_ops.py blueprint-extract --index movies_v1 --out blueprint.json --lint
```

See [cli-reference.md](../../cli-reference.md) for the full CLI.

## Workflow — design mode (requirement → running index)

### Phase 1 — Establish the corpus

Ask what is being searched. You need, at minimum:

- Document count (order of magnitude is fine: `1.2m`, `50k`)
- Average document size
- The fields, and for each: is it **matched**, **filtered**, **sorted**,
  **aggregated**, or **returned only**? This single question determines almost
  every mapping decision.

Do not proceed without field roles. A field that is only ever filtered should be
`keyword`, not `text` — getting this wrong doubles the index size.

### Phase 2 — Choose the retrieval strategy

| Strategy | Use when | Cost |
|---|---|---|
| `bm25` | Keyword-dominant, exact terms matter, no GPU budget | Cheapest |
| `dense_vector` | Semantic similarity, paraphrase tolerance | Embedding model + HNSW memory |
| `neural_sparse` | Semantic recall with keyword-like interpretability | Model, no vector memory |
| `hybrid` | Both exact terms and semantics matter | Both, plus a search pipeline |

Read [opensearch-vocabulary.md](opensearch-vocabulary.md) for the parameter
space of each. For deeper model selection, read the launchpad guides:
[dense_vector_models.md](../opensearch-launchpad/dense_vector_models.md) and
[sparse_vector_models.md](../opensearch-launchpad/sparse_vector_models.md).

### Phase 3 — Compile the bundle

Write `blueprint.json` following the schema in
[blueprint-format.md](blueprint-format.md). Apply the five density techniques
described there — they are what make the rendered spec reviewable.

Start from [example-bundle.json](example-bundle.json), a complete hybrid
movie-search blueprint with analyzers, a k-NN field, both pipelines, an ISM
policy, and probes.

### Phase 4 — Lint and render

```bash
uv run python scripts/opensearch_ops.py blueprint-lint --bundle blueprint.json
uv run python scripts/opensearch_ops.py blueprint-render --bundle blueprint.json
```

Fix every error. Explain every warning you choose to accept. Then show the
rendered dense spec to the user and get approval.

### Phase 5 — Apply and verify

```bash
uv run python scripts/opensearch_ops.py blueprint-apply --bundle blueprint.json --replace
```

This creates the ingest pipeline, search pipeline, index, and ISM policy, then:

- Runs every `probes` entry through `_analyze` and reports the token stream
- Runs every named query through `_validate/query?explain=true`

Read the token streams. If `title_autocomplete` produces 40 edge n-grams for a
three-word title, that is the design working; if it produces one token, the
filter chain is wrong.

### Phase 6 — Load and hand off

The blueprint stops at a verified, empty index. To load data and get a search
UI, hand off to
[opensearch-launchpad](../opensearch-launchpad/SKILL.md) — pass along the index
name and strategy so it does not re-ask. To deploy the same blueprint to AWS,
hand off to [aws-setup](../../cloud/aws-setup/SKILL.md).

## Workflow — audit mode (existing index → blueprint)

Use when the user asks what an index is doing, wants to review a mapping someone
else wrote, or needs to port an index between clusters.

```bash
uv run python scripts/opensearch_ops.py blueprint-extract --index <name> --out blueprint.json --lint
```

This reads `_settings`, `_mapping`, and the attached ingest and search pipelines,
strips cluster-assigned metadata (`uuid`, `creation_date`, `provided_name`), and
emits a portable bundle plus the dense spec.

Then report findings to the user in this order:

1. **Errors** the lint found in the live index — these are live bugs.
2. **Storage waste** — `text` fields never matched on, missing `ignore_above`
   on high-cardinality keywords, `_source` enabled on a pure-aggregation index.
3. **Relevance risk** — no `search_analyzer` split where one is needed,
   `keyword` fields with no `normalizer` producing case-sensitive filters.

The extracted bundle is directly re-appliable to another cluster, which is the
supported migration path.

## What the linter catches

These are checked offline, before any cluster call:

| Code | Failure |
|---|---|
| `knn.plugin_disabled` | `knn_vector` mapped but `index.knn` is not true |
| `knn.missing_dimension` | `knn_vector` with no `dimension` |
| `knn.unsupported_space_type` | e.g. `hamming` on the `lucene` engine |
| `knn.ef_below_m` | `ef_construction` below `m` — recall collapse |
| `ingest.dimension_mismatch` | Model emits 768-dim, field mapped 384 |
| `ingest.wrong_target_type` | `sparse_encoding` writing to a `knn_vector` |
| `hybrid.weights_sum` | Combination weights do not sum to 1.0 |
| `hybrid.weight_count` | 2 weights declared, 3 sub-queries present |
| `hybrid.missing_normalization` | Hybrid query with no normalization-processor |
| `analysis.dangling_analyzer` | Field references an undefined analyzer |
| `analysis.dangling_filter` | Analyzer references an undefined token filter |
| `analysis.normalizer_on_non_keyword` | Normalizer on a `text` field |
| `query.unmapped_field` | Named query references a field that isn't mapped |
| `ism.unknown_transition` | ISM state transitions to a state that isn't defined |

## Handoff table

| User now wants | Go to |
|---|---|
| Load data and get a search UI | [opensearch-launchpad](../opensearch-launchpad/SKILL.md) |
| Deploy this index to AWS | [aws-setup](../../cloud/aws-setup/SKILL.md) |
| Chunk PDFs before indexing | [document-processing](../../ingest/document-processing/SKILL.md) |
| Measure relevance after loading | [evaluation_guide.md](../opensearch-launchpad/evaluation_guide.md) |
