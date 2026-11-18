# ML Inference Ingest Processor Guide

The `ml_inference` ingest processor calls a registered model while a document is indexed and
writes the result into `_source`. Use it for enrichment you want to filter, aggregate, or search
on later: embeddings, classification, NER, PII redaction, summaries.

- Official field reference: [ML inference processor](https://docs.opensearch.org/latest/ingest-pipelines/processors/ml-inference/). This guide covers only the patterns and pitfalls that reference leaves out.
- Platform differences (AOSS NextGen limits, IAM): [ml_inference_platforms.md](ml_inference_platforms.md)
- Connector blueprints, output JSONPath per model, model choice: [connector_patterns.md](connector_patterns.md)
- Worked example (chained sentiment + NER): [verified_examples.md](verified_examples.md#example-1-ingest-pipeline--chained-sentiment--ner)
- Query-time and response-time processors: [ml_inference_search_pipeline_guide.md](ml_inference_search_pipeline_guide.md)

---

## 1. When to use it (and when not to)

| Need | Use |
|---|---|
| Embed one text field for kNN, standard embedding model | `text_embedding` processor + `neural` query ([opensearch_semantic_search_guide.md](opensearch_semantic_search_guide.md)). Simpler. |
| Embed nested fields, array elements, or several fields with one processor | `ml_inference` |
| Call an LLM (classification, NER, redaction, summary) at write time | `ml_inference` |
| One LLM, several tasks | `ml_inference` with a different `model_config.system_prompt` per processor |

`ml_inference` reads input with JSONPath (`metadata.content`, `chunks[0]`, `chunks`), so the
document usually needs no reshaping before the model call.

---

## 2. Fields whose defaults cause mistakes

| Field | Default | What to know |
|---|---|---|
| `input_map` | — | Keys must equal the connector's `${parameters.X}` names. Values are document paths. |
| `output_map` | — | Keys are target fields. Values are JSONPath into the model response. |
| `full_response_path` | `false` for remote models, `true` for local | Sets the JSONPath root. `false`: the model response body (`dataAsMap`). `true`: the full `inference_results` envelope. |
| `model_config` | — | Overrides connector `parameters` (e.g. `system_prompt`, `max_tokens`) without re-registering the model. |
| `ignore_missing` | `false` | `true` skips the processor when the input field is absent. |
| `ignore_failure` | `false` | `true` indexes the document without the enriched field when the model call fails. |

The `$.` prefix in JSONPath is optional: `content[0].text` and `$.content[0].text` are read the same way.

---

## 3. Remote vs local models

**Remote (connector-based)** — Bedrock, SageMaker, OpenAI, etc.

```json
{
  "input_map":  [{ "inputText": "title" }],
  "output_map": [{ "title_embedding": "$.embedding" }]
}
```

`inputText` matches `${parameters.inputText}` in the Titan connector's `request_body`.

**Local (in-cluster)** — not available on AOSS NextGen. `function_name` and `model_input` are
required; the processor rejects a local model without `model_input`.

```json
{
  "function_name": "text_embedding",
  "model_input": "{ \"text_docs\": ${input_map.text_docs} }",
  "input_map":  [{ "text_docs": "description" }],
  "output_map": [{ "description_embedding": "$.inference_results[0].output[0].data" }]
}
```

---

## 4. Input and output patterns

| Pattern | `input_map` | `output_map` | Model calls per doc |
|---|---|---|---|
| Single field | `[{"inputText": "review_text"}]` | `[{"review_embedding": "$.embedding"}]` | 1 |
| Nested field | `[{"inputText": "metadata.content"}]` | same shape | 1 |
| Array element | `[{"inputText": "chunks[0]"}]` | same shape | 1 |
| Whole array (model must accept a list) | `[{"texts": "chunks"}]` | `[{"chunk_embeddings": "$.embeddings"}]` | 1 |
| Several fields | `[{"inputText": "title"}, {"inputText": "description"}]` | `[{"title_embedding": "$.embedding"}, {"description_embedding": "$.embedding"}]` | 1 per entry |

For several fields, the Nth `output_map` entry reads the result of the Nth `input_map` entry.

**Whole array**, with a connector that accepts a list:

```json
"request_body": "{ \"texts\": ${parameters.texts}, \"input_type\": \"search_document\" }"
```

Result: `_source.chunk_embeddings = [[0.02, ...], [0.05, ...], [-0.01, ...]]`.

**Chaining.** Processors run in order, and a later processor can read fields written by an earlier one:

```json
{
  "processors": [
    { "ml_inference": {
        "tag": "embed",
        "model_id": "<embedding_model>",
        "input_map":  [{ "inputText": "text" }],
        "output_map": [{ "text_embedding": "$.embedding" }] } },
    { "ml_inference": {
        "tag": "classify",
        "model_id": "<llm_model>",
        "input_map":  [{ "prompt": "text" }],
        "output_map": [{ "category": "$.content[0].text" }],
        "model_config": { "system_prompt": "Classify this text. Reply with one word: tech, sports, politics, entertainment." } } }
  ]
}
```

---

## 5. Verify before production

1. **`_predict`** on the model. Derive `input_map` keys from the connector parameters and the `output_map` path from the response.
   ```http
   POST /_plugins/_ml/models/<model_id>/_predict
   { "parameters": { "inputText": "test" } }
   ```
2. **`_simulate`** the pipeline with dirty data (quotes, newlines). Check the target field in `_source`.
   ```http
   POST /_ingest/pipeline/<name>/_simulate
   { "docs": [{ "_index": "test", "_source": { "text": "has \"quotes\" and \nnewlines" } }] }
   ```
3. **Index one document**, then read it back and check `_source`.

---

## 6. Gotchas

1. **`input_map` key ≠ connector placeholder.** If the connector uses `${parameters.inputText}`, the key must be `inputText`.
2. **Raw string substitution.** Values with quotes, backslashes, or newlines are substituted into `request_body` as-is and can break its JSON. This is why step 2 above uses dirty data.
3. **No automatic backfill.** A new or changed pipeline only affects new writes. Use `_reindex` for existing documents.
4. **Cost scales with `input_map` entries.** Each entry is one model call per document. Use a model that accepts a list and a single array entry when you can.
5. **`ignore_failure: true` hides gaps.** Documents are indexed without the enriched field. Prefer fixing the cause; if you enable it, check for documents missing the field after ingest.
