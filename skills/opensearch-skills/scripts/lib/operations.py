"""Core OpenSearch operations: index, model, pipeline, search, docs."""

import json
import os
import sys
import time

from opensearchpy import OpenSearch

from .client import create_client, normalize_text


# ---------------------------------------------------------------------------
# Pretrained model registry
# ---------------------------------------------------------------------------
PRETRAINED_MODELS = {
    "huggingface/cross-encoders/ms-marco-MiniLM-L-12-v2": "1.0.2",
    "huggingface/cross-encoders/ms-marco-MiniLM-L-6-v2": "1.0.2",
    "huggingface/sentence-transformers/all-MiniLM-L12-v2": "1.0.2",
    "huggingface/sentence-transformers/all-MiniLM-L6-v2": "1.0.2",
    "huggingface/sentence-transformers/all-distilroberta-v1": "1.0.2",
    "huggingface/sentence-transformers/all-mpnet-base-v2": "1.0.2",
    "huggingface/sentence-transformers/distiluse-base-multilingual-cased-v1": "1.0.2",
    "huggingface/sentence-transformers/msmarco-distilbert-base-tas-b": "1.0.3",
    "huggingface/sentence-transformers/multi-qa-MiniLM-L6-cos-v1": "1.0.2",
    "huggingface/sentence-transformers/multi-qa-mpnet-base-dot-v1": "1.0.2",
    "huggingface/sentence-transformers/paraphrase-MiniLM-L3-v2": "1.0.2",
    "huggingface/sentence-transformers/paraphrase-mpnet-base-v2": "1.0.1",
    "huggingface/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": "1.0.2",
    "amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v1": "1.0.1",
    "amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v2-distill": "1.0.0",
    "amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v2-mini": "1.0.0",
    "amazon/neural-sparse/opensearch-neural-sparse-encoding-v2-distill": "1.0.0",
    "amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v3-distill": "1.0.0",
    "amazon/neural-sparse/opensearch-neural-sparse-encoding-doc-v3-gte": "1.0.0",
    "amazon/neural-sparse/opensearch-neural-sparse-tokenizer-v1": "1.0.1",
    "amazon/neural-sparse/opensearch-neural-sparse-tokenizer-multilingual-v1": "1.0.0",
    "amazon/sentence-highlighting/opensearch-semantic-highlighter-v1": "1.0.0",
    "amazon/metrics_correlation": "1.0.0b2",
}


# ---------------------------------------------------------------------------
# ML helpers
# ---------------------------------------------------------------------------
def _wait_for_ml_task(
    client: OpenSearch, task_id: str, *, max_polls: int = 100, interval: int = 3
) -> tuple[str, dict]:
    if not task_id:
        return "FAILED", {"error": "Missing task_id"}
    for _ in range(max_polls):
        res = client.transport.perform_request("GET", f"/_plugins/_ml/tasks/{task_id}")
        state = normalize_text(res.get("state", "")).upper()
        if state in {"COMPLETED", "FAILED"}:
            return state, res
        time.sleep(interval)
    return "TIMEOUT", {}


def set_ml_settings(client: OpenSearch) -> None:
    body = {
        "persistent": {
            "plugins.ml_commons.native_memory_threshold": 95,
            "plugins.ml_commons.only_run_on_ml_node": False,
            "plugins.ml_commons.allow_registering_model_via_url": True,
            "plugins.ml_commons.model_access_control_enabled": True,
            "plugins.ml_commons.trusted_connector_endpoints_regex": [
                "^https://runtime\\.sagemaker\\..*[a-z0-9-]\\.amazonaws\\.com/.*$",
                "^https://bedrock-runtime\\..*[a-z0-9-]\\.amazonaws\\.com/.*$",
            ],
        }
    }
    client.transport.perform_request("PUT", "/_cluster/settings", body=body)


# ---------------------------------------------------------------------------
# Index operations
# ---------------------------------------------------------------------------
def create_index(
    index_name: str, body: dict | None = None, replace_if_exists: bool = True
) -> str:
    if body is None:
        body = {}
    try:
        client = create_client()
    except Exception as e:
        return f"Failed to create index '{index_name}': {e}"

    try:
        exists = client.indices.exists(index=index_name)
    except Exception:
        exists = False

    if exists and replace_if_exists:
        try:
            client.indices.delete(index=index_name, ignore=[404])
        except Exception as e:
            return f"Failed to delete existing index '{index_name}': {e}"
    elif exists:
        return f"Index '{index_name}' already exists."

    try:
        client.indices.create(index=index_name, body=body)
        action = "recreated" if exists else "created"
        return f"Index '{index_name}' {action} successfully."
    except Exception as e:
        return f"Failed to create index '{index_name}': {e}"


