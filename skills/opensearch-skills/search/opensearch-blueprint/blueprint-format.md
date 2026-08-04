# Blueprint Format

A blueprint has two representations generated from one source.

1. **The bundle** — `blueprint.json`, executable, fed to the cluster.
2. **The dense spec** — one continuous line, rendered by `blueprint-render`.

You author the bundle. The dense spec is derived, never hand-written — that is
what keeps documentation from drifting away from configuration.

---

## The bundle schema

```json
{
  "name": "MOVIE-SEARCH",
  "pitch": "hybrid movie discovery over 1.2m titles",
  "opensearch_version": "3.x",
  "index": "movies_v1",
  "settings": { "index": { "number_of_shards": 3, "knn": true, "analysis": {} } },
  "mappings": { "properties": {} },
  "ingest_pipeline": { "name": "movies_embed", "body": { "processors": [] } },
  "search_pipeline": { "name": "movies_hybrid", "body": { "phase_results_processors": [] } },
  "ism_policy": { "name": "movies_lifecycle", "body": { "policy": {} } },
  "queries": [ { "name": "hybrid_semantic", "body": { "query": {} } } ],
  "probes": [ { "analyzer": "title_en", "text": "The Lord of the Rings", "expect_tokens": [] } ]
}
```

| Key | Required | Purpose |
|---|---|---|
| `index` | yes | Index name. Version-suffix it (`movies_v1`) so reindexing is an alias swap. |
| `mappings.properties` | yes | Explicit field map. Dynamic mapping is not a design. |
| `settings` | no | Accepts both `{"index": {...}}` and flat form. |
| `ingest_pipeline` | no | Applied before the index is created. |
| `search_pipeline` | no | Required if any query uses a `hybrid` clause. |
| `ism_policy` | no | Lifecycle states and transitions. |
| `queries` | no | Named queries, each validated via `_validate/query`. |
| `probes` | no | Analyzer assertions run through `_analyze`. |

### Probes

A probe is an executable claim about tokenization:

```json
{ "analyzer": "title_en", "text": "The Lord of the Rings",
  "expect_tokens": ["lord", "ring"] }
```

With `expect_tokens`, the probe passes only on an exact match and
`blueprint-apply` exits non-zero on failure. Without it, the probe just reports
the token stream for you to read. Always include at least one probe per custom
analyzer.

---

## The five density techniques

These carry over from general dense-spec writing, but every slot is filled with
OpenSearch's own vocabulary. The point is that the rendered spec stays scannable
as the design grows past what a mapping JSON can show on one screen.

### 1. Slash-stack the option space

Never name one setting where the alternatives matter. Stack them so the reader
sees the decision, not just the outcome.

- Weak: `an hnsw index`
- Dense: `hnsw/lucene/l2, ef_construction 256, m 16`

The engine, space type, and parameters are the decision. Show all three.

### 2. OpenSearch-native jargon, never generic words

The whole point of the format is that the reader — human or agent — recognizes
a term and pulls in everything associated with it.

- Weak: `a filter to make search case-insensitive`
- Dense: `normalizer keyword_lc (lowercase/asciifolding)`
- Weak: `combine keyword and vector results`
- Dense: `normalization min_max, combination arithmetic_mean, weights 0.3/0.7`

See [opensearch-vocabulary.md](opensearch-vocabulary.md) for the term inventory.
If you do not know the correct term for something, look it up with
`search-docs` — do not fall back to a generic phrase.

### 3. CAPS sections, em-dash separated

Em-dashes separate top-level sections **only**. Inside a section, use commas.

```
INDEX — ANALYSIS — MAPPINGS — INGEST PIPELINE — SEARCH PIPELINE — ISM — QUERIES
```

`blueprint-render` emits exactly this structure, so you get it for free.

### 4. Hard numbers everywhere

Every quantity is a number. This is the highest-leverage rule, because in
OpenSearch a vague quantity is usually an unmade decision.

- Weak: `several shards` → Dense: `3 shards`
- Weak: `a large vector` → Dense: `dim 768`
- Weak: `keep logs a while` → Dense: `hot 7d → warm 30d → delete 90d`
- Weak: `long titles get truncated` → Dense: `ignore_above 256`

Shard count should follow from corpus size: target 10–50 GB per shard, so
`1.2m docs × 2 KB ≈ 2.4 GB` is **one** shard, not three. If you cannot justify
the number from the corpus, you have not finished Phase 1.

### 5. Ranges in parentheses

Ranges communicate the shape of a parameter without spending words.

- `ef_construction (128-512)` — recall/build-time tradeoff
- `m (16-48)` — graph degree, memory-linear
- `edge_ngram (2-20)` — autocomplete prefix window
- `shingle (2-3)` — phrase-ish matching without positions
- `refresh_interval (1s-30s)` — freshness vs indexing throughput
- `scaling_factor (10-100)` — `scaled_float` precision

---

## The no-list

Inside the rendered spec:

- No prose sentences. It is a manifest, not documentation.
- No vague quantifiers — always a hard number.
- No generic words where an OpenSearch term exists.
- No em-dashes inside a section — those separate sections only.
- No line breaks. One continuous block.

Inside the bundle:

- No `dynamic: true` on a designed index.
- No `text` field that is never matched on — make it `keyword`.
- No `keyword` field without `ignore_above` if values can be unbounded.
- No `knn_vector` without a probe-verified embedding path.

---

## Rendered output shape

`blueprint-render` produces:

```
3.x, MOVIE-SEARCH — hybrid movie discovery over 1.2m titles — INDEX movies_v1
(1 shards, 0 replicas, refresh_interval 30s, knn True) — ANALYSIS analyzer
title_en (standard tokenizer, lowercase/asciifolding/english_stop/english_stemmer),
normalizer keyword_lc (lowercase/asciifolding) — MAPPINGS title (text, analyzer
title_en), title.raw (keyword, ignore_above 256), embedding (knn_vector, dim 384,
hnsw/lucene/l2, ef_construction 256, m 16) — INGEST PIPELINE movies_embed
(text_embedding: title→embedding) — SEARCH PIPELINE movies_hybrid (normalization
min_max, combination arithmetic_mean, weights 0.3/0.7) — ISM movies_lifecycle
(hot → warm → delete) — QUERIES bm25_title, hybrid_semantic — validated against
_analyze / _validate/query / _search
```

Wrapped here for readability; the real output is one line. Paste it into a PR
description or a design doc — it is the whole index in one paragraph.

---

## Offering tuning knobs

After showing the rendered spec, offer 2–3 concrete adjustments, each with its
tradeoff stated as a number:

- drop `m` to 16 and `ef_construction` to 128 — roughly halves HNSW memory, costs
  a few points of recall@10
- shift hybrid weights 0.3/0.7 → 0.5/0.5 — favors exact terms, hurts paraphrase
- add `refresh_interval 30s` — better bulk throughput, 30s search lag

Keep it to four lines. The user iterates from there.
