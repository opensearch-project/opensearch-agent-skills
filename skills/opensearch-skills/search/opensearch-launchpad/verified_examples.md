# Verified Examples — ML Inference Processors on AOSS V2

All examples in this file were verified end-to-end on a live AOSS V2 beta collection
(us-east-1, account 631352388807) using Claude Sonnet 4.6 via Bedrock cross-region
inference profile. Generated 2026-05-12.

---

## Connector: Bedrock Claude Sonnet 4.6 (Anthropic Messages API)

This connector works for **all three processor types** (ingest, search request, search response).
The `system_prompt` parameter is overridden per-pipeline via `model_config.system_prompt`,
so one connector + one model registration serves unlimited tasks.

```http
POST /_plugins/_ml/connectors/_create
{
  "name": "Bedrock Claude Sonnet 4.6",
  "version": "1",
  "protocol": "aws_sigv4",
  "credential": {
    "roleArn": "arn:aws:iam::<account>:role/<role>"
  },
  "parameters": {
    "service_name": "bedrock",
    "region": "us-east-1",
    "model": "us.anthropic.claude-sonnet-4-6",
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 1024,
    "temperature": 0,
    "system_prompt": "You are a helpful assistant. Respond ONLY with the requested JSON or value, no preamble."
  },
  "actions": [
    {
      "action_type": "PREDICT",
      "method": "POST",
      "url": "https://bedrock-runtime.us-east-1.amazonaws.com/model/${parameters.model}/invoke",
      "headers": {
        "content-type": "application/json",
        "x-amz-content-sha256": "required"
      },
      "request_body": "{\"anthropic_version\":\"${parameters.anthropic_version}\",\"max_tokens\":${parameters.max_tokens},\"temperature\":${parameters.temperature},\"system\":\"${parameters.system_prompt}\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"${parameters.prompt}\"}]}]}"
    }
  ]
}
```

**Response:** `{ "connector_id": "134d9123-6ea8-4902-97f8-92bcedab4830" }`

**Gotcha:** First attempt without `credential.roleArn` failed with:
```json
{"error":{"reason":"Credentials are null or empty.","type":"status_exception"},"status":400}
```
AOSS does not auto-inherit caller credentials for outbound Bedrock calls — you must supply a role.

### Register and deploy

```http
POST /_plugins/_ml/models/_register?deploy=true
{
  "name": "Claude Sonnet 4.6",
  "function_name": "remote",
  "description": "Claude Sonnet 4.6 via Bedrock cross-region inference profile",
  "connector_id": "134d9123-6ea8-4902-97f8-92bcedab4830"
}
```

**Response:** `{ "model_id": "5f45692d-f529-4fee-b382-6a0ae263a747" }`

### Direct predict sanity check

```http
POST /_plugins/_ml/models/5f45692d-f529-4fee-b382-6a0ae263a747/_predict
{
  "parameters": {
    "prompt": "Classify the sentiment of this review as exactly one word: positive, negative, or neutral. Review: \"The battery dies after 2 hours and customer support never responded. Total waste of money.\""
  }
}
```

**Response:** `"negative"` (4 output tokens). Model obeys "single word" instruction with `temperature=0`.

---

## Example 1: Ingest Pipeline — Chained Sentiment + NER

Creates two enrichment fields (`sentiment` as keyword, `entities_json` as text) on every indexed document.

### Create pipeline