def index_doc(index_name: str, doc: dict, doc_id: str) -> str:
    client = create_client()
    try:
        client.index(index=index_name, body=doc, id=doc_id)
    except Exception as e:
        return f"Failed to index document: {e}"

    client.indices.refresh(index=index_name)

    try:
        result = client.get(index=index_name, id=doc_id)
        return json.dumps(result, default=str, ensure_ascii=False)
    except Exception as e:
        return f"Indexed but failed to retrieve: {e}"


def index_bulk(index_name: str, docs: list[dict], id_prefix: str = "doc") -> str:
    client = create_client()
    indexed = []
    errors = []
    bulk_body: list[dict] = []
    doc_id_list: list[str] = []

    for i, doc in enumerate(docs, 1):
        doc_id = f"{id_prefix}-{i}"
        bulk_body.append({"index": {"_index": index_name, "_id": doc_id}})
        bulk_body.append(doc)
        doc_id_list.append(doc_id)

    if bulk_body:
        try:
            resp = client.bulk(body=bulk_body)
            for item, doc_id in zip(resp.get("items", []), doc_id_list):
                action_result = item.get("index", {})
                if action_result.get("error"):
                    errors.append(f"{doc_id}: {action_result['error']}")
                else:
                    indexed.append(doc_id)
        except Exception as e:
            errors.append(f"bulk request failed: {e}")

    if indexed:
        client.indices.refresh(index=index_name)

    return json.dumps({
        "index_name": index_name,
        "indexed_count": len(indexed),
        "doc_ids": indexed,
        "errors": errors,
    }, ensure_ascii=False)


def search(client: OpenSearch, index_name: str, body: dict | None = None, size: int = 10) -> dict:
    if body is None:
        body = {"query": {"match_all": {}}}
    return client.search(index=index_name, body=body, size=size)


# ---------------------------------------------------------------------------
# ML model deployment
# ---------------------------------------------------------------------------
def deploy_local_model(model_name: str) -> str:
    if model_name not in PRETRAINED_MODELS:
        return f"Error: Model '{model_name}' not supported. Supported: {list(PRETRAINED_MODELS.keys())}"

    try:
        client = create_client()
        set_ml_settings(client)

        version = PRETRAINED_MODELS[model_name]
        register_body = {
            "name": model_name,
            "version": version,
            "model_format": "TORCH_SCRIPT",
        }
        print(f"Registering model '{model_name}'...", file=sys.stderr)
        resp = client.transport.perform_request(
            "POST", "/_plugins/_ml/models/_register", body=register_body
        )
        task_id = resp.get("task_id")

        state, task_res = _wait_for_ml_task(client, task_id, max_polls=100, interval=5)
        if state == "FAILED":
            return f"Model registration failed: {task_res.get('error')}"
        if state == "TIMEOUT":
            return "Model registration timed out."

        model_id = task_res.get("model_id")
        if not model_id:
            return "Model registration completed but no model_id returned."
        print(f"Model registered: {model_id}", file=sys.stderr)

        # Deploy
        resp = client.transport.perform_request(
            "POST", f"/_plugins/_ml/models/{model_id}/_deploy"
        )
        deploy_task_id = resp.get("task_id")
        print(f"Deploying model {model_id}...", file=sys.stderr)

        state, task_res = _wait_for_ml_task(client, deploy_task_id, max_polls=100, interval=3)
        if state == "COMPLETED":
            return f"Model '{model_name}' (ID: {model_id}) created and deployed successfully."
        if state == "FAILED":
            return f"Model deployment failed: {task_res.get('error')}"
        return f"Model deployment timed out. Model ID: {model_id}"

    except Exception as e:
        return f"Error creating local pretrained model: {e}"


