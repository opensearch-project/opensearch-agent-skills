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

DEFAULT_TEXT_EMBEDDING_MODEL = "huggingface/sentence-transformers/all-MiniLM-L6-v2"


# ---------------------------------------------------------------------------
# ML helpers
# ---------------------------------------------------------------------------
def find_registered_model(client: OpenSearch, model_name: str) -> dict | None:
    """Return the root document of a registered model, or None if absent.

    Chunk sub-documents are excluded: they carry `chunk_number` and no
    `model_state`, so only the root document reports deployment state.
    """
    response = client.transport.perform_request(
        "GET", "/_plugins/_ml/models/_search",
        body={
            "query": {
                "bool": {
                    "must": [{"match": {"name": model_name}}],
                    "must_not": [{"exists": {"field": "chunk_number"}}],
                }
            },
            "size": 1,
        },
    )
    hits = response.get("hits", {}).get("hits", [])
    return hits[0] if hits else None



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
# Pipeline helpers
# ---------------------------------------------------------------------------
def put_ingest_pipeline(client: OpenSearch, pipeline_id: str, body: dict) -> None:
    """Create or replace an ingest pipeline. Raises on failure."""
    client.transport.perform_request(
        "PUT", f"/_ingest/pipeline/{pipeline_id}", body=body
    )


def attach_default_pipeline(client: OpenSearch, index_name: str, pipeline_id: str) -> None:
    """Make an ingest pipeline the index default, so every write runs it."""
    client.indices.put_settings(
        index=index_name, body={"index": {"default_pipeline": pipeline_id}}
    )


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
            "pre_process_function": "connector.pre_process.bedrock.embedding",
            "post_process_function": "connector.post_process.bedrock.embedding",
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
    model_name: str = "us.anthropic.claude-sonnet-4-6",
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


