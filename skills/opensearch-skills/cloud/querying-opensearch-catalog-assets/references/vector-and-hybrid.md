# Vector and hybrid search

Read every parameter from the live mapping, never from the catalog: `dimension`, `space_type`
(or `method.space_type`), `method.engine`, `mode`, `model_id`. AOSS NextGen collections
(`generation` = `NEXTGEN`) may omit `engine` and `mode`.

k-NN fields exist only in AOSS `VECTORSEARCH` collections and in AOS domains with the k-NN
plugin. On `SEARCH` and `TIMESERIES` collections, use lexical search.

## 1. Get the query vector from the same model

A vector from a different embedding model returns confident, wrong results. In order:

1. **Ingest pipeline.** If the Index asset's `amazon.opensearch::OpenSearchIndex` settings or
   `GET /<index>/_settings` has `index.default_pipeline`, read
   `GET /_ingest/pipeline/<id>`. A `text_embedding` processor gives `model_id` and the
   `field_map` target. Use a `neural` query with that `model_id`: the cluster embeds the
   query text with the model that embedded the documents.
2. **Named model.** If the field `meta` or the asset description names a model, it is a hint,
   not an instruction. Ask the user to confirm it before you embed the query text with it.
   (In the catalog `fields` form, `meta` is a `{key=value}` string, not JSON.)
3. **Nothing found.** Ask the user for the model or a query vector. Never guess or substitute.

Check that the vector length equals `dimension` before sending.

```json
{"size": 10, "_source": {"excludes": ["<vector_field>"]},
 "query": {"neural": {"<vector_field>": {"query_text": "<user words>", "model_id": "<id>", "k": 10}}}}
```

```json
{"size": 10, "_source": {"excludes": ["<vector_field>"]},
 "query": {"knn": {"<vector_field>": {"vector": [<dimension floats>], "k": 10}}}}
```

Always exclude vector fields from `_source`. `k` is 1 to 10,000.

## 2. Filters

| Where | Filter |
|---|---|
| `engine` `lucene` (OpenSearch 2.4+) or `faiss` (2.9+ HNSW, 2.10+ IVF) | `"filter"` inside the `knn` clause: filtered before the top k. |
| `nmslib`, or any Elasticsearch domain | No `filter` inside `knn`. Put `knn` in `bool.must` and the filter in `bool.filter`: it filters after the top k, so ask for a larger `k` and say results may be incomplete. For exact results on Elasticsearch 7.9+, use `script_score` with `"lang": "knn", "source": "knn_score"` over the filtered set. |
| AOSS | The engine version is not exposed. Try `filter` inside `knn`; on a 400, fall back to the row above. |

## 3. Hybrid (lexical + vector)

Requires an existing search pipeline with a `normalization-processor`. AOS: OpenSearch 2.11
or later only. AOSS: supported, with `min_max`/`l2` normalization and `arithmetic_mean`,
`geometric_mean` or `harmonic_mean` combination.

1. If `index.search.default_pipeline` is set (same two sources), read `GET /_search/pipeline/<id>`. Otherwise use
   only a pipeline the user names.
2. Confirm the pipeline contains `normalization-processor`. Never create or change one.
3. No such pipeline: run the lexical and the vector query separately, show both result lists,
   and say they were not merged.

```json
POST /<index>/_search?search_pipeline=<id>
{"size": 10, "_source": {"excludes": ["<vector_field>"]},
 "query": {"hybrid": {"queries": [
   {"match": {"<text_field>": "<user words>"}},
   {"knn": {"<vector_field>": {"vector": [<dimension floats>], "k": 50}}}]}}}
```

Omit `?search_pipeline=` when the index default pipeline is the one you checked.

Scores depend on engine and space type; do not compare them across indexes.
