# OpenSearch Vocabulary

The term inventory a blueprint draws from. Use the real name; never paraphrase.

---

## Field types

| Type | Use for | Watch out |
|---|---|---|
| `text` | Full-text matched fields | Not aggregatable or sortable without `fielddata` |
| `keyword` | Filters, facets, sorts, IDs | Set `ignore_above` (typically 256) on unbounded values |
| `wildcard` | Grep-like substring search on long strings | Larger than `keyword` |
| `integer` / `long` | Counts, IDs | Use the smallest type that fits |
| `scaled_float` | Ratings, prices | Needs `scaling_factor`; 10 gives one decimal place |
| `half_float` | Scores where 3 significant digits suffice | Half the storage of `float` |
| `date` | Timestamps | Pin `format`, e.g. `strict_date_optional_time\|\|epoch_millis` |
| `boolean` | Flags | — |
| `ip` | Addresses | Supports CIDR range queries |
| `geo_point` / `geo_shape` | Coordinates, regions | `geo_shape` is far more expensive |
| `nested` | Arrays of objects queried as units | Each element is a hidden doc; costs scale with array length |
| `join` | Parent/child | Single shard routing required |
| `knn_vector` | Dense embeddings | Needs `index.knn: true` and a `dimension` |
| `rank_features` | Sparse/learned term weights | Target of `sparse_encoding` |
| `rank_feature` | A single numeric relevance signal | Use `positive_score_impact: false` for "lower is better" |
| `alias` | Rename without reindex | Query-time only |
| `percolator` | Stored queries matched against documents | Reverse search |

**Multi-fields** — index one source several ways:

```json
"title": {
  "type": "text", "analyzer": "title_en",
  "fields": {
    "raw": { "type": "keyword", "ignore_above": 256 },
    "ac":  { "type": "text", "analyzer": "title_autocomplete" }
  }
}
```

---

## Analysis chain

Order is always: `char_filter` → `tokenizer` → `filter`.

**Char filters** — `html_strip`, `mapping`, `pattern_replace`

**Tokenizers** — `standard`, `whitespace`, `keyword`, `pattern`, `uax_url_email`,
`ngram`, `edge_ngram`, `path_hierarchy`, `char_group`, `classic`, `letter`,
`simple_pattern`, `simple_pattern_split`, `thai`

**Token filters** — `lowercase`, `uppercase`, `asciifolding`, `stop`, `stemmer`,
`snowball`, `kstem`, `porter_stem`, `keyword_marker`, `keyword_repeat`,
`remove_duplicates`, `shingle`, `ngram`, `edge_ngram`, `synonym`,
`synonym_graph`, `word_delimiter_graph`, `flatten_graph`, `elision`,
`common_grams`, `unique`, `length`, `limit`, `trim`, `truncate`, `reverse`,
`pattern_capture`, `pattern_replace`, `phonetic`, `stemmer_override`,
`decimal_digit`, `cjk_bigram`, `cjk_width`, `min_hash`, `multiplexer`,
`condition`, `predicate_token_filter`, `delimited_payload`, `hunspell`

**Normalizers** — keyword-only, no tokenizer. Filters limited to the
character-level set (`lowercase`, `asciifolding`, `trim`, `pattern_replace`, …).
This is how you get case-insensitive **filters** without making a field `text`.

### Patterns worth knowing

- **Autocomplete** — index with `edge_ngram (2-20)`, search with `standard`.
  Always split `analyzer` and `search_analyzer`, or every query term is itself
  n-grammed and precision collapses.
- **Stemming with exceptions** — `keyword_marker` (protect terms) before
  `stemmer`, or `stemmer_override` for specific mappings.
- **Phrase-ish matching cheaply** — `shingle (2-3)` instead of positional phrase
  queries.
- **Search-time synonyms** — put `synonym_graph` in `search_analyzer` only.
  Index-time synonyms cannot be changed without a reindex.

---

## k-NN / vector search

```json
"embedding": {
  "type": "knn_vector", "dimension": 384,
  "method": { "name": "hnsw", "engine": "lucene", "space_type": "l2",
              "parameters": { "ef_construction": 256, "m": 16 } }
}
```

| Engine | Space types | Notes |
|---|---|---|
| `lucene` | `l2`, `cosinesimil`, `innerproduct` | Native segment merge, filter-aware |
| `faiss` | `l2`, `innerproduct`, `cosinesimil`, `hamming` | Supports PQ/SQ quantization |
| `nmslib` | `l2`, `cosinesimil`, `innerproduct`, `l1`, `linf` | Legacy |

Parameters:

- `m (16-48)` — graph degree. Memory grows roughly linearly.
- `ef_construction (128-512)` — build-time candidate list. Higher = better
  recall, slower indexing. Must be ≥ `m`.