def deploy_rag_model(
    access_key: str,
    secret_key: str,
    region: str = "us-east-1",
    session_token: str = "",
    model_name: str = "us.anthropic.claude-sonnet-4-6",
) -> str:
    """Deploy a Bedrock model for the RAG processor.

    The RAG processor passes context via ${parameters.inputs}; the connector
    template uses the /invoke API, unlike the agent connector which uses
    ${parameters.system_prompt}/${parameters.user_prompt} (the /converse API).
    """
    if not access_key or not secret_key:
        return "Error: AWS credentials required."

    creds = {"access_key": access_key.strip(), "secret_key": secret_key.strip()}
    if session_token and session_token.strip():
        creds["session_token"] = session_token.strip()

    register_body = {
        "name": f"rag-model-{int(time.time())}",
        "function_name": "remote",
        "connector": {
            "name": f"Bedrock Claude RAG Connector {int(time.time())}",
            "description": "Bedrock connector for RAG processor (invoke API)",
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
                "url": f"https://bedrock-runtime.{region.strip()}.amazonaws.com/model/{model_name}/invoke",
                "headers": {"content-type": "application/json"},
                "request_body": '{"anthropic_version":"bedrock-2023-05-31","max_tokens":1024,"messages":[{"role":"user","content":[{"type":"text","text":"${parameters.inputs}"}]}]}',
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
        return f"Error creating RAG model: {e}"


# ---------------------------------------------------------------------------
# Flow agent builders (subclass pattern: sparse vs dense)
# ---------------------------------------------------------------------------


class FlowAgentBuilder:
    """Base class for building flow agents."""

    def __init__(self, client: OpenSearch, agent_name: str, model_id: str,
                 embedding_model_id: str = "", index_name: str = ""):
        self.client = client
        self.agent_name = agent_name
        self.model_id = model_id
        self.embedding_model_id = embedding_model_id
        self.index_name = index_name

    def build_tools(self) -> list:
        raise NotImplementedError

    def description(self) -> str:
        return "Flow agent for agentic search"

    def create(self) -> str:
        body = {
            "name": self.agent_name,
            "type": "flow",
            "description": self.description(),
            "tools": self.build_tools(),
        }
        resp = self.client.transport.perform_request(
            "POST", "/_plugins/_ml/agents/_register", body=body
        )
        agent_id = resp.get("agent_id")
        if not agent_id:
            return f"Failed to create agent: {resp}"
        return f"Flow agent '{self.agent_name}' (ID: {agent_id}) created successfully."


class DenseFlowAgentBuilder(FlowAgentBuilder):
    """Dense path: IndexMappingTool + QueryPlanningTool generates DSL with neural queries.

    Works with knn_vector fields. The generated DSL is executed by the
    agentic_query_translator search pipeline processor.
    """

    def build_tools(self) -> list:
        params: dict = {
            "model_id": self.model_id,
            "response_filter": "$.output.message.content[0].text",
        }
        if self.embedding_model_id:
            params["embedding_model_id"] = self.embedding_model_id
        return [
            {"type": "IndexMappingTool", "name": "IndexMappingTool"},
            {"type": "QueryPlanningTool", "parameters": params},
        ]


class SparseFlowAgentBuilder(FlowAgentBuilder):
    """Sparse path: NeuralSparseSearchTool executes neural_sparse search directly.

    Works with rank_features fields. The agent performs the search itself —
    no agentic_query_translator pipeline needed.
    """

    SPARSE_FIELD = "text_sparse"

    def description(self) -> str:
        return "Flow agent for sparse agentic search"

    def _detect_source_fields(self) -> list:
        """Read index mapping to find non-vector fields for source retrieval."""
        try:
            mapping_resp = self.client.indices.get_mapping(index=self.index_name)
            props = next(iter(mapping_resp.values()), {}).get(
                "mappings", {}
            ).get("properties", {})
            return [
                f for f, spec in props.items()
                if spec.get("type") not in ("rank_features", "knn_vector")
            ]
        except Exception:
            return ["text", "headings", "source_file", "chunk_id", "page_number"]

    def _detect_sparse_field(self) -> str:
        """Find the rank_features field name from mapping."""
        try:
            mapping_resp = self.client.indices.get_mapping(index=self.index_name)
            props = next(iter(mapping_resp.values()), {}).get(
                "mappings", {}
            ).get("properties", {})
            for f, spec in props.items():
                if spec.get("type") == "rank_features":
                    return f
        except Exception:
            pass
        return self.SPARSE_FIELD

    def build_tools(self) -> list:
        source_fields = self._detect_source_fields()
        sparse_field = self._detect_sparse_field()
        return [
            {
                "type": "NeuralSparseSearchTool",
                "parameters": {
                    "index": self.index_name,
                    "embedding_field": sparse_field,
                    "source_field": json.dumps(source_fields),
                    "model_id": self.embedding_model_id,
                },
                "include_output_in_agent_response": True,
            },
        ]


def create_flow_agent(
    agent_name: str, model_id: str, embedding_model_id: str = "",
    index_name: str = "", is_sparse: bool = False,
) -> str:
    """Create a flow agent for agentic search.

    Args:
        agent_name: Name for the agent.
        model_id: Deployed LLM model ID (Bedrock Claude).
        embedding_model_id: Model ID for embeddings (sparse tokenizer or dense encoder).
        index_name: Target index (required for sparse).
        is_sparse: True = NeuralSparseSearchTool (rank_features).
                   False = QueryPlanningTool (knn_vector / dense).
    """
    if not model_id:
        return "Error: model_id required."
    if is_sparse and not index_name:
        return "Error: --index required for sparse flow agent."

    try:
        client = create_client()
        if is_sparse:
            builder = SparseFlowAgentBuilder(
                client, agent_name, model_id, embedding_model_id, index_name
            )
        else:
            builder = DenseFlowAgentBuilder(
                client, agent_name, model_id, embedding_model_id, index_name
            )
        return builder.create()
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


def create_flow_agentic_pipeline(
    pipeline_name: str, agent_id: str, index_name: str,
    embedding_model_id: str = "", is_sparse: bool = False,
    agentic_model_id: str = "",
) -> str:
    """Create a search pipeline for Flow Agent (stateless, low-latency).

    Two modes:
    - Dense (is_sparse=False): Uses agentic_query_translator so the agent generates
      DSL. Optional neural_query_enricher injects model_id into neural queries.
    - Sparse (is_sparse=True): Agent searches directly via NeuralSparseSearchTool.
      No search pipeline needed. Agent metadata stored in index _meta for the
      backend to call agent._execute at search time.
    """
    if not agent_id or not index_name:
        return "Error: agent_id and index_name required."

    try:
        client = create_client()

        if is_sparse:
            # Sparse: store agent config in index _meta; backend calls agent directly.
            meta = {
                "agentic_agent_id": agent_id,
                "agentic_type": "sparse",
            }
            if agentic_model_id:
                meta["agentic_model_id"] = agentic_model_id
            client.indices.put_mapping(
                index=index_name,
                body={"_meta": meta},
            )
            # Clear any existing search pipeline that might interfere
            try:
                client.indices.put_settings(
                    index=index_name,
                    body={"index": {"search.default_pipeline": "_none"}},
                )
            except Exception:
                pass
            return (
                f"Sparse agentic config stored in '{index_name}' _meta "
                f"(agent_id: {agent_id}). Agent executes search directly "
                f"via NeuralSparseSearchTool."
            )
        else:
            # Dense: agentic_query_translator pipeline
            request_processors: list = [
                {"agentic_query_translator": {"agent_id": agent_id}}
            ]
            if embedding_model_id:
                request_processors.append(
                    {"neural_query_enricher": {"default_model_id": embedding_model_id}}
                )

            pipeline_body = {
                "request_processors": request_processors,
                "response_processors": [
                    {"agentic_context": {"dsl_query": True}}
                ],
            }

            client.transport.perform_request(
                "PUT", f"/_search/pipeline/{pipeline_name}", body=pipeline_body
            )
            client.indices.put_settings(
                index=index_name,
                body={"index": {"search.default_pipeline": pipeline_name}},
            )
            return f"Flow agent pipeline '{pipeline_name}' attached to '{index_name}'."
    except Exception as e:
        return f"Failed to create flow agent pipeline: {e}"


def create_conversational_agent_pipeline(
    pipeline_name: str, agent_id: str, index_name: str, model_id: str
) -> str:
    """Create a search pipeline for Conversational Agent with RAG processor.

    Conversational agents support multi-turn conversations with context retention.
    The RAG processor enriches responses with context from retrieved documents.
    context_field_list is auto-detected from the index mapping (text/keyword fields).
    """
    if not agent_id or not index_name or not model_id:
        return "Error: agent_id, index_name, and model_id required."

    # Auto-detect text fields from index mapping for RAG context
    try:
        client = create_client()
        mapping = client.indices.get_mapping(index=index_name)
        props = mapping.get(index_name, {}).get("mappings", {}).get("properties", {})
        context_fields = [
            f for f, spec in props.items()
            if spec.get("type") in ("text", "keyword")
        ]
    except Exception as e:
        return f"Error: could not read index mapping for '{index_name}': {e}"

    if not context_fields:
        return f"Error: no text/keyword fields found in index '{index_name}'."

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
            },
            {
                "retrieval_augmented_generation": {
                    "model_id": model_id,
                    "context_field_list": context_fields,
                    "system_prompt": "You are a helpful assistant. Answer the user's question based on the provided context.",
                    "user_instructions": "Answer the question based on the search results provided as context.",
                }
            },
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
        return f"Conversational agent pipeline '{pipeline_name}' with RAG attached to '{index_name}'."
    except Exception as e:
        return f"Failed to create conversational agent pipeline: {e}"
