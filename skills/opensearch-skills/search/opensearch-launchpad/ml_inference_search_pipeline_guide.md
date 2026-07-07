# ML Inference Search Pipeline Guide

Use this guide when the user wants to call a machine learning model **at query time or response time** — query rewriting, intent detection, multilingual routing, query expansion, LLM re-ranking, or grounded RAG answer synthesis. The same `ml_inference` processor handles all of these via two variants: **search request** processor and **search response** processor.

> Related guides
> - For ingest-time enrichment (auto-embeddings, classification at index time), see [`ingestion/ml-inference-ingest/`](../../ingestion/ml-inference-ingest/SKILL.md) instead.
> - For the simpler pre-built `neural` query (text → kNN), see [`opensearch_semantic_search_guide.md`](opensearch_semantic_search_guide.md). Use `ml_inference` request processor only when you need advanced behavior `neural` query can't express.
> - For agentic search (LLM-driven multi-step retrieval), see [`agentic_search_guide.md`](agentic_search_guide.md). `ml_inference` is a lighter, single-shot tool — use it when you need predictable inline LLM enrichment, not multi-step planning.

---

## 1. The three substitution namespaces

The `ml_inference` processor has three places where templates substitute values, each with its own scope. Mixing them up is the most common configuration error.

| Namespace | Where it appears | Source of values |
|---|---|---|
| `${parameters.X}` | Inside the **connector's** `request_body` template | Connector's static `parameters` map + per-request parameters (from `input_map` keys) |
| `${input_map.X}` | Inside the processor's `model_input` field (open-source) — **not supported on AOSS NextGen** | The JSONPath value extracted by `input_map[X]` |
| `${X}` (where `X` is an `output_map` key) | Inside the processor's `query_template` (request processor) or `model_config.prompt` (response processor) | The model's prediction output, looked up by the JSONPath in `output_map[X]` |

**These do not overlap.** `output_map` keys are never visible in the connector body. `input_map` keys are never visible in `query_template`. Most user errors come from forgetting this.

---

## 2. Search request processor — query rewriting

### When to use

The user wants the pipeline to **modify the query** based on an LLM call before retrieval runs. Common patterns:

- Detect query language → add a `language` filter (multilingual routing)
- Classify intent → choose which index/filter/boost set to apply
- Spell-correct or expand query → rewrite the `must` clause
- Extract entities from the query → add structured filters

### Two ways to wire it

**Pattern A — `query_template` rewrite** (the model output drives the rewritten query)

The pipeline replaces the user's query body entirely with `query_template`, substituting model output via `${output_map_key}`. Best when the model produces a vector or score the rewritten query directly consumes (e.g. NL → kNN with a Titan embedding).

```http
PUT /_search/pipeline/nl-to-knn
{
  "request_processors": [{
    "ml_inference": {
      "model_id": "<titan_embed_model>",
      "function_name": "remote",
      "input_map":  [{ "inputText": "query.match.title.query" }],
      "output_map": [{ "query_vector": "$.embedding" }],
      "query_template": "{\"size\":3,\"query\":{\"knn\":{\"title_embedding\":{\"vector\":${query_vector},\"k\":3}}}}"
    }
  }]
}
```

User sends `{ "query": { "match": { "title": { "query": "space exploration" } } } }`. Pipeline embeds it and replaces the whole query with a kNN over `title_embedding`.

**Pattern B — `output_map` JsonPath direct rewrite** (overwrite an existing slot)

The pipeline writes the model output to a specific path inside the existing query body. The user's query stays mostly intact — only the targeted slot is overwritten. Best for adding filters or modifying boost values where the user controls the outer query shape.

```http
PUT /_search/pipeline/lang-route
{
  "request_processors": [{
    "ml_inference": {
      "model_id": "<lang_detect_model>",
      "function_name": "remote",
      "input_map":  [{ "text": "query.bool.must[0].match.text.query" }],
      "output_map": [{ "query.bool.filter[0].term.language.value": "output.message.content[0].text" }]
    }
  }]
}
```

