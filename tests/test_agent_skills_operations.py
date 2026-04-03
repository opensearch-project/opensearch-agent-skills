"""Tests for skills/opensearch-skills/scripts/lib/operations.py"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.operations import (
    PRETRAINED_MODELS,
    _wait_for_ml_task,
    create_index,
    index_doc,
    index_bulk,
    search,
    create_pipeline,
    deploy_local_model,
    deploy_bedrock_model,
    deploy_agentic_model,
    create_flow_agent,
    create_conversational_agent,
    create_agentic_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeIndices:
    def __init__(self, exists=False):
        self._exists = exists
        self.created = []
        self.deleted = []
        self.refreshed = []
        self.settings_calls = []

    def exists(self, index):
        return self._exists

    def create(self, index, body):
        self.created.append((index, body))

    def delete(self, index, ignore=None):
        self.deleted.append(index)

    def refresh(self, index):
        self.refreshed.append(index)

    def put_settings(self, index, body):
        self.settings_calls.append((index, body))


class _FakeTransport:
    def __init__(self, responses=None):
        self._responses = responses or []
        self._call_index = 0
        self.calls = []

    def perform_request(self, method, url, body=None, **kwargs):
        self.calls.append((method, url, body))
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            return resp
        return {}


class _FakeClient:
    def __init__(self, exists=False, transport_responses=None):
        self.indices = _FakeIndices(exists)
        self.transport = _FakeTransport(transport_responses)
        self._indexed = []
        self._get_response = {}
        self._search_response = {"hits": {"hits": [], "total": {"value": 0}}, "took": 1}
        self._bulk_errors = []  # For simulating bulk errors

    def index(self, index, body, id):
        self._indexed.append((index, body, id))

    def bulk(self, body):
        """Simulate bulk indexing API"""
        items = []
        # Process bulk body (alternating action/doc pairs)
        for i in range(0, len(body), 2):
            action = body[i]
            doc = body[i + 1]

            # Check if this doc should error (for partial failure tests)
            doc_id = action["index"]["_id"]
            if doc_id in self._bulk_errors:
                items.append({
                    "index": {
                        "_id": doc_id,
                        "error": {"type": "simulated_error", "reason": "test error"}
                    }
                })
            else:
                items.append({
                    "index": {
                        "_id": doc_id,
                        "_index": action["index"]["_index"],
                        "result": "created"
                    }
                })
                self._indexed.append((action["index"]["_index"], doc, doc_id))

        return {"items": items, "errors": len(self._bulk_errors) > 0}

    def get(self, index, id):
        return self._get_response or {"_source": {}, "_id": id}

    def search(self, index, body, size=10):
        return self._search_response


# ---------------------------------------------------------------------------
# _wait_for_ml_task
# ---------------------------------------------------------------------------
def test_wait_for_ml_task_completed():
    client = MagicMock()
    client.transport.perform_request.return_value = {"state": "COMPLETED", "model_id": "m-1"}

    state, res = _wait_for_ml_task(client, "task-1", max_polls=2, interval=0)

    assert state == "COMPLETED"
    assert res["model_id"] == "m-1"


def test_wait_for_ml_task_failed():
    client = MagicMock()
    client.transport.perform_request.return_value = {"state": "FAILED", "error": "oom"}

    state, res = _wait_for_ml_task(client, "task-1", max_polls=2, interval=0)

    assert state == "FAILED"
    assert res["error"] == "oom"


def test_wait_for_ml_task_timeout():
    client = MagicMock()
    client.transport.perform_request.return_value = {"state": "RUNNING"}

    state, res = _wait_for_ml_task(client, "task-1", max_polls=2, interval=0)

    assert state == "TIMEOUT"


def test_wait_for_ml_task_missing_task_id():
    client = MagicMock()

    state, res = _wait_for_ml_task(client, "", max_polls=2, interval=0)

    assert state == "FAILED"
    assert "Missing task_id" in res["error"]


# ---------------------------------------------------------------------------
# create_index
# ---------------------------------------------------------------------------
def test_create_index_new_index(monkeypatch):
    fake = _FakeClient(exists=False)
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_index("test-index", {"mappings": {}})

    assert "created successfully" in result
    assert fake.indices.created == [("test-index", {"mappings": {}})]


def test_create_index_replace_existing(monkeypatch):
    fake = _FakeClient(exists=True)
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_index("test-index", {}, replace_if_exists=True)

    assert "recreated" in result
    assert "test-index" in fake.indices.deleted


def test_create_index_skip_existing(monkeypatch):
    fake = _FakeClient(exists=True)
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_index("test-index", {}, replace_if_exists=False)

    assert "already exists" in result
    assert fake.indices.created == []


def test_create_index_connection_failure(monkeypatch):
    monkeypatch.setattr("lib.operations.create_client", lambda: (_ for _ in ()).throw(RuntimeError("no docker")))

    result = create_index("test-index")

    assert "Failed to create index" in result


# ---------------------------------------------------------------------------
# index_doc
# ---------------------------------------------------------------------------
def test_index_doc_success(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = index_doc("my-index", {"title": "Hello"}, "doc-1")

    assert fake._indexed == [("my-index", {"title": "Hello"}, "doc-1")]
    assert "my-index" in fake.indices.refreshed
    parsed = json.loads(result)
    assert parsed["_id"] == "doc-1"


def test_index_doc_failure(monkeypatch):
    class _FailClient(_FakeClient):
        def index(self, index, body, id):
            raise Exception("mapping error")

    monkeypatch.setattr("lib.operations.create_client", lambda: _FailClient())

    result = index_doc("my-index", {"title": "Hello"}, "doc-1")

    assert "Failed to index document" in result


# ---------------------------------------------------------------------------
# index_bulk
# ---------------------------------------------------------------------------
def test_index_bulk_success(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    docs = [{"a": 1}, {"a": 2}, {"a": 3}]
    result = json.loads(index_bulk("bulk-index", docs, id_prefix="test"))

    assert result["indexed_count"] == 3
    assert result["doc_ids"] == ["test-1", "test-2", "test-3"]
    assert result["errors"] == []
    assert "bulk-index" in fake.indices.refreshed


def test_index_bulk_partial_failure(monkeypatch):
    fake = _FakeClient()
    fake._bulk_errors = ["doc-2"]  # Simulate doc-2 failing
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    docs = [{"a": 1}, {"a": 2}, {"a": 3}]
    result = json.loads(index_bulk("bulk-index", docs))

    assert result["indexed_count"] == 2
    assert len(result["errors"]) == 1
    assert "doc-2" in result["errors"][0]


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def test_search_default_match_all():
    fake = _FakeClient()

    result = search(fake, "my-index")

    assert result["took"] == 1


def test_search_with_custom_body():
    fake = _FakeClient()
    body = {"query": {"term": {"status": "active"}}}

    search(fake, "my-index", body=body, size=5)
    # Just verify it doesn't raise


# ---------------------------------------------------------------------------
# create_pipeline
# ---------------------------------------------------------------------------
def test_create_pipeline_hybrid_search_auto_body(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_pipeline(
        pipeline_name="hybrid-pipe",
        pipeline_body={},
        index_name="my-index",
        pipeline_type="search",
        is_hybrid=True,
        hybrid_weights=[0.3, 0.7],
    )

    assert "created and attached" in result
    assert fake.transport.calls
    method, url, body = fake.transport.calls[0]
    assert method == "PUT"
    assert "/_search/pipeline/hybrid-pipe" in url
    assert body["phase_results_processors"][0]["normalization-processor"]["combination"]["parameters"]["weights"] == [0.3, 0.7]


def test_create_pipeline_ingest_requires_body(monkeypatch):
    result = create_pipeline(
        pipeline_name="ingest-pipe",
        pipeline_body={},
        index_name="my-index",
        pipeline_type="ingest",
    )

    assert "Error: pipeline_body required" in result


def test_create_pipeline_requires_index_name():
    result = create_pipeline(
        pipeline_name="pipe",
        pipeline_body={"processors": []},
        index_name="",
    )

    assert "Error: index_name is required" in result


# ---------------------------------------------------------------------------
# deploy_local_model
# ---------------------------------------------------------------------------
def test_deploy_local_model_unsupported():
    result = deploy_local_model("not-a-real-model")

    assert "not supported" in result
    assert "Supported:" in result


def test_deploy_local_model_success(monkeypatch):
    fake = _FakeClient(transport_responses=[
        {},                                            # set_ml_settings (PUT /_cluster/settings)
        {"task_id": "reg-task-1"},                    # register
        {"state": "COMPLETED", "model_id": "m-1"},    # poll register
        {"task_id": "dep-task-1"},                    # deploy
        {"state": "COMPLETED"},                        # poll deploy
    ])
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    model = list(PRETRAINED_MODELS.keys())[0]
    result = deploy_local_model(model)

    assert "deployed successfully" in result
    assert "m-1" in result


# ---------------------------------------------------------------------------
# deploy_bedrock_model
# ---------------------------------------------------------------------------
def test_deploy_bedrock_model_unsupported():
    result = deploy_bedrock_model("wrong-model")

    assert "Only amazon.titan-embed-text-v2:0 is supported" in result


def test_deploy_bedrock_model_missing_credentials(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    result = deploy_bedrock_model("amazon.titan-embed-text-v2:0")

    assert "AWS credentials" in result


# ---------------------------------------------------------------------------
# deploy_agentic_model
# ---------------------------------------------------------------------------
def test_deploy_agentic_model_missing_credentials():
    result = deploy_agentic_model(access_key="", secret_key="")

    assert "Error: AWS credentials required" in result


def test_deploy_agentic_model_success(monkeypatch):
    fake = _FakeClient(transport_responses=[
        {},  # set_ml_settings
        {"model_id": "agentic-m-1"},  # register+deploy
    ])
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = deploy_agentic_model(access_key="AK", secret_key="SK", region="us-west-2")

    assert result == "agentic-m-1"


# ---------------------------------------------------------------------------
# create_flow_agent
# ---------------------------------------------------------------------------
def test_create_flow_agent_missing_model_id():
    result = create_flow_agent("my-agent", "")

    assert "Error: model_id required" in result


def test_create_flow_agent_success(monkeypatch):
    fake = _FakeClient(transport_responses=[{"agent_id": "agent-1"}])
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_flow_agent("my-agent", "model-1")

    assert "created successfully" in result
    assert "agent-1" in result


# ---------------------------------------------------------------------------
# create_conversational_agent
# ---------------------------------------------------------------------------
def test_create_conversational_agent_missing_model_id():
    result = create_conversational_agent("my-conv-agent", "")

    assert "Error: model_id required" in result


def test_create_conversational_agent_success(monkeypatch):
    fake = _FakeClient(transport_responses=[{"agent_id": "conv-agent-1"}])
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_conversational_agent("my-conv-agent", "model-1", max_iterations=15)

    assert "conv-agent-1" in result
    assert "conversational" in result.lower()
    assert "memory" in result.lower()


def test_create_conversational_agent_default_iterations(monkeypatch):
    fake = _FakeClient(transport_responses=[{"agent_id": "conv-agent-2"}])
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_conversational_agent("my-conv-agent", "model-1")

    assert "conv-agent-2" in result
    # Verify it uses default max_iterations=10
    assert fake.transport.calls[0][2]["llm"]["parameters"]["max_iteration"] == 10


# ---------------------------------------------------------------------------
# create_agentic_pipeline
# ---------------------------------------------------------------------------
def test_create_agentic_pipeline_missing_params():
    assert "Error:" in create_agentic_pipeline("pipe", "", "idx")
    assert "Error:" in create_agentic_pipeline("pipe", "agent-1", "")


def test_create_agentic_pipeline_success(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr("lib.operations.create_client", lambda: fake)

    result = create_agentic_pipeline("agentic-pipe", "agent-1", "my-index")

    assert "attached to" in result
    assert fake.transport.calls
    assert fake.indices.settings_calls


# ---------------------------------------------------------------------------
# PRETRAINED_MODELS registry
# ---------------------------------------------------------------------------
def test_pretrained_models_has_entries():
    assert len(PRETRAINED_MODELS) > 10


def test_pretrained_models_all_have_versions():
    for name, version in PRETRAINED_MODELS.items():
        assert version, f"Model {name} has empty version"
