# Connector Patterns for ML Inference Processors

## Key Insight: `ml_inference` Uses JSONPath — Maximum Flexibility, No Preprocessing

The `ml_inference` processor's power comes from **JSONPath-based field extraction**. Unlike the specialized `text_embedding` processor that can only read a single flat text field, `ml_inference` uses `input_map` with JSONPath to extract **any** value from the document — nested objects, array elements, specific positions — and maps it directly to the connector's `request_body` template.

This means:
- **No preprocessing layer needed** — no `script` or `set` processors to reshape your document before the model sees it
- **No `pre_process_function` / `post_process_function` needed** — `input_map` feeds the model, `output_map` picks the result
- **Works for any model type** — embeddings, LLMs, classifiers, rerankers — all through the same processor
- **Handles nested data natively** — `items[0].description`, `metadata.tags`, `reviews.text` all work directly

```
Document field (any JSONPath) → input_map → ${parameters.X} in request_body → Model → response JSON → output_map JSONPath → target field
```

---

## Connector Blueprints (Official Recipes)

Instead of writing connectors from scratch, **start from the official blueprints**:

📁 **[opensearch-project/ml-commons — Standard Blueprints](https://github.com/opensearch-project/ml-commons/tree/main/docs/remote_inference_blueprints/standard_blueprints)**

Key blueprints for `ml_inference` use cases:

| Model | Blueprint | Use Case |
|---|---|---|
| Titan Embed v2 | `bedrock_connector_titan_embedding_v2_blueprint.md` | Auto-embedding for kNN/semantic search |
| Claude (Anthropic) | `bedrock_connector_anthropic_claude_blueprint.md` | NER, summarization, classification, PII redaction |
| Nova Micro/Lite/Pro | `bedrock_connector_nova_blueprint.md` | Fast classification (sentiment, language, intent) |
| Cohere Embed | `bedrock_connector_cohere_cohere.embed_blueprint.md` | Cohere embeddings |
| Cohere Rerank | `bedrock_connector_cohere_rerank_blueprint.md` | Reranking |
| SageMaker | `sagemaker_connector_blueprint.md` | Custom fine-tuned models |
| OpenAI | `openai_connector_chat_blueprint.md` | GPT-4o / GPT-4o-mini |

---

## What You Need to Know Per Model (for `output_map` JSONPath)

The only thing you must customize after copying a blueprint is your `output_map` JSONPath. Run `_predict` first to see the response shape:

| Model Family | Output JSONPath (for `ml_inference` `output_map`) |
|---|---|
| **Titan Embedding** | `$.embedding` |
| **Claude (Anthropic Messages)** | `$.content[0].text` |
| **Nova (Bedrock Converse)** | `output.message.content[0].text` |
| **Llama** | `generation` |
| **Cohere Embed** | `$.embeddings[0]` |
| **OpenAI Chat** | `choices[0].message.content` |
| **SageMaker** | Depends on your endpoint — always run `_predict` first |

> **Note:** Ingest processors use `$.` prefix. Search response processors omit it. See `ml_inference_ingest_guide.md` Section 6 gotcha 3 for details.

---

## The `system_prompt` Override Pattern (Verified on AOSS V2)

One connector + one model can serve **multiple tasks** (sentiment, NER, summarization, query rewriting) by overriding the system prompt at the pipeline layer:

**Connector** — define a default `system_prompt` in `parameters`:
```json
{
  "parameters": {
    "system_prompt": "You are a helpful assistant.",
    ...
  },
  "actions": [{
    "request_body": "{...\"system\":\"${parameters.system_prompt}\",...}"
  }]
}
```

**Pipeline processor** — override per task via `model_config`:
```json
{
  "ml_inference": {
    "model_id": "<model_id>",
    "input_map": [{"prompt": "review"}],
    "output_map": [{"sentiment": "$.content[0].text"}],
    "model_config": {
      "system_prompt": "You are a sentiment classifier. Reply with EXACTLY one word: positive, negative, or neutral."
    }
  }
}
```

This means: **register the model once, use it everywhere** with different prompts.

---

## IAM Setup (Managed Service / AOSS)

For Bedrock connectors on AOS or AOSS:

1. **Connector role** needs:
   - Trust policy: `"Service": "opensearchservice.amazonaws.com"` (AOS) or `"Service": "ml.opensearchservice.amazonaws.com"` (AOSS)
   - Permission: `bedrock:InvokeModel` on the model/inference-profile ARN

2. **AOSS additionally needs** in the data access policy:
   - `aoss:CreateMLResource`
   - `aoss:ExecuteMLResource`

3. **The caller** creating the connector needs `iam:PassRole` to pass the connector role to OpenSearch

4. **Cross-region inference profiles** (e.g., `us.anthropic.claude-sonnet-4-6`) are required for Claude 4.x on Bedrock — base model IDs are not directly invokable

---

## Quick Decision: Which Model for Which Task?

| Task | Recommended Model | Why |
|---|---|---|
| Auto-embedding (kNN search) | Titan Embed v2 | Purpose-built, fast, cheap |
| Sentiment / language / intent | Nova Micro | Sub-second, lowest cost |
| NER / summarization / PII redaction | Claude Haiku 4.5 | Good quality, fast enough for ingest |
| Complex extraction / reasoning | Claude Sonnet 4.6 | Highest quality |
| Custom fine-tuned model | SageMaker endpoint | Full control |
| Quick prototype (non-AWS) | OpenAI GPT-4o-mini | Easy API key setup |
