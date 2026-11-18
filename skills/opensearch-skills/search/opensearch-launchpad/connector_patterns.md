# Connector Patterns for ML Inference Processors

How to get a working connector and model for `ml_inference`, and how to read its output.
For IAM and platform limits, see [ml_inference_platforms.md](ml_inference_platforms.md).

The data flow is:

```
document or request field (JSONPath) → input_map → ${parameters.X} in connector request_body → model
→ response JSON → output_map JSONPath → target field
```

---

## Start from a blueprint

Copy a connector from the official blueprints instead of writing one:
[ml-commons standard blueprints](https://github.com/opensearch-project/ml-commons/tree/main/docs/remote_inference_blueprints/standard_blueprints).

| Model | Blueprint | Use case |
|---|---|---|
| Titan Embed v2 | `bedrock_connector_titan_embedding_v2_blueprint.md` | Embeddings for kNN |
| Claude (Anthropic) | `bedrock_connector_anthropic_claude_blueprint.md` | NER, summarization, classification, PII redaction, RAG |
| Nova Micro/Lite/Pro | `bedrock_connector_nova_blueprint.md` | Fast classification (sentiment, language, intent) |
| Cohere Embed | `bedrock_connector_cohere_cohere.embed_blueprint.md` | Embeddings, including batch |
| Cohere Rerank | `bedrock_connector_cohere_rerank_blueprint.md` | Reranking |
| SageMaker | `sagemaker_connector_blueprint.md` | Custom fine-tuned models |
| OpenAI | `openai_connector_chat_blueprint.md` | GPT-4o / GPT-4o-mini |

The `input_map` keys in your pipeline must match the `${parameters.X}` names in the blueprint's `request_body`.

---

## Derive `output_map` from `_predict`

Call the model directly before building any pipeline:

```http
POST /_plugins/_ml/models/<model_id>/_predict
{ "parameters": { "prompt": "Classify sentiment: The battery dies after 2 hours. Output one word." } }
```

Response (Claude):

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

For a remote model, `output_map` JSONPath starts inside `dataAsMap` (`full_response_path: false`),
so the path is `$.content[0].text`. The `$.` prefix is optional. For a local model
(`full_response_path: true`) the path starts at the full `inference_results` envelope.

### Output JSONPath per model family

| Model family | `output_map` JSONPath |
|---|---|
| Titan Embedding | `$.embedding` |
| Claude (Anthropic Messages) | `$.content[0].text` |
| Nova (Bedrock Converse) | `output.message.content[0].text` |
| Llama | `generation` |
| Cohere Embed | `$.embeddings` (batch) or `$.embeddings[0]` (single input) |
| OpenAI Chat | `choices[0].message.content` |
| Local embedding model | `$.inference_results[0].output[0].data` |
| SageMaker | Depends on the endpoint; run `_predict` |

---

## One model, many tasks: override `system_prompt`

Give the connector a default `system_prompt` and override it per processor with `model_config`.
One model registration then serves sentiment, NER, summarization, and query rewriting.

Connector:

```json
{
  "parameters": { "system_prompt": "You are a helpful assistant.", ... },
  "actions": [{ "request_body": "{...\"system\":\"${parameters.system_prompt}\",...}" }]
}
```

Processor:

```json
{
  "ml_inference": {
    "model_id": "<model_id>",
    "input_map":  [{"prompt": "review"}],
    "output_map": [{"sentiment": "$.content[0].text"}],
    "model_config": {
      "system_prompt": "You are a sentiment classifier. Reply with EXACTLY one word: positive, negative, or neutral."
    }
  }
}
```

With `temperature: 0` and a strict prompt ("one word only", "JSON only"), Claude Sonnet 4.6
returned clean, parseable output in every verified run.

---

## Which model for which task

Pick the smallest model that does the job. Processors in one pipeline can use different models.

| Task | Model | Why |
|---|---|---|
| Embeddings (ingest or NL → kNN) | Titan Embed v2 (`amazon.titan-embed-text-v2:0`) | Purpose-built, fast, cheap |
| Sentiment, language, intent, spell-correct | Nova Micro (`us.amazon.nova-micro-v1:0`) | Sub-second, lowest cost |
| Per-hit scoring | Nova Micro or another small classifier | Per-hit calls add up |
| NER, summarization, PII redaction at ingest | Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) | Good quality, fast enough for ingest |
| RAG synthesis, complex extraction | Claude Sonnet 4.6 (`us.anthropic.claude-sonnet-4-6`) | Best instruction-following |
| Custom fine-tuned model | SageMaker endpoint | Full control |
| Prototype outside AWS | OpenAI GPT-4o-mini | API-key setup |

Claude 4.x on Bedrock must be called through a cross-region inference profile (the `us.` IDs above).