The user must provide a placeholder filter slot in their request:
```json
{
  "query": {
    "bool": {
      "must":   [{ "match": { "text": { "query": "Carlos en Madrid" } } }],
      "filter": [{ "term":  { "language": "PLACEHOLDER" } }]
    }
  }
}
```

The pipeline overwrites `"PLACEHOLDER"` with the detected language code. The literal string `"PLACEHOLDER"` doesn't matter — anything works as long as the JSONPath resolves to an existing value the processor can `JsonPath.set(...)` into. This is enforced by `validateRequiredOutputMappingFields` — paths starting with `query.*` must already exist.

### Critical gotchas

1. **`input_map` key must match the connector's `${parameters.X}` placeholder.** If the connector's `request_body` template has `${parameters.text}`, the pipeline must populate a parameter named `text`. A mismatch surfaces as `Invalid payload: ... parameter placeholder not filled in payload: text`.

2. **Don't extract from a parent match clause.** `query.bool.must[0].match.text` returns the entire normalized match clause object (with `auto_generate_synonyms_phrase_query`, `boost`, etc.) once OpenSearch has parsed the request. JSONPath needs to land on the leaf string: `query.bool.must[0].match.text.query` (note the trailing `.query`).

3. **`query_template` only sees `output_map` keys.** `${input_map.X}` substitution is supported only inside `model_input` — and `model_input` is **not supported on AOSS NextGen**. If you need to replay the user's text in the rewritten query alongside the model output, use Pattern B (write into placeholder slots) instead of Pattern A.

4. **AOSS NextGen does not register the `ext.ml_inference` extension.** Use `$._request.<jsonpath>` syntax (see Section 3) inside response processors instead — `ext.ml_inference` works only on managed/self-hosted OpenSearch.

---

## 3. Search response processor — RAG and per-hit enrichment

### When to use

The user wants the pipeline to **call an LLM after retrieval** with the hits as context, and attach the LLM's output to the search response. Common patterns:

- Cross-document RAG synthesis (one answer for the whole result set)
- LLM re-ranking (per-hit relevance score)
- Per-hit summarization or classification
- Citation extraction

### `one_to_one` controls the fundamental shape