def deploy_bedrock_model(model_name: str) -> str:
    if model_name != "amazon.titan-embed-text-v2:0":
        return "Error: Only amazon.titan-embed-text-v2:0 is supported."

    region = os.getenv("AWS_REGION", "us-east-1")
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    session_token = os.getenv("AWS_SESSION_TOKEN")

    if not access_key or not secret_key:
        return "Error: AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY) required."

    credentials = {"access_key": access_key, "secret_key": secret_key}
    if session_token:
        credentials["session_token"] = session_token

    connector_body = {
        "name": f"Bedrock Connector for {model_name}",
        "description": f"Connector for Bedrock model {model_name}",
        "version": 1,
        "protocol": "aws_sigv4",
        "parameters": {"region": region, "service_name": "bedrock"},
        "credential": credentials,
        "actions": [{
            "action_type": "predict",
            "method": "POST",
            "url": f"https://bedrock-runtime.{region}.amazonaws.com/model/{model_name}/invoke",
            "headers": {"content-type": "application/json"},
            "request_body": '{"inputText": "${parameters.inputText}"}',
        }],
    }

    try:
        client = create_client()
        set_ml_settings(client)

        resp = client.transport.perform_request(
            "POST", "/_plugins/_ml/connectors/_create", body=connector_body
        )
        connector_id = resp.get("connector_id")
        if not connector_id:
            return f"Failed to create connector: {resp}"

        register_body = {
            "name": f"Bedrock {model_name}",
            "function_name": "remote",
            "connector_id": connector_id,
        }
        resp = client.transport.perform_request(
            "POST", "/_plugins/_ml/models/_register?deploy=true", body=register_body
        )
        task_id = resp.get("task_id")

        state, task_res = _wait_for_ml_task(client, task_id, max_polls=100, interval=5)
        if state == "COMPLETED":
            mid = task_res.get("model_id")
            return f"Bedrock model '{model_name}' (ID: {mid}) deployed successfully."
        if state == "FAILED":
            return f"Bedrock model deployment failed: {task_res.get('error')}"
        return "Bedrock model deployment timed out."

    except Exception as e:
        return f"Error deploying Bedrock model: {e}"


# ---------------------------------------------------------------------------
# Pipeline operations
# ---------------------------------------------------------------------------
def create_pipeline(
    pipeline_name: str,
    pipeline_body: dict,
    index_name: str,
    pipeline_type: str = "ingest",
    is_hybrid: bool = False,
    hybrid_weights: list[float] | None = None,
) -> str:
    if not index_name:
        return "Error: index_name is required."

    if pipeline_type == "search" and is_hybrid and not pipeline_body:
        weights = hybrid_weights or [0.5, 0.5]
        pipeline_body = {
            "phase_results_processors": [{
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {"weights": weights},
                    },
                }
            }]
        }

    if pipeline_type == "ingest" and not pipeline_body:
        return "Error: pipeline_body required for ingest pipelines."

    try:
        client = create_client()
        client.transport.perform_request(
            "PUT", f"/_{'search' if pipeline_type == 'search' else 'ingest'}/pipeline/{pipeline_name}",
            body=pipeline_body,
        )

        if index_name:
            setting_key = (
                "index.search.default_pipeline"
                if pipeline_type == "search"
                else "index.default_pipeline"
            )
            client.indices.put_settings(
                index=index_name,
                body={"index": {setting_key.split(".", 1)[-1]: pipeline_name}},
            )

        return f"Pipeline '{pipeline_name}' ({pipeline_type}) created and attached to '{index_name}'."
    except Exception as e:
        return f"Failed to create pipeline: {e}"


# ---------------------------------------------------------------------------
# Agentic search
# ---------------------------------------------------------------------------
def deploy_agentic_model(
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    session_token: str = "",
    model_name: str = "us.anthropic.claude-sonnet-4-20250514-v1:0",
) -> str:
    if not access_key or not secret_key:
        return "Error: AWS credentials required."

    creds = {"access_key": access_key.strip(), "secret_key": secret_key.strip()}
    if session_token and session_token.strip():
        creds["session_token"] = session_token.strip()

    register_body = {
        "name": f"agentic-search-model-{int(time.time())}",
        "function_name": "remote",
        "connector": {
            "name": f"Bedrock Claude Connector {int(time.time())}",
            "description": "Bedrock connector for agentic search",
            "version": 1,
            "protocol": "aws_sigv4",
            "parameters": {
                "region": region.strip(),
                "service_name": "bedrock",
                "model": model_name,
            },
            "credential": creds,
            "actions": [{
                "action_type": "predict",
                "method": "POST",
                "url": f"https://bedrock-runtime.{region.strip()}.amazonaws.com/model/{model_name}/converse",
                "headers": {"content-type": "application/json"},
                "request_body": '{ "system": [{"text": "${parameters.system_prompt}"}], "messages": [${parameters._chat_history:-}{"role":"user","content":[{"text":"${parameters.user_prompt}"}]}${parameters._interactions:-}]${parameters.tool_configs:-} }',
            }],
        },
    }

    try:
        client = create_client()
        set_ml_settings(client)
        resp = client.transport.perform_request(
            "POST", "/_plugins/_ml/models/_register?deploy=true", body=register_body
        )
        model_id = resp.get("model_id") or resp.get("modelId")
        if not model_id:
            return f"Registration failed: {resp}"
        return model_id
    except Exception as e:
        return f"Error creating agentic model: {e}"


