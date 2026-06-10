# ML Inference Processor Guide

The `ml_inference` processor calls a registered ML model during ingest (index time), search request, or search response. This guide focuses on **how to configure it** — every field, every pattern, with examples.

For search-time specific patterns (request/response processors), see [`ml_inference_search_pipeline_guide.md`](ml_inference_search_pipeline_guide.md).

For end-to-end verified examples on AOSS V2 (ingest, search request, search response), see [`verified_examples.md`](verified_examples.md).

For connector blueprints and model selection, see [`connector_patterns.md`](connector_patterns.md).

---

## 1. Benefits and Use Cases

The `ml_inference` processor's key strength is **JSONPath-based flexibility** — it can read any field from your document (nested objects, array elements, specific positions) and map it directly to the model's expected input format. No preprocessing, no data reshaping, no custom scripting.

### Why use `ml_inference`

- **No preprocessing layer needed** — JSONPath extracts exactly what the model needs, regardless of document structure
- **Supports any model type** — embeddings, LLMs, classifiers, rerankers — all through the same processor configuration
- **Handles complex document structures natively** — nested fields, arrays of text, multi-value fields
- **One model, multiple tasks** — override `model_config.system_prompt` per processor to reuse a single LLM for sentiment, NER, summarization
- **Batch array input** — pass an entire array of texts to the model in one call, get back array of results
- **Multi-field per processor** — embed or infer on multiple document fields in one processor definition

### Recommended use cases

| Use Case | How `ml_inference` helps |
|---|---|
| **Semantic search (auto-embedding)** | Read text from any field path, generate vector, write to knn_vector field — works with nested docs and arrays |
| **Document classification** | Classify into categories (sentiment, language, intent, topic) at ingest time → stored as `keyword` for filtering/aggregation |
| **Named Entity Recognition (NER)** | Extract entities (PERSON, ORG, LOCATION) as structured JSON → enables faceted navigation |
| **PII redaction** | Redact sensitive data before it hits storage → compliance built into the pipeline |
| **Text summarization** | Generate short summary field for long documents → improves preview/display without loading full text |
| **Multi-language embedding** | Embed an array of text chunks in one call → supports chunked documents without splitting into sub-documents |
| **Search-time query rewriting** | (Request processor) Rewrite natural language queries into structured filters before search executes |
| **Search-time RAG synthesis** | (Response processor) Generate grounded answers from search results, per-hit summaries |

---

## 2. Configuration Fields

Every `ml_inference` processor has these fields:

```json
{
  "ml_inference": {
    "model_id": "<required>",
    "input_map": [<required>],
    "output_map": [<required>],
    "model_config": {},
    "tag": "",
    "ignore_missing": false,
    "ignore_failure": false,
    "one_to_one": false,
    "full_response_path": true
  }
}
```

### Field reference

| Field | Required | Description |
|---|---|---|
| `model_id` | Y | The ID of a registered + deployed model |
| `input_map` | Y | Array of objects mapping document fields → model input parameters |
| `output_map` | Y | Array of objects mapping model response JSONPath → target document fields |
| `model_config` | N | Override connector parameters at the pipeline level (e.g., `system_prompt`, `max_tokens`) |
| `tag` | N | Label for this processor (appears in `verbose_pipeline` output and error messages) |
| `ignore_missing` | N | If `true`, skip the processor when the source field doesn't exist in the document (default: `false`) |
| `ignore_failure` | N | If `true`, continue ingestion even if the model call fails (default: `false`) |
| `one_to_one` | N | **Search response processor only.** If `true`, runs the model once per hit. If `false` (default), batches all hits into one model call |
| `full_response_path` | N | If `true` (default for ingest), `output_map` JSONPath starts from the root of model response. If `false`, starts from `inference_results[0].output[0].dataAsMap` |

---

## 3. Remote Model vs Local Model

### Remote model (connector-based)

The model calls an external API (Bedrock, SageMaker, OpenAI, etc.) via a **connector**.

```
Register connector → Register model (function_name: "remote") → Deploy → Use
```