| Setting | Behavior | Use it for |
|---|---|---|
| `one_to_one: false` (default) | One model call sees ALL hits. The processor aggregates each hit's `input_map` field into a `List<String>`. Use `${parameters.X.toString()}` to embed the list as a single string slot, OR use `${parameters.X}` (no quotes around it in the connector body) when the model's API expects a JSON array directly. Output is written either as a single value replicated across hits (string output) or fanned out per hit using `results[*]` indexing (array-aligned output). | **Cross-document synthesis** (RAG, summarization across results) AND **batch per-hit scoring** (the array fan-out pattern; see the rerank section for an AOSS verification caveat) |
| `one_to_one: true` | One model call per hit. Inputs are scalar (single hit's fields). Output is per-hit. | **Per-hit enrichment when the model can't batch** — e.g., a custom classifier whose API only accepts one document at a time |

### Cross-document RAG (the most common use case)

**Connector** — single `prompt` parameter. The pipeline assembles the full prompt template, passes it to the connector as `parameters.prompt`:

```http
POST /_plugins/_ml/connectors/_create
{
  "name": "Claude RAG cross-doc",
  "version": "1.0",
  "protocol": "aws_sigv4",
  "credential": { "roleArn": "arn:aws:iam::<account>:role/<connector-role>" },
  "parameters": {
    "service_name": "bedrock", "region": "us-west-2",
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 400, "temperature": 0
  },
  "actions": [{
    "action_type": "predict", "method": "POST",
    "url": "https://bedrock-runtime.us-west-2.amazonaws.com/model/us.anthropic.claude-sonnet-4-6/invoke",
    "headers": { "content-type": "application/json" },
    "request_body": "{\"anthropic_version\":\"${parameters.anthropic_version}\",\"max_tokens\":${parameters.max_tokens},\"temperature\":${parameters.temperature},\"messages\":[{\"role\":\"user\",\"content\":\"${parameters.prompt}\"}]}"
  }]
}
```

**Pipeline** — `model_config.prompt` builds the full prompt with `${parameters.context.toString()}`:

```http
PUT /_search/pipeline/rag-pipeline
{
  "response_processors": [{
    "ml_inference": {
      "model_id": "<claude_model>",
      "function_name": "remote",
      "input_map": [{
        "context":  "title",
        "question": "$._request.query.match.title.query"
      }],
      "output_map": [{ "rag_answer": "content[0].text" }],
      "model_config": {
        "prompt": "You are a search assistant. Answer the user's question using ONLY the provided context list. Each list element is one retrieved document. If none of the documents contain the answer, reply: I do not know based on the retrieved documents. Cite which document(s) support your answer. Keep the answer under 80 words.\n\nContext: ${parameters.context.toString()}\n\nQuestion: ${parameters.question.toString()}"
      }
    }
  }]
}
```

**Searching:**

```http
POST /<index>/_search?search_pipeline=rag-pipeline
{
  "size": 3,
  "_source": ["title", "rag_answer"],
  "query": { "match": { "title": { "query": "What is the largest volcano?" } } }
}
```

Every hit's `_source` carries the **same** `rag_answer` (one model call, output replicated across hits). Application reads it from any hit and renders the standard "answer + supporting hits" UX.

### Critical gotchas

1. **Use `${parameters.X.toString()}` — not `${parameters.X}` — when the input is a list.** When `one_to_one: false`, the processor builds a `List<String>` for each `input_map` key. Without `.toString()`, gson serializes the list as a JSON-array literal `["doc1","doc2"]` whose internal double quotes break the surrounding JSON string in the connector's `request_body`. Apache Commons StringSubstitutor's `.toString()` method call converts the list to Java's plain `[doc1, doc2]` representation (no quotes), which is safe to embed inside a string slot. This is the difference between RAG that works and RAG that returns 400/Forbidden.

2. **`$._request.<jsonpath>` is the canonical way to read the original request body inside a response processor.** AOSS NextGen does not register `ext.ml_inference`, so the older `ext.ml_inference.<key>` extension pattern fails on AOSS. Use `$._request.query.match.title.query` to pull the user's question from the original search request.

3. **`output_map` writes to `_source` (per-hit), not response-level `ext`.** On open-source ml-commons, output_map keys starting with `ext.ml_inference.` get redirected to a top-level `MLInferenceSearchResponse.params` extension — this avoids cross-hit duplication. On AOSS NextGen, that branch is missing: an `ext.ml_inference.X` key falls through and writes to `_source` under a literal dotted field name. Always assume the output goes per-hit; for RAG, reading from any one hit is the application pattern.

4. **`one_to_one: true` is NOT real cross-doc RAG, and usually NOT the right rerank shape either.** Each `one_to_one: true` call sees only one document, so RAG synthesis can't compare evidence and most calls return "I do not know"; rerank with `one_to_one: true` makes one API call per hit (50× the latency and cost vs. a batched rerank API). Default to `one_to_one: false` for both synthesis (string output replicated to every hit) and batch scoring (array output fanned out via `results[*]`). Reach for `one_to_one: true` only when the underlying model API genuinely cannot batch.

### Re-ranking with the `rerank` response processor

The `rerank` response processor (a distinct processor, not `ml_inference`) reorders hits and rewrites their `_score`. It has two rerank types:

- **`by_field`** — reorders by a numeric field already present on each hit. No model call. **Verified working on AOSS NextGen.**
- **`ml_opensearch`** — calls a cross-encoder model to score each (query, document) pair. Needs a registered cross-encoder. **Documented upstream; not verified end-to-end on AOSS NextGen in our testing (see caveat below).**

#### `by_field` rerank — verified on AOSS NextGen

Use this when each hit already carries a relevance score — either a score you computed at ingest time, or one produced by an upstream `ml_inference` response processor that wrote a per-hit field. The `rerank` processor just sorts by that field.

```http
PUT /_search/pipeline/rerank-byfield
{
  "response_processors": [
    {
      "rerank": {
        "by_field": {
          "target_field": "rerank_score",
          "keep_previous_score": true
        }
      }
    }
  ]
}
```

```http
POST /<index>/_search?search_pipeline=rerank-byfield
{
  "size": 5,
  "query": { "match": { "title": "keyword" } }
}
```

Hits come back ordered by `rerank_score` (descending). With `keep_previous_score: true`, each hit also carries a `previous_score` field holding the original BM25/kNN score — useful for debugging. Verified: a corpus where BM25 ranked docs `[0.18, 0.11, 0.09]` returned, after `by_field` rerank, in `rerank_score` order `[0.9, 0.5, 0.1]` with `previous_score` preserved.

**Pairing with `ml_inference`:** to produce the score field that `by_field` sorts on, run an `ml_inference` response processor first (writing e.g. `relevance_score` per hit via `one_to_one: false` + `results[*]` fan-out), then `by_field` to reorder by it. The `ml_inference` half of that chain is subject to the connector/model caveats in this guide — verify the scoring processor produces the field (`verbose_pipeline=true`) before relying on the chain.

#### `ml_opensearch` rerank (cross-encoder)

The `ml_opensearch` rerank type calls a cross-encoder model registered in OpenSearch. This works end-to-end on AOSS NextGen with remote cross-encoder models (e.g. Amazon Bedrock Rerank or Cohere Rerank via connector).

To set up cross-encoder rerank on AOSS NextGen:
1. Build and register the cross-encoder connector/model.
2. Test it with `_predict` (TextSimilarity input) **before** wiring the pipeline.
3. Create the `ml_opensearch` rerank pipeline and run a search with `verbose_pipeline=true`.
4. Confirm the `rerank` processor's `status` is `success`.

Upstream reference for the full pattern: [Cohere Rerank tutorial](https://github.com/opensearch-project/ml-commons/blob/main/docs/tutorials/ml_inference/rerank/ml_Inference_with_Cohere_Rerank_model.md) and the [rerank processor docs](https://docs.opensearch.org/latest/search-plugins/search-pipelines/rerank-processor/).

**Note on AOSS NextGen:** the `rerank` response processor type is in the curated allowlist (pipeline creation succeeds and the processor executes), distinct from `collapse` which is not (returns `400`). See Section 4 for the full allowlist.

### Debugging search pipeline issues

When a search pipeline returns an error, follow this chain:

1. **Confirm the model itself works.** Call `_predict` directly on the same model with the same parameters the pipeline would pass. If `_predict` succeeds, the model + IAM are good — the issue is in the pipeline.
2. **Run with `verbose_pipeline=true`.** This returns 200 even when a processor fails, with the per-processor `error` and `output_data` in `processor_results[]`. The processor-level error surfaces the real reason ("Some parameter placeholder not filled in payload: text", "cannot find field", etc.).
3. **Check input_map / connector parameter alignment.** The most common cause of pipeline errors is an `input_map` key that doesn't match a `${parameters.X}` placeholder in the connector's `request_body`.

### Symptom → cause cheat sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| `Invalid payload: parameter placeholder not filled` | `input_map` key doesn't match the connector's `${parameters.X}` placeholder | Align the `input_map` key name with the connector template placeholder |
| RAG answer appears as a literal field named `_source["ext.ml_inference.rag_answer"]` (with the dot in the key) on every hit | AOSS fork of `MLInferenceSearchResponseProcessor` lacks the `EXTENSION_PREFIX` write path. Output keys starting with `ext.ml_inference.` fall through to per-hit `_source` instead of the response-level `ext` block. | Rename the `output_map` key to a plain identifier like `rag_answer`. Read it from any one hit. |
| Rewritten query has `${input_map.X}` left as a literal string | The placeholder was used in the wrong field. `${input_map.X}` substitutes only inside `model_input`. `query_template` (request processor) substitutes only `output_map` keys; `model_config.prompt` (response processor) substitutes `${parameters.X}` and `${parameters.X.toString()}`. | If you wrote `${input_map.X}` in a `query_template`, switch to `${parameters.X}` and remember the input_map key must match a connector parameter. AOSS NextGen also doesn't expose `model_input`, so the workaround on AOSS is to bake the prompt into the connector's `request_body` and reference values via `${parameters.X}`. See Section 1. |
| `Invalid processor type collapse` when creating a search pipeline | The `collapse` response processor isn't in the AOSS NextGen allowlist. | Use `rerank` (which is allowlisted) or post-process client-side. |
| Bulk RAG response duplicates the same answer on every hit | This is by design when `output_map` writes to a `_source` field with `one_to_one: false` — one answer is replicated across all hits. Read it from any one hit; render the rest as supporting sources (Perplexity / Google AI Overviews UX pattern). | Not a bug — read from any hit |

---

## 4. AOSS NextGen specifics

The AOSS fork of `MLInferenceSearchRequestProcessor` and `MLInferenceSearchResponseProcessor` has been trimmed compared to upstream open-source ml-commons. When the user is on AOSS NextGen, apply these constraints:

| Feature | Open-source | AOSS NextGen |
|---|---|---|
| `ml_inference` ingest, request, response processors | Y | Y (NextGen only — Classic does not support `ml_inference`) |
| `model_input` field on processors | Y | N Not supported. Pass model parameters via the connector's `${parameters.X}` template instead |
| `ext.ml_inference.X` write to response-level extension | Y | N Falls through to per-hit `_source` (silent fallback) |
| `$._request.<jsonpath>` reads from request body | Y | Y |
| `$.X` JSONPath in output_map (per-hit `_source` write) | Y | Y |
| `query.X` JSONPath in output_map (rewrite existing slot) | Y | Y — but the path must already exist in the request body |
| `ext.ml_inference` SearchExtBuilder for passing params via the request `ext` block | Y | N Not registered on AOSS NextGen (typically surfaces as a `NamedWriteable not found` error). Use `$._request.<jsonpath>` syntax to read from the request body instead. |
| `set`, `script`, `remove` ingest processors | Y | N Curated allowlist — only `ml_inference`, `text_embedding`, and other ML-specific processors are exposed |
| `collapse` response processor | Y | N Returns `400: Invalid processor type collapse` |
| Bedrock cross-region inference profiles (`us.amazon.nova-micro-v1:0`, `us.anthropic.claude-...`) | Y | Y |

---

## 5. Choosing models

Pick the smallest model that handles the task. Different processors can use different models in the same pipeline.

| Task | Recommended Bedrock model | Why |
|---|---|---|
| Text embedding (NL → kNN) | `amazon.titan-embed-text-v2:0` (1024 dim, on-demand) | Fast, on-demand FM, well-supported by built-in pre/post-process functions |
| Language detection, intent classification, spell-correct | `us.amazon.nova-micro-v1:0` (cross-region inference profile) | Purpose-built for low-latency text classification; sub-second median latency |
| Per-hit re-ranking | `us.amazon.nova-micro-v1:0` or any small classifier | Per-hit calls accumulate latency, so smaller is better |
| RAG answer synthesis | `us.anthropic.claude-sonnet-4-6` or `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Reasoning-quality matters more than latency for synthesis |
| Multi-step RAG with citations | Claude Sonnet 4.6 | Best instruction-following for grounded synthesis prompts |

For non-Bedrock connectors (SageMaker, OpenAI, self-hosted), the same shape applies — only the connector's `url` and `request_body` change. The pipeline itself is connector-agnostic.

---

## 6. Verification workflow

For every pipeline you build, verify in this order:

1. **Direct `_predict` first.** Call the model directly to confirm the connector + IAM are good before adding any pipeline complexity:
   ```bash
   POST /_plugins/_ml/models/<model_id>/_predict
   { "parameters": { "text": "Bonjour le monde" } }
   ```
2. **Pipeline `_simulate`** (ingest only — request/response pipelines do not have a simulate endpoint).
3. **`verbose_pipeline=true`** on the actual search to see each processor's input and output:
   ```http
   POST /<index>/_search?search_pipeline=<name>&verbose_pipeline=true
   { ... }
   ```
   The `processor_results` array shows each processor's `status`, `error`, `input_data`, and `output_data`. This is the single most useful debugging tool — always reach for it before assuming a permission or model issue.

---

## 7. Decision flow

When a user asks for query-time or response-time LLM enrichment:

1. **What stage?**
   - Before retrieval, modify the query → request processor
   - After retrieval, enrich the response → response processor
   - At index time → use ingestion skill, not this one

2. **Single output for the whole request, or per-hit?**
   - Whole request (RAG synthesis, response-level summary) → `one_to_one: false` + `$._request.*` to read the question. Output is replicated across hits.
   - Re-ranking hits → use the `rerank` response processor. `by_field` (sort by an existing numeric field) is verified on AOSS NextGen; cross-encoder (`ml_opensearch`) is accepted but unverified end-to-end on AOSS — see the re-ranking section.
   - Per-hit scoring via an LLM that batches → `one_to_one: false` + `results[*]` in `output_map` to fan out the array (one API call). Subject to the same connector/model caveats — verify with `verbose_pipeline=true`.
   - Per hit, model can't batch (rare; custom classifier with single-doc API) → `one_to_one: true`. N API calls.

3. **Does the model output drive the entire query, or just a slot?**
   - Entire query (NL → kNN where the vector IS the query) → `query_template` (Pattern A in Section 2)
   - Just a slot (add a filter to user's existing query) → `output_map` JsonPath rewrite (Pattern B in Section 2)

4. **Are we on AOSS NextGen?**
   - Yes → review Section 4 constraints. No `model_input`, no `ext.ml_inference.*`, no `collapse`. Read errors with `verbose_pipeline=true`.
   - No (managed OS or self-hosted) → all upstream features available.

5. **Pick the smallest model that does the job** — see Section 5.

---

## 8. Verified Examples (AOSS V2 Beta — Claude Sonnet 4.6)

All examples verified end-to-end on a live AOSS V2 collection (us-east-1) using the same connector and model described in [`ingestion/ml-inference-ingest/verified_examples.md`](verified_examples.md).

### 8a. Search Response Processor — Per-Hit Sentiment + NER

One model, two response processors chained. Each overrides `system_prompt` via `model_config`:

```http
PUT /_search/pipeline/sonnet46_ner_sentiment
{
  "response_processors": [
    {
      "ml_inference": {
        "tag": "sentiment_step",
        "model_id": "5f45692d-f529-4fee-b382-6a0ae263a747",
        "input_map": [{"prompt": "review"}],
        "output_map": [{"sentiment": "$.content[0].text"}],
        "model_config": {
          "system_prompt": "You are a sentiment classifier. Reply with EXACTLY one lowercase word: positive, negative, or neutral. No punctuation."
        },
        "one_to_one": true
      }
    },
    {
      "ml_inference": {
        "tag": "ner_step",
        "model_id": "5f45692d-f529-4fee-b382-6a0ae263a747",
        "input_map": [{"prompt": "review"}],
        "output_map": [{"entities_json": "$.content[0].text"}],
        "model_config": {
          "system_prompt": "You are an NER extractor. Return ONLY a compact JSON object with keys PERSON, ORG, LOCATION, PRODUCT, DATE; each value an array of strings. No prose, no markdown, just JSON."
        },
        "one_to_one": true
      }
    }
  ]
}
```

**Key points:**
- `one_to_one: true` — runs the model once per hit (not batched)
- `model_config.system_prompt` overrides the connector default — one model serves multiple tasks
- Output path `$.content[0].text` — Claude Anthropic Messages format

**Verified results:**

| id | sentiment | PERSON | ORG | LOCATION | PRODUCT |
|---|---|---|---|---|---|
| r1 | positive | — | United Airlines | Paris | — |
| r2 | neutral | Tim Cook | Apple | — | MacBook Pro |
| r3 | negative | — | Comcast | Seattle | — |
| r4 | positive | — | Toyota | Bay Area | Toyota Camry |

---

### 8b. Search Request Processor — Natural Language → Keyword Query Rewrite

Rewrites a free-form sentiment phrase into the exact stored keyword (`positive`/`negative`/`neutral`) before the search executes. Uses `output_map` to overwrite the query field in-place (Pattern B).

```http
PUT /_search/pipeline/sonnet46_request_sentiment_classify
{
  "request_processors": [
    {
      "ml_inference": {
        "tag": "sentiment_classify_request",
        "model_id": "5f45692d-f529-4fee-b382-6a0ae263a747",
        "input_map":  [{"prompt": "query.term.sentiment.value"}],
        "output_map": [{"query.term.sentiment.value": "$.content[0].text"}],
        "model_config": {
          "system_prompt": "You are a sentiment classifier. Given a short natural-language phrase describing how a reviewer feels, output EXACTLY one lowercase word: positive, negative, or neutral. No punctuation. No explanation."
        }
      }
    }
  ]
}
```

**How it works:**
- `input_map` reads `query.term.sentiment.value` from the search request body → feeds it to model as `prompt`
- `output_map` writes model output back to `query.term.sentiment.value` → mutates the query in-flight
- The term query now matches the exact keyword stored in the index

**Verified with `verbose_pipeline=true`:**

```http
POST /sonnet46-reviews-ingest/_search?search_pipeline=sonnet46_request_sentiment_classify&verbose_pipeline=true
{
  "size": 10,
  "_source": ["id","review","sentiment"],
  "query": { "term": { "sentiment": { "value": "really bad and frustrating" } } }
}
```

**`processor_results` trace:**
```json
{
  "processor_name": "ml_inference",
  "tag": "sentiment_classify_request",
  "duration_millis": 1234,
  "status": "success",
  "input_data":  { "query": { "term": { "sentiment": { "value": "really bad and frustrating" } } } },
  "output_data": { "query": { "term": { "sentiment": { "value": "negative" } } } }
}
```

| Input phrase | Rewrite | Hits |
|---|---|---|
| `really bad and frustrating` | `negative` | 1 (r3) |
| `overjoyed and would recommend` | `positive` | 2 (r1, r4) |
| `meh, didnt care either way` | `neutral` | 1 (r2) |

---

### 8c. Tip: Run `_predict` First to Derive Your `output_map` JSONPath

Before writing any search pipeline, call the model directly:

```http
POST /_plugins/_ml/models/<model_id>/_predict
{
  "parameters": {
    "prompt": "Classify sentiment: The battery dies after 2 hours. Output one word."
  }
}
```

**Response (Claude):**
```json
{
  "inference_results": [{
    "output": [{
      "name": "response",
      "dataAsMap": {
        "content": [{"type": "text", "text": "negative"}],
        "stop_reason": "end_turn"
      }
    }]
  }]
}
```

From this response, you can see the text lives at `content[0].text` inside `dataAsMap`. So:
- **Search response/request processor `output_map`:** `"$.content[0].text"`
- **Verify:** use `verbose_pipeline=true` on your first test query to confirm the value lands correctly

**The workflow:** `_predict` → inspect output JSON → write `output_map` path → test with `verbose_pipeline=true`

---

### 8d. Three Pipeline Shapes — When to Use Which

| Aspect | Ingest pipeline | Search response processor | Search request processor |
|---|---|---|---|
| When LLM runs | At write time, once per doc | At search time, once per hit | At search time, once per query |
| Mutates | `_source` of the indexed doc | Search response only | Search request body |
| Persisted? | Yes, in index | No | No, ephemeral |
| Cost per query | 0 LLM calls | N × hits | 1 LLM call |
| Best for | Filterable/aggregatable enrichment, embeddings | RAG answers, per-hit summaries | Query rewriting, intent classification, embedding user query for kNN |

**Compose all three:**
- Ingest pipeline pre-computes structured fields (sentiment keyword, embeddings, NER for filters)
- Request processor rewrites or vectorizes the user query
- Response processor decorates hits with per-hit LLM summary or RAG answer