def create_flow_agent(agent_name: str, model_id: str) -> str:
    if not model_id:
        return "Error: model_id required."
    try:
        client = create_client()
        body = {
            "name": agent_name,
            "type": "flow",
            "description": "Flow agent for agentic search",
            "tools": [
                {"type": "IndexMappingTool", "name": "IndexMappingTool"},
                {
                    "type": "QueryPlanningTool",
                    "parameters": {
                        "model_id": model_id,
                        "response_filter": "$.output.message.content[0].text",
                    },
                },
            ],
        }
        resp = client.transport.perform_request(
            "POST", "/_plugins/_ml/agents/_register", body=body
        )
        agent_id = resp.get("agent_id")
        if not agent_id:
            return f"Failed to create agent: {resp}"
        return f"Flow agent '{agent_name}' (ID: {agent_id}) created successfully."
    except Exception as e:
        return f"Error creating flow agent: {e}"


def create_conversational_agent(agent_name: str, model_id: str, max_iterations: int = 10) -> str:
    """Create a conversational agentic search agent with memory for multi-turn conversations.

    Conversational agents support:
    - Multi-turn conversations with memory retention via memory_id
    - Context from previous questions in the conversation
    - Multiple tools: ListIndex, IndexMapping, WebSearch, QueryPlanning
    - Follow-up questions like "What about blue ones?" after asking about red cars

    Args:
        agent_name: Name for the agent (e.g., "my-conversational-agent")
        model_id: The deployed LLM model ID from deploy_agentic_model
        max_iterations: Maximum LLM iterations for query planning (default: 10)

    Returns:
        Agent ID or error message

    Reference: https://docs.opensearch.org/latest/vector-search/ai-search/agentic-search/agent-converse/
    """
    if not model_id:
        return "Error: model_id required."

    try:
        client = create_client()
        body = {
            "name": agent_name,
            "type": "conversational",
            "description": f"Conversational agentic search agent with memory for multi-turn queries",
            "llm": {
                "model_id": model_id,
                "parameters": {
                    "max_iteration": max_iterations
                }
            },
            "tools": [
                {"type": "ListIndexTool", "name": "ListIndexTool"},
                {"type": "IndexMappingTool", "name": "IndexMappingTool"},
                {
                    "type": "WebSearchTool",
                    "name": "DuckduckgoWebSearchTool",
                    "parameters": {"engine": "duckduckgo"}
                },
                {"type": "QueryPlanningTool", "name": "QueryPlanningTool"}
            ],
            "memory": {
                "type": "conversation_index"
            },
            "app_type": "os_chat",
            "parameters": {
                "_llm_interface": "bedrock/converse/claude"
            }
        }

        resp = client.transport.perform_request(
            "POST", "/_plugins/_ml/agents/_register", body=body
        )
        agent_id = resp.get("agent_id")
        if not agent_id:
            return f"Failed to create conversational agent: {resp}"

        return json.dumps({
            "agent_id": agent_id,
            "agent_name": agent_name,
            "type": "conversational",
            "message": f"Conversational agent '{agent_name}' created with memory support. Use memory_id in queries for multi-turn conversations.",
            "tools": ["ListIndexTool", "IndexMappingTool", "WebSearchTool", "QueryPlanningTool"]
        }, indent=2)
    except Exception as e:
        return f"Error creating conversational agent: {e}"


def create_agentic_pipeline(
    pipeline_name: str, agent_id: str, index_name: str
) -> str:
    if not agent_id or not index_name:
        return "Error: agent_id and index_name required."

    pipeline_body = {
        "request_processors": [
            {"agentic_query_translator": {"agent_id": agent_id}}
        ],
        "response_processors": [
            {
                "agentic_context": {
                    "agent_steps_summary": True,
                    "dsl_query": True,
                }
            }
        ],
    }

    try:
        client = create_client()
        client.transport.perform_request(
            "PUT", f"/_search/pipeline/{pipeline_name}", body=pipeline_body
        )
        client.indices.put_settings(
            index=index_name,
            body={"index": {"search.default_pipeline": pipeline_name}},
        )
        return f"Agentic pipeline '{pipeline_name}' attached to '{index_name}'."
    except Exception as e:
        return f"Failed to create agentic pipeline: {e}"
