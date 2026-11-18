# ML Inference Processors — Platform Differences

The `ml_inference` processor runs on open-source OpenSearch, Amazon OpenSearch Service (AOS),
and Amazon OpenSearch Serverless (AOSS) NextGen collections, but the supported features differ.
Patterns that work on open source often fail on AOSS. **Ask the user which platform they are on
before writing any connector or pipeline.**

This is the only file that describes platform differences. The other `ml_inference_*` guides
link here instead of repeating it.

---

## Comparison

| Feature | Open source | AOS (managed) | AOSS NextGen |
|---|---|---|---|
| `ml_inference` processors | Ingest since 2.14, search request/response since 2.16 | Same as open source | NextGen collections only. Classic AOSS does not support `ml_inference`. |
| Connector auth | API key in `credential`, or none for local models | IAM role (`credential.roleArn`) | IAM role (`credential.roleArn`), mandatory |
| Model registration | `_register` then `_deploy`, or `_register?deploy=true` | `_register?deploy=true` | `_register?deploy=true` |
| `model_input` on processors | Y | Y | N. Put the prompt in the connector `request_body` and use `${parameters.X}`. |
| `ext.ml_inference` in the search request | Y | Y | N. Not registered (typically `NamedWriteable not found`). Read request values with `$._request.<path>`. |
| `output_map` key `ext.ml_inference.X` writes to response-level `ext` | Y | Y | N. Falls through and writes a literal dotted field into each hit's `_source`. |
| `$._request.<path>` in response processors | Y | Y | Y |
| Non-ML ingest processors (`set`, `script`, `remove`, …) | Y | Y | N. Curated allowlist: `ml_inference`, `text_embedding`, and other ML processors. |
| `collapse` response processor | Y | Y | N. `400: Invalid processor type collapse` |
| `rerank` (`by_field`, `ml_opensearch`) | Y | Y | Y. Verified with Cohere Rerank and Amazon Bedrock Rerank. |
| Error messages | Full detail | Full detail | Upstream status code and message (non-429 4xx are no longer rewritten to 403) |
| Pipeline creation | Immediate | Immediate | Eventually consistent: `GET` can return `{}` for ~30s after `acknowledged: true` |
| Bedrock cross-region inference profiles | Y | Y | Y. Required for Claude 4.x (base model IDs are not invokable). |
| `_simulate` (ingest), `verbose_pipeline=true` (search) | Y | Y | Y. The main debugging tools on AOSS. |

---

## IAM setup (AOS and AOSS)

1. **Connector role**
   - Trust policy: `"Service": "opensearchservice.amazonaws.com"` (AOS) or `"Service": "ml.opensearchservice.amazonaws.com"` (AOSS).
   - Permission: `bedrock:InvokeModel` on the model or inference-profile ARN (for Claude 4.x, the inference-profile ARN).
2. **Caller** that creates the connector needs `iam:PassRole` on the connector role.
3. **AOS with fine-grained access control:** the caller needs the `ml_full_access` role mapped.
4. **AOSS data access policy** must grant `aoss:CreateMLResource` and `aoss:ExecuteMLResource`.

Without `credential.roleArn`, an AOSS connector fails with:

```json
{"error":{"reason":"Credentials are null or empty.","type":"status_exception"},"status":400}
```

AOSS does not pass the caller's credentials to outbound model calls.

---

## Per-platform notes

**Open source**
- Any provider works (Bedrock, SageMaker, OpenAI, Ollama, local models).
- `model_input` and the full ingest processor set are available, e.g. a `script` processor to clean text before `ml_inference`.
- Easiest place to reproduce an AOSS failure with full logs.

**AOS (managed)**
- All upstream features work, including `model_input`, `ext.ml_inference`, and `script`.
- CloudFormation templates are available for common connector setups.

**AOSS NextGen**
- Remote (connector) models only; local models are not available.
- No `model_input`, no `ext.ml_inference`, no non-ML ingest processors, no `collapse`.
- In automation, retry `GET` on a new pipeline for ~30s before treating it as missing.

---

## Debugging a failing `_predict` or pipeline

```
_predict fails →
├── Open source / AOS: read the error message; on AOS check the role's trust policy and permissions
└── AOSS: read the error message first; if it is a 403 →
    ├── Is credential.roleArn set on the connector?
    ├── Does the data access policy grant CreateMLResource + ExecuteMLResource?
    ├── Does the role trust ml.opensearchservice.amazonaws.com?
    ├── Is bedrock:InvokeModel granted on the inference-profile ARN (not the base model ARN)?
    └── Still stuck: reproduce on open-source 3.x and compare

_predict works but the pipeline fails →
├── Ingest: POST /_ingest/pipeline/<name>/_simulate
└── Search: add verbose_pipeline=true; processor_results[] shows each processor's error, input_data, output_data
```