- `input_map` keys must match `${parameters.X}` placeholders in the connector's `request_body`
- `output_map` JSONPath navigates the model's HTTP response body
- See [connector blueprints](https://github.com/opensearch-project/ml-commons/tree/main/docs/remote_inference_blueprints/standard_blueprints) for ready-to-use templates

**Example:**
```json
{
  "input_map": [{ "inputText": "title" }],
  "output_map": [{ "title_embedding": "$.embedding" }]
}
```
Here `inputText` matches `${parameters.inputText}` in the Titan connector's `request_body`.

### Local model (built-in or uploaded)

The model runs inside OpenSearch (e.g., pre-trained sentence transformers, sparse models).

```
Register model (function_name: "text_embedding" / "sparse_encoding") → Deploy → Use
```

- `input_map` keys are the model's native input field names (typically `text_docs` for embedding models)
- `output_map` navigates the local model's response format
- Local models have a fixed response shape — check with `_predict` first

**Example (local embedding model):**
```json
{
  "input_map": [{ "text_docs": "description" }],
  "output_map": [{ "description_embedding": "$.inference_results[0].output[0].data" }]
}
```

### How to know which format?

**Always run `_predict` first** to see the exact input/output format:

```http
POST /_plugins/_ml/models/<model_id>/_predict
{
  "parameters": { "inputText": "test sentence" }
}
```

The response shows you:
- What parameter names the model expects → use these as `input_map` keys
- What the response JSON looks like → use JSONPath to write your `output_map`

---

## 4. `input_map` — How to Read Document Fields

`input_map` is an **array of objects**. Each object maps: `{ "<model_parameter>": "<document_field_path>" }`

### Single field input

```json
"input_map": [{ "inputText": "review_text" }]
```
Reads `_source.review_text` and sends it as `parameters.inputText` to the model.

### Nested field input

```json
"input_map": [{ "inputText": "metadata.content" }]
```
Reads `_source.metadata.content` (dot notation for nested objects).

### Array element input

```json
"input_map": [{ "inputText": "chunks[0]" }]
```
Reads the first element of the `chunks` array.

### Array field input (batch embedding)

```json
"input_map": [{ "texts": "chunks" }]
```
Reads the entire `chunks` array (e.g., `["text1", "text2", "text3"]`) and passes it to the model as an array parameter. The model must accept array input (e.g., Cohere embed, Titan with `texts` parameter).

### Multiple fields in one processor

```json
"input_map": [
  { "inputText": "title" },
  { "inputText": "description" }
]
```
Each entry triggers a separate model call. The first result maps to the first `output_map` entry, the second to the second.

---

## 5. `output_map` — How to Write Model Results

`output_map` is an **array of objects**. Each object maps: `{ "<target_field_in_source>": "<jsonpath_in_model_response>" }`

### Single output

```json
"output_map": [{ "sentiment": "$.content[0].text" }]
```
Reads `content[0].text` from the model response, writes it to `_source.sentiment`.

### Multiple outputs (paired with multiple inputs)

```json
"output_map": [
  { "title_embedding": "$.embedding" },
  { "description_embedding": "$.embedding" }
]
```
First output corresponds to first `input_map` entry, second to second.

### Array output (batch embedding)

```json
"output_map": [{ "chunk_embeddings": "$.embeddings" }]
```
If the model returns an array of vectors, writes the entire array to `_source.chunk_embeddings`.

### Common JSONPath per model family

| Model | JSONPath |
|---|---|
| Titan Embedding | `$.embedding` |
| Claude (Anthropic Messages) | `$.content[0].text` |
| Nova (Converse API) | `output.message.content[0].text` |
| Llama | `generation` |
| Cohere Embed | `$.embeddings` |
| OpenAI Chat | `choices[0].message.content` |
| Local embedding model | `$.inference_results[0].output[0].data` |

> **Tip:** `$.` prefix behavior differs by processor type. Ingest processors use `$.` to root at the full response. Search response processors omit `$.` (roots at `dataAsMap` automatically). Always verify with `_predict` + `_simulate`.

---

## 6. `model_config` — Override Connector Parameters

`model_config` lets you override any connector parameter at the pipeline level **without re-registering the model**. Most useful for LLM tasks where the same model serves different purposes.

```json
{
  "ml_inference": {
    "model_id": "<model_id>",
    "input_map": [{"prompt": "review"}],
    "output_map": [{"sentiment": "$.content[0].text"}],
    "model_config": {
      "system_prompt": "You are a sentiment classifier. Reply with one word: positive, negative, or neutral.",
      "max_tokens": 10,
      "temperature": 0
    }
  }
}
```

Any key in `model_config` overrides the same key in the connector's `parameters` block. This means **one model registration** can serve sentiment, NER, summarization, query rewriting — just vary `model_config` per processor.

---

## 7. Batch Inference Configuration

### Scenario: Array of texts → Array of embeddings

Document has `"chunks": ["para1", "para2", "para3"]`. You want to embed all chunks in one model call.

**Connector** must accept array input (e.g., Cohere embed blueprint with `texts` parameter):
```json
"request_body": "{ \"texts\": ${parameters.texts}, \"input_type\": \"search_document\" }"
```

**Processor:**
```json
{
  "ml_inference": {
    "model_id": "<cohere_embed_model>",
    "input_map": [{ "texts": "chunks" }],
    "output_map": [{ "chunk_embeddings": "$.embeddings" }]
  }
}
```

Result: `_source.chunk_embeddings` = `[[0.02, ...], [0.05, ...], [-0.01, ...]]`

### Scenario: Multiple fields, each embedded separately

Document has `title` and `description`. Each gets its own embedding.

**Processor:**
```json
{
  "ml_inference": {
    "model_id": "<titan_embed_model>",
    "input_map": [
      { "inputText": "title" },
      { "inputText": "description" }
    ],
    "output_map": [
      { "title_embedding": "$.embedding" },
      { "description_embedding": "$.embedding" }
    ]
  }
}
```

Each `input_map` / `output_map` pair runs a separate model call. Two calls per document in this case.

### Scenario: Chained processors (different models, different tasks)

```json
{
  "processors": [
    {
      "ml_inference": {
        "tag": "embed",
        "model_id": "<embedding_model>",
        "input_map": [{ "inputText": "text" }],
        "output_map": [{ "text_embedding": "$.embedding" }]
      }
    },
    {
      "ml_inference": {
        "tag": "classify",
        "model_id": "<classifier_model>",
        "input_map": [{ "prompt": "text" }],
        "output_map": [{ "category": "$.content[0].text" }],
        "model_config": {
          "system_prompt": "Classify this text. Reply with one word: tech, sports, politics, entertainment."
        }
      }
    }
  ]
}
```

Processors run in sequence. The second processor can read fields written by the first.

---

## 8. Verification Workflow

**Always follow this order:**

1. **`_predict`** — verify model input/output format:
   ```http
   POST /_plugins/_ml/models/<model_id>/_predict
   { "parameters": { "inputText": "test" } }
   ```
   → Confirm the response shape. Derive your `output_map` JSONPath from this.

2. **`_simulate`** — verify the pipeline works end-to-end:
   ```http
   POST /_ingest/pipeline/<name>/_simulate
   { "docs": [{ "_index": "test", "_source": { "text": "sample document" } }] }
   ```
   → Check `_source` in the result. Is the target field populated correctly?

3. **Index a test document** — verify the field is persisted:
   ```http
   POST /<index>/_doc
   { "text": "real document with special characters: \"quotes\" and \nnewlines" }
   ```
   → Search for it and check `_source`.

4. **For search pipelines** — use `verbose_pipeline=true`:
   ```http
   POST /<index>/_search?search_pipeline=<name>&verbose_pipeline=true
   { "query": { "match_all": {} } }
   ```
   → `processor_results` shows exactly what went in and came out of each processor.

---

## 9. Platform-Specific Notes

| | Open Source | Amazon OpenSearch Service (AOS) | AOSS (NextGen) |
|---|---|---|---|
| `model_config` override | Y | Y | Y |
| `model_input` field | Y | Y | N Not supported |
| Error messages | Full detail | Full detail | All 4xx masked as 403 |
| Pipeline creation | Immediate | Immediate | Eventually consistent (~30s) |
| Connector auth | Optional | IAM role required | IAM role mandatory |
| `_simulate` | Y | Y | Y (best debugging tool on AOSS) |

For full platform comparison, see [verified_examples.md](verified_examples.md) — "Platform Differences" section.

---

## 10. Common Gotchas

1. **`input_map` key must match connector's `${parameters.X}`.** If the blueprint has `${parameters.inputText}`, your `input_map` must use `inputText` as the key.

2. **Raw string substitution.** Field values containing quotes, backslashes, or newlines can break the connector's `request_body` JSON. Always `_simulate` with dirty data (quotes, newlines) before production ingest.

3. **`output_map` JSONPath differs between ingest and search response.** Ingest uses `$.` prefix; search response omits it. Always verify with `_predict` first.

4. **Ingest pipeline does NOT auto-reindex.** Changing the processor config only affects new documents. Use `_reindex` for backfill.

5. **Multiple `input_map` entries = multiple model calls.** Each entry is a separate inference. If cost/latency matters, consider using a model that accepts batch input (array) and use a single `input_map` entry with the array field.

6. **`ignore_failure: true`** — use cautiously. Silently skipping failures means some documents won't have the enriched field. Better to fix the root cause.