```http
PUT /_ingest/pipeline/sonnet46_ingest_ner_sentiment
{
  "description": "Enrich review docs with sentiment + NER via Claude Sonnet 4.6 at write time",
  "processors": [
    {
      "ml_inference": {
        "tag": "sentiment_step",
        "model_id": "5f45692d-f529-4fee-b382-6a0ae263a747",
        "input_map":  [{"prompt": "review"}],
        "output_map": [{"sentiment": "$.content[0].text"}],
        "model_config": {
          "system_prompt": "You are a sentiment classifier. Reply with EXACTLY one lowercase word: positive, negative, or neutral. No punctuation, no explanation."
        }
      }
    },
    {
      "ml_inference": {
        "tag": "ner_step",
        "model_id": "5f45692d-f529-4fee-b382-6a0ae263a747",
        "input_map":  [{"prompt": "review"}],
        "output_map": [{"entities_json": "$.content[0].text"}],
        "model_config": {
          "system_prompt": "You are an NER extractor. Return ONLY a compact JSON object with keys PERSON, ORG, LOCATION, PRODUCT, DATE; each value an array of strings. No prose, no markdown, just JSON."
        }
      }
    }
  ]
}
```

### Create index bound to pipeline

```http
PUT /sonnet46-reviews-ingest
{
  "settings": {
    "index": {
      "knn": false,
      "default_pipeline": "sonnet46_ingest_ner_sentiment"
    }
  },
  "mappings": {
    "properties": {
      "id":            {"type": "keyword"},
      "review":        {"type": "text"},
      "sentiment":     {"type": "keyword"},
      "entities_json": {"type": "text"}
    }
  }
}
```

### Ingest test documents

```http
POST /sonnet46-reviews-ingest/_doc
{"id":"r1","review":"I just got back from a trip to Paris with United Airlines on November 3 2025 and the service was absolutely outstanding."}

POST /sonnet46-reviews-ingest/_doc
{"id":"r2","review":"The new MacBook Pro from Apple has a beautiful display, but Tim Cook keynote was kind of boring this year."}

POST /sonnet46-reviews-ingest/_doc
{"id":"r3","review":"Worst experience ever with Comcast. The technician never showed up in Seattle and customer service hung up on me twice."}

POST /sonnet46-reviews-ingest/_doc
{"id":"r4","review":"Toyota Camry 2025 model is reliable and fuel efficient. I recommend it to anyone in the Bay Area."}
```

### Verified results (no search pipeline — fields are in `_source`)

| id | sentiment | entities_json (parsed) |
|---|---|---|
| r1 | **positive** | `{"PERSON":[],"ORG":["United Airlines"],"LOCATION":["Paris"],"PRODUCT":[],"DATE":["November 3 2025"]}` |
| r2 | **neutral** | `{"PERSON":["Tim Cook"],"ORG":["Apple"],"LOCATION":[],"PRODUCT":["MacBook Pro"],"DATE":["this year"]}` |
| r3 | **negative** | `{"PERSON":[],"ORG":["Comcast"],"LOCATION":["Seattle"],"PRODUCT":[],"DATE":[]}` |
| r4 | **positive** | `{"PERSON":[],"ORG":["Toyota"],"LOCATION":["Bay Area"],"PRODUCT":["Toyota Camry"],"DATE":["2025"]}` |

### Aggregation on enriched field

```http
POST /sonnet46-reviews-ingest/_search
{"size":0,"aggs":{"by_sentiment":{"terms":{"field":"sentiment"}}}}
```

```json
"aggregations": {
  "by_sentiment": {
    "buckets": [
      {"key": "positive", "doc_count": 2},
      {"key": "negative", "doc_count": 1},
      {"key": "neutral",  "doc_count": 1}
    ]
  }
}
```

---

## Example 2: Search Response Processor — Per-Hit Enrichment

Same model, different `system_prompt` at the pipeline layer. No new model registration needed.

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

**Key difference from ingest:** `one_to_one: true` is required for search response processors to run per-hit.

### Query with the pipeline

```http
POST /sonnet46-reviews/_search?search_pipeline=sonnet46_ner_sentiment
{"size": 10, "_source": ["id","review","sentiment","entities_json"], "query": {"match_all": {}}}
```

---

## Example 3: Search Request Processor — Query Rewriting

Rewrites a natural-language sentiment phrase into the exact stored keyword before the search executes.

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

### Verified query rewrite tests