- `ef_search` — query-time candidate list, set per search.

Requires `"index": { "knn": true }` in settings.

---

## Pipelines

### Ingest processors

`text_embedding` (dense), `sparse_encoding` (learned sparse),
`text_image_embedding` (multimodal), `text_chunking`, `set`, `script`, `rename`,
`remove`, `split`, `trim`, `lowercase`, `date`, `grok`, `dissect`, `foreach`,
`json`, `convert`, `fingerprint`

```json
{ "text_embedding": { "model_id": "<id>", "field_map": { "title": "embedding" } } }
```

Attach with `"index": { "default_pipeline": "movies_embed" }`.

### Search pipeline processors

- **Phase results** — `normalization-processor` (required for `hybrid`)
- **Request** — `filter_query`, `neural_query_enricher`, `script`
- **Response** — `rename_field`, `rerank`, `collapse`, `truncate_hits`,
  `personalize_search_ranking`

```json
{ "normalization-processor": {
    "normalization": { "technique": "min_max" },
    "combination": { "technique": "arithmetic_mean",
                     "parameters": { "weights": [0.3, 0.7] } } } }
```

Normalization: `min_max`, `l2`, `z_score`.
Combination: `arithmetic_mean`, `geometric_mean`, `harmonic_mean`.

**Weights must sum to 1.0 and their count must equal the number of `hybrid`
sub-queries.** Both are linted.

---

## Query clauses

**Full text** — `match`, `match_phrase`, `match_phrase_prefix`, `multi_match`
(types: `best_fields`, `most_fields`, `cross_fields`, `phrase`, `bm25`),
`query_string`, `simple_query_string`, `intervals`

**Term-level** — `term`, `terms`, `terms_set`, `range`, `prefix`, `wildcard`,
`regexp`, `fuzzy`, `ids`, `exists`

**Compound** — `bool` (`must`/`filter`/`should`/`must_not`), `dis_max`,
`function_score`, `boosting`, `constant_score`

**Neural** — `knn`, `neural`, `neural_sparse`, `hybrid`

**Relevance** — `rank_feature`, `distance_feature`, `script_score`

Put anything non-scoring in `filter`, not `must` — filters are cached and skip
scoring entirely.

---

## Aggregations

**Bucket** — `terms`, `composite` (paginates, use for high cardinality),
`date_histogram`, `histogram`, `range`, `date_range`, `filters`, `nested`,
`significant_text`, `sampler`, `diversified_sampler`, `multi_terms`

**Metric** — `avg`, `sum`, `min`, `max`, `stats`, `extended_stats`,
`cardinality` (set `precision_threshold`), `percentiles`, `percentile_ranks`,
`top_hits`, `scripted_metric`

**Pipeline** — `derivative`, `moving_avg`, `moving_fn`, `cumulative_sum`,
`bucket_script`, `bucket_selector`, `bucket_sort`, `serial_diff`

`terms` on a high-cardinality field is a memory hazard — use `composite`.

---

## Index settings

| Setting | Range | Effect |
|---|---|---|
| `number_of_shards` | 1–N | Fixed at creation. Target 10–50 GB per shard. |
| `number_of_replicas` | 0–N | Use `0` on single-node dev clusters. |
| `refresh_interval` | `1s`–`30s`, `-1` | Higher = faster bulk indexing, staler search. |
| `codec` | `default`, `best_compression` | `best_compression` trades CPU for ~15–25% disk. |
| `knn` | bool | Must be `true` for `knn_vector`. |
| `max_result_window` | default `10000` | Raise only if you cannot use `search_after`. |
| `default_pipeline` | pipeline name | Ingest pipeline applied to every write. |

Deep pagination: use `search_after` with a Point-in-Time, never `from`/`size`
past a few thousand.

---

## ISM lifecycle

States and their actions:

- **hot** — `rollover` (`min_size`, `min_doc_count`, `min_index_age`)
- **warm** — `force_merge` (`max_num_segments: 1`), `replica_count`, `shrink`
- **cold** — `close`, `snapshot`
- **delete** — `delete`

Transitions use `min_index_age`, `min_size`, `min_doc_count`. Every
`state_name` in a transition must be a defined state — this is linted.

---

## Useful diagnostic APIs

```
GET  <index>/_analyze                 # prove tokenization
GET  <index>/_validate/query?explain  # syntax + field resolution
POST <index>/_search?explain=true     # per-document score breakdown
GET  <index>/_mapping
GET  <index>/_settings
GET  _cat/indices?v&s=store.size:desc
GET  _cat/shards/<index>?v
GET  <index>/_stats
GET  _plugins/_ism/explain/<index>
```

`_analyze` and `_validate/query` are the two cheapest ways to be sure a design
is right before loading data. Use them.
