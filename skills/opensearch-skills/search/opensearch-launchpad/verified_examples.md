# Verified Examples — ML Inference Processors on AOSS NextGen

All examples in this file were verified end-to-end on a live AOSS NextGen collection
(us-east-1) using Claude Sonnet 4.6 via a Bedrock cross-region inference profile. Generated 2026-05-12.

They use no AOSS-only syntax, so they also apply to open source and AOS. For platform limits
and IAM, see [ml_inference_platforms.md](ml_inference_platforms.md). For how each processor
works, see [ml_inference_ingest_guide.md](ml_inference_ingest_guide.md) and
[ml_inference_search_pipeline_guide.md](ml_inference_search_pipeline_guide.md).

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

**Response:** `{ "connector_id": "<connector_id>" }`

Without `credential.roleArn` this call fails with `Credentials are null or empty` (see
[ml_inference_platforms.md](ml_inference_platforms.md#iam-setup-aos-and-aoss)).

### Register and deploy

```http
POST /_plugins/_ml/models/_register?deploy=true
{
  "name": "Claude Sonnet 4.6",
  "function_name": "remote",
  "description": "Claude Sonnet 4.6 via Bedrock cross-region inference profile",
  "connector_id": "<connector_id>"
}
```

**Response:** `{ "model_id": "<model_id>" }`

### Direct predict sanity check

```http
POST /_plugins/_ml/models/<model_id>/_predict
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
        "model_id": "<model_id>",
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
        "model_id": "<model_id>",
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
The fields are computed per search and not stored.

```http
PUT /_search/pipeline/sonnet46_ner_sentiment
{
  "response_processors": [
    {
      "ml_inference": {
        "tag": "sentiment_step",
        "model_id": "<model_id>",
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
        "model_id": "<model_id>",
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

**Key difference from ingest:** `one_to_one: true` makes one model call per hit, so each hit gets its own result. With the default `false`, all hits are sent to the model in a single call.

### Query with the pipeline

```http
POST /sonnet46-reviews/_search?search_pipeline=sonnet46_ner_sentiment
{"size": 10, "_source": ["id","review","sentiment","entities_json"], "query": {"match_all": {}}}
```

### Verified results

| id | sentiment | PERSON | ORG | LOCATION | PRODUCT |
|---|---|---|---|---|---|
| r1 | positive | — | United Airlines | Paris | — |
| r2 | neutral | Tim Cook | Apple | — | MacBook Pro |
| r3 | negative | — | Comcast | Seattle | — |
| r4 | positive | — | Toyota | Bay Area | Toyota Camry |

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
        "model_id": "<model_id>",
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