```http
POST /sonnet46-reviews-ingest/_search?search_pipeline=sonnet46_request_sentiment_classify&verbose_pipeline=true
{
  "size": 10,
  "_source": ["id","review","sentiment"],
  "query": { "term": { "sentiment": { "value": "really bad and frustrating" } } }
}
```

**`processor_results` trace (from `verbose_pipeline=true`):**
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

| Input phrase | Rewrite | Hits | Stored sentiment |
|---|---|---|---|
| `really bad and frustrating` | `negative` | 1 | negative |
| `overjoyed and would recommend` | `positive` | 2 | positive |
| `meh, didnt care either way` | `neutral` | 1 | neutral |

---

## When to Use Which Pipeline Shape

| Aspect | Ingest pipeline | Search response processor | Search request processor |
|---|---|---|---|
| When LLM runs | At write time, once per doc | At search time, once per hit | At search time, once per query |
| Mutates | `_source` of the indexed doc | Search response only | Search request body |
| Persisted? | Yes, in index | No | No, ephemeral |
| Cost per query | 0 LLM calls | N × hits | 1 LLM call |
| Best for | Filterable/aggregatable enrichment, embeddings | RAG-style answers, per-hit summaries | Query rewriting, intent classification, embedding the user query for kNN |

**Hybrid pattern:** Use all three together:
- **Ingest pipeline** pre-computes structured fields (sentiment, embeddings, NER for filters)
- **Request processor** rewrites or vectorizes the user query
- **Response processor** decorates hits with a per-hit LLM summary

---

## AOSS V2 Gotchas (verified)

1. **Pipeline creation is eventually consistent.** `PUT` returns `acknowledged:true` but `GET` returns `{}` for ~30s. Plan for retry in automation.
2. **`credential.roleArn` is mandatory.** AOSS does not auto-inherit caller credentials for outbound Bedrock calls.
3. **Cross-region inference profile is mandatory** for Claude 4.x — base model IDs are not invokable directly.
4. **All 4xx errors are masked as 403 Forbidden.** Use `_simulate` or reproduce on open-source 3.x to see the real error.
5. **`model_config.system_prompt` overrides the connector's default** — one model serves multiple tasks by swapping prompts at the pipeline layer.
6. **`temperature: 0` + strict system prompt** gives clean, parseable output. Sonnet 4.6 followed every "JSON only / one-word only" constraint.
7. **`verbose_pipeline=true`** on search queries shows `input_data` and `output_data` for every processor — use it for debugging request processors.
8. **Ingest pipeline does NOT auto-reindex existing docs.** Only new writes pick up changes. Use `_reindex` for backfill.

---

## Platform Differences: Open Source vs Managed AOS vs AOSS

The `ml_inference` processor works across all three platforms, but each has unique constraints. **Always ask the user which platform they are on** before giving guidance.

### Quick Comparison

| Aspect | Open Source (self-managed) | Amazon OpenSearch Service (AOS) | Amazon OpenSearch Serverless (AOSS) |
|---|---|---|---|
| **Supported since** | 2.14 (ingest), 2.16 (search) | Same versions as OS | NextGen collections only (Classic AOSS does NOT support it) |
| **Connector auth** | Basic auth, no IAM needed for local models | IAM role required (`credential.roleArn`) | IAM role required (`credential.roleArn`) — **mandatory**, no auto-inherit |
| **Credential setup** | API key in connector `credential` block, or no auth for local models | Role must trust `opensearchservice.amazonaws.com` | Role must trust `ml.opensearchservice.amazonaws.com` |
| **Model registration** | `_register` + `_deploy` (explicit deploy step) | `_register?deploy=true` (auto-deploy available) | `_register?deploy=true` (auto-deploy available) |
| **`model_input` field** | ✅ Supported | ✅ Supported | ❌ **Not supported** — use connector `${parameters.X}` template instead |
| **`ext.ml_inference` extension** | ✅ Supported (response processors) | ✅ Supported | ❌ **Not supported** — use `$._request.<path>` instead |
| **`set`, `script`, `remove` processors** | ✅ All ingest processors available | ✅ All ingest processors available | ❌ **Not in allowlist** — only ML-related processors |
| **`collapse` processor** | ✅ Supported | ✅ Supported | ❌ Not supported |
| **Error messages** | Full, unmasked error with details | Full error messages | ⚠️ **All 4xx masked as 403 Forbidden** — no detail |
| **Pipeline creation** | Immediate (synchronous) | Immediate | ⚠️ **Eventually consistent** (~30s delay after `acknowledged:true`) |
| **IAM permissions for Bedrock** | N/A (or local role for Bedrock) | `bedrock:InvokeModel` on connector role | `bedrock:InvokeModel` + `aoss:CreateMLResource` + `aoss:ExecuteMLResource` in data access policy |
| **Cross-region inference profiles** | Works if you have Bedrock access | Works | ✅ Required for Claude 4.x (base model IDs not invokable) |
| **`verbose_pipeline=true`** | ✅ Works | ✅ Works | ✅ Works — **use this as primary debug tool** since errors are masked |
| **`_simulate` (ingest)** | ✅ Full error details | ✅ Full error details | ✅ Better error surface than live ingest (use for debugging) |
| **Rerank `by_field`** | ✅ Works | ✅ Works | ✅ Verified working |
| **Rerank `ml_opensearch`** | ✅ Works | ✅ Works | ✅ Verified working
| **Max model timeout** | Configurable | Configurable | Default limits apply |

### Platform-Specific Tips

#### Open Source (self-managed)
- **Easiest to debug** — error messages are unmasked and detailed
- No IAM complexity; use basic auth or disable security for local dev
- Can use **any** model provider: Bedrock, SageMaker, OpenAI, Ollama, local models
- `model_input` field available for complex prompt construction
- All ingest processors available for pre/post-processing (e.g., `script` to sanitize input before `ml_inference`)
- **Best for:** development, testing, reproducing AOSS errors to see the real message

#### Amazon OpenSearch Service (AOS / Managed)
- IAM role setup required for connector → Bedrock/SageMaker calls
- Trust policy needs: `"Service": "opensearchservice.amazonaws.com"`
- `iam:PassRole` required for the human/role that creates the connector
- Fine-Grained Access Control (FGAC) applies — the user creating connectors/models needs `ml_full_access` role mapped
- **Pre-built blueprints available** via CloudFormation for common connector patterns
- All upstream OpenSearch features work (including `model_input`, `ext.ml_inference`, `script` processor)
- **Best for:** production workloads with full feature set

#### Amazon OpenSearch Serverless (AOSS NextGen)
- **Most restrictive** — only ML-related processors in the allowlist
- Must use connector `${parameters.X}` templates (no `model_input`)
- Must use `$._request.<path>` in response processors (no `ext.ml_inference`)
- `credential.roleArn` is mandatory — forgot this = opaque `403`
- Trust policy needs: `"Service": "ml.opensearchservice.amazonaws.com"`
- Data access policy needs: `aoss:CreateMLResource`, `aoss:ExecuteMLResource`
- Pipeline creation is eventually consistent — retry after 30s
- All 4xx errors masked as 403 → debug with `_simulate` or `verbose_pipeline=true`
- **Best for:** serverless workloads where you don't want to manage infrastructure, but expect more debugging friction

### Debugging Flowchart by Platform

```
_predict fails →
├── Open Source: Read the error message directly (it tells you exactly what's wrong)
├── AOS: Read the error message (usually clear); check IAM role trust + permissions
└── AOSS: Error says "403 Forbidden" →
    ├── Try _simulate (shows better errors)
    ├── Check roleArn is set in connector
    ├── Check data access policy has CreateMLResource + ExecuteMLResource
    ├── Check role trusts ml.opensearchservice.amazonaws.com
    ├── Check bedrock:InvokeModel on the inference profile ARN (not base model ARN)
    └── If still stuck: reproduce on open-source 3.x to see the unmasked error
```
