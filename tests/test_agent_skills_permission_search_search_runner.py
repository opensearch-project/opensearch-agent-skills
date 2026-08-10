"""Embedding, query, and answer-provider tests for SearchRunner."""

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Make the scripts/lib package importable
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib import search_runner


def _profile(**overrides):
    profile = {
        "opensearch": {"index": "permission-aware-search"},
        "embedding": {"mode": "none", "dimension": 384},
    }
    profile.update(overrides)
    return profile


def _runner(monkeypatch, response, dimension=3):
    client = MagicMock()
    client.transport.perform_request.return_value = response
    monkeypatch.setattr(
        search_runner,
        "build_app_client",
        lambda _profile, username, password: client,
    )
    profile = {
        "opensearch": {"index": "permission-aware-search"},
        "embedding": {"mode": "local", "dimension": dimension},
    }
    runner = search_runner.SearchRunner(profile, "alice", "password")
    runner._get_model_id = MagicMock(return_value="model-1")
    return runner, client


def test_get_model_id_is_looked_up_once_per_runner(monkeypatch):
    client = MagicMock()
    client.transport.perform_request.return_value = {
        "hits": {"hits": [{"_id": "model-1", "_source": {"model_state": "DEPLOYED"}}]}
    }
    monkeypatch.setattr(
        search_runner,
        "build_app_client",
        lambda _profile, username, password: client,
    )
    runner = search_runner.SearchRunner(
        {
            "opensearch": {"index": "permission-aware-search"},
            "embedding": {"mode": "local", "dimension": 3},
        },
        "alice",
        "password",
    )

    assert [runner._get_model_id() for _ in range(5)] == ["model-1"] * 5
    # Repeating the lookup would add a round trip to every query and benchmark
    # iteration; the model id cannot change during a run.
    assert client.transport.perform_request.call_count == 1


def test_get_model_id_reports_a_model_that_is_not_deployed(monkeypatch):
    client = MagicMock()
    client.transport.perform_request.return_value = {"hits": {"hits": []}}
    monkeypatch.setattr(
        search_runner,
        "build_app_client",
        lambda _profile, username, password: client,
    )
    runner = search_runner.SearchRunner(
        {
            "opensearch": {"index": "permission-aware-search"},
            "embedding": {"mode": "local", "dimension": 3},
        },
        "alice",
        "password",
    )

    with pytest.raises(RuntimeError, match="not deployed"):
        runner._get_model_id()


def test_embed_requires_named_sentence_embedding(monkeypatch):
    response = {"inference_results": [{"output": [
        {"name": "input_ids", "data": [1, 2]},
        {"name": "sentence_embedding", "data": [0.1, 0.2, 0.3]},
    ]}]}
    runner, client = _runner(monkeypatch, response)

    assert runner._embed("hello") == [0.1, 0.2, 0.3]
    assert client.transport.perform_request.call_args.kwargs["body"] == {
        "text_docs": ["hello"],
        "return_number": True,
        "target_response": ["sentence_embedding"],
    }


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"inference_results": []},
        {"inference_results": [{}]},
    ],
)
def test_embed_rejects_missing_output_structure(monkeypatch, response):
    runner, _ = _runner(monkeypatch, response)

    with pytest.raises(RuntimeError, match="missing inference_results"):
        runner._embed("hello")


def test_embed_rejects_non_list_outputs(monkeypatch):
    runner, _ = _runner(
        monkeypatch,
        {"inference_results": [{"output": {"name": "sentence_embedding"}}]},
    )

    with pytest.raises(RuntimeError, match="output must be a list"):
        runner._embed("hello")


@pytest.mark.parametrize(
    "outputs",
    [
        [{"name": "input_ids", "data": [1, 2, 3]}],
        [
            {"name": "sentence_embedding", "data": [0.1, 0.2, 0.3]},
            {"name": "sentence_embedding", "data": [0.4, 0.5, 0.6]},
        ],
    ],
)
def test_embed_requires_exactly_one_named_output(monkeypatch, outputs):
    runner, _ = _runner(monkeypatch, {"inference_results": [{"output": outputs}]})

    with pytest.raises(RuntimeError, match="exactly one sentence_embedding"):
        runner._embed("hello")


@pytest.mark.parametrize(
    "embedding,actual",
    [
        ([0.1, 0.2], "2"),
        ([0.1, 0.2, 0.3, 0.4], "4"),
        ("not-a-vector", "non-list"),
    ],
)
def test_embed_rejects_dimension_mismatch(monkeypatch, embedding, actual):
    response = {"inference_results": [{"output": [{
        "name": "sentence_embedding",
        "data": embedding,
    }]}]}
    runner, _ = _runner(monkeypatch, response)

    with pytest.raises(RuntimeError, match=rf"expected 3, got {actual}"):
        runner._embed("hello")


@pytest.mark.parametrize(
    "embedding",
    [
        [0.1, "0.2", 0.3],
        [0.1, True, 0.3],
        [0.1, math.nan, 0.3],
        [0.1, math.inf, 0.3],
    ],
)
def test_embed_rejects_non_finite_or_non_numeric_values(monkeypatch, embedding):
    response = {"inference_results": [{"output": [{
        "name": "sentence_embedding",
        "data": embedding,
    }]}]}
    runner, _ = _runner(monkeypatch, response)

    with pytest.raises(RuntimeError, match="finite numeric values"):
        runner._embed("hello")


# ---------------------------------------------------------------------------
# search_runner - RAG optionality, query shape, LLM routing, find_document
# ---------------------------------------------------------------------------
def _query_runner(monkeypatch, prof, hits):
    fake = MagicMock()
    fake.search.return_value = {"hits": {"hits": hits, "total": {"value": len(hits)}}}
    monkeypatch.setattr(search_runner, "build_app_client", lambda p, username, password: fake)
    r = search_runner.SearchRunner(prof, username="alice", password="alice-password")
    return r, fake


def _hit(content="hello world", **src):
    src.setdefault("content", content)
    return {"_id": "d1", "_source": src}


def test_search_runner_requires_explicit_end_user_credentials(monkeypatch):
    build_client = MagicMock()
    monkeypatch.setattr(search_runner, "build_app_client", build_client)

    with pytest.raises(ValueError, match="end-user credentials"):
        search_runner.SearchRunner(_profile(), username="", password="pw")
    with pytest.raises(ValueError, match="end-user credentials"):
        search_runner.SearchRunner(_profile(), username="alice", password="")

    build_client.assert_not_called()


def test_search_runners_use_distinct_authenticated_identities(monkeypatch):
    calls = []

    def build_client(profile, username, password):
        calls.append((username, password))
        return MagicMock()

    monkeypatch.setattr(search_runner, "build_app_client", build_client)

    search_runner.SearchRunner(_profile(), username="alice", password="alice-password")
    search_runner.SearchRunner(_profile(), username="bob", password="bob-password")

    assert calls == [
        ("alice", "alice-password"),
        ("bob", "bob-password"),
    ]


def test_query_default_does_not_call_llm(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(), [_hit(title="T", content="body text here")])
    r._call_llm = MagicMock(side_effect=AssertionError("LLM must not be called in search mode"))
    result = r.query("q", rag=False)
    assert result["mode"] == "search"
    assert result["answer"] is None
    assert result["hits"][0]["title"] == "T"
    assert result["hits"][0]["snippet"] == "body text here"


def test_query_rag_calls_llm(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(), [_hit(content="ctx")])
    r._call_llm = MagicMock(return_value="the answer")
    result = r.query("q", rag=True)
    assert result["mode"] == "rag"
    assert result["answer"] == "the answer"


def test_query_empty_hits_both_modes(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(), [])
    r._call_llm = MagicMock(side_effect=AssertionError("no LLM with zero hits"))
    assert r.query("q", rag=True)["answer"] is None
    assert r.query("q", rag=False)["hits"] == []


def test_search_combines_bm25_and_knn_with_boolean_scoring(monkeypatch):
    r, fake = _query_runner(monkeypatch, _profile(embedding={"mode": "local", "dimension": 384}), [])
    r._embed = MagicMock(return_value=[0.0] * 384)
    r._search("q", 5)
    body = fake.search.call_args.kwargs["body"]
    assert "hybrid" not in body["query"]
    shoulds = body["query"]["bool"]["should"]
    assert body["query"]["bool"]["minimum_should_match"] == 1
    assert len(shoulds) == 2
    assert any("multi_match" in c for c in shoulds)
    assert any("knn" in c for c in shoulds)


def test_search_bm25_shape_for_none(monkeypatch):
    r, fake = _query_runner(monkeypatch, _profile(embedding={"mode": "none"}), [])
    r._search("q", 5)
    body = fake.search.call_args.kwargs["body"]
    assert "multi_match" in body["query"]
    assert body["query"]["multi_match"]["fields"] == ["title^2", "content"]


@pytest.mark.parametrize("mode", ["none", "local"])
def test_search_matches_exactly_without_fuzziness(monkeypatch, mode):
    # The shared lexical builder adds fuzziness: AUTO by default. This index has a
    # fixed mapping and tuned scoring, so the emitted query must not carry it.
    r, fake = _query_runner(
        monkeypatch, _profile(embedding={"mode": mode, "dimension": 3}), []
    )
    if mode == "local":
        r._embed = lambda text: [0.1, 0.2, 0.3]

    r._search("q", 5)

    body = fake.search.call_args.kwargs["body"]
    assert "fuzziness" not in json.dumps(body)


def test_find_document_true_false(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(search_runner, "build_app_client", lambda p, username, password: fake)
    r = search_runner.SearchRunner(_profile(), username="alice", password="alice-password")
    fake.search.return_value = {"hits": {"total": {"value": 1}}}
    assert r.find_document("d1") is True
    fake.search.return_value = {"hits": {"total": {"value": 0}}}
    assert r.find_document("d1") is False


def _fake_opener(monkeypatch, response=None, side_effect=None):
    """Replace the hardened opener, capturing the URLs it was asked to validate."""
    validated = []
    monkeypatch.setattr(
        search_runner,
        "validate_url",
        lambda url, **kwargs: validated.append((url, kwargs)),
    )
    opener = MagicMock()
    if side_effect is not None:
        opener.open.side_effect = side_effect
    else:
        opener.open.return_value = response
    monkeypatch.setattr(
        search_runner, "build_safe_opener", lambda **kwargs: opener
    )
    return validated


def test_call_llm_openai_compatible_success(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(llm={"provider": "openai_compatible"}), [])
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps({
        "choices": [{"message": {"content": "local answer"}}]
    }).encode()
    fake_resp.__enter__.return_value = fake_resp
    _fake_opener(monkeypatch, response=fake_resp)

    assert r._call_llm("q", "[1] ctx") == "local answer"


def test_call_llm_validates_the_endpoint_url_before_sending_the_prompt(monkeypatch):
    r, _ = _query_runner(
        monkeypatch,
        _profile(llm={"provider": "openai_compatible", "base_url": "http://localhost:12434/engines/v1"}),
        [],
    )
    fake_resp = MagicMock()
    fake_resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "ok"}}]}
    ).encode()
    fake_resp.__enter__.return_value = fake_resp
    validated = _fake_opener(monkeypatch, response=fake_resp)

    r._call_llm("q", "[1] ctx")

    # The prompt carries content the caller is authorized to read, so the
    # destination is checked first. Loopback is allowed for a local runner.
    assert validated == [
        ("http://localhost:12434/engines/v1/chat/completions", {"allow_loopback": True})
    ]


def test_call_llm_refuses_an_endpoint_rejected_by_url_validation(monkeypatch):
    r, _ = _query_runner(
        monkeypatch,
        _profile(llm={"provider": "openai_compatible", "base_url": "http://169.254.169.254"}),
        [],
    )

    def reject(url, **kwargs):
        raise ValueError("URL resolves to a restricted address: 169.254.169.254")

    monkeypatch.setattr(search_runner, "validate_url", reject)

    with pytest.raises(search_runner.LLMProviderError) as exc:
        r._call_llm("q", "[1] ctx")

    assert exc.value.provider == "openai_compatible"
    # The rejected address must not leak through the sanitized error.
    assert "169.254.169.254" not in str(exc.value)


def test_call_llm_unconfigured_falls_back_to_excerpt(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(), [])
    out = r._call_llm("q", "[1] top chunk")
    assert out.startswith("(No LLM configured")


def test_call_llm_openai_compatible_error_is_visible(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(llm={"provider": "openai_compatible"}), [])
    _fake_opener(monkeypatch, side_effect=RuntimeError("connection refused"))

    with pytest.raises(search_runner.LLMProviderError) as exc:
        r._call_llm("q", "[1] top chunk")

    assert exc.value.provider == "openai_compatible"
    assert exc.value.category == "provider"
    assert "connection refused" not in str(exc.value)


def test_call_llm_unknown_provider_is_configuration_error(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(llm={"provider": "mystery"}), [])
    with pytest.raises(search_runner.LLMProviderError) as exc:
        r._call_llm("q", "[1] top chunk")
    assert exc.value.category == "configuration"


def _bedrock_sdk(client):
    boto3 = MagicMock()
    boto3.client.return_value = client
    return boto3


def test_call_bedrock_import_failure_is_visible(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(llm={"provider": "bedrock"}), [])
    monkeypatch.setattr(
        search_runner, "_load_bedrock_sdk", MagicMock(side_effect=ImportError("boto3"))
    )

    with pytest.raises(search_runner.LLMProviderError) as exc:
        r._call_llm("q", "[1] context")

    assert exc.value.provider == "bedrock"
    assert exc.value.category == "configuration"
    assert "--group ingestion" in str(exc.value)


def test_call_bedrock_provider_failure_is_sanitized(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(llm={"provider": "bedrock"}), [])
    client = MagicMock()
    client.invoke_model.side_effect = RuntimeError("secret access key")
    monkeypatch.setattr(search_runner, "_load_bedrock_sdk", lambda: _bedrock_sdk(client))

    with pytest.raises(search_runner.LLMProviderError) as exc:
        r._call_llm("q", "[1] context")

    assert exc.value.category == "provider"
    assert "secret access key" not in str(exc.value)


def test_call_bedrock_invalid_response_is_visible(monkeypatch):
    r, _ = _query_runner(monkeypatch, _profile(llm={"provider": "bedrock"}), [])
    client = MagicMock()
    client.invoke_model.return_value = {
        "body": SimpleNamespace(read=lambda: b'{"content": []}')
    }
    monkeypatch.setattr(search_runner, "_load_bedrock_sdk", lambda: _bedrock_sdk(client))

    with pytest.raises(search_runner.LLMProviderError) as exc:
        r._call_llm("q", "[1] context")

    assert exc.value.category == "invalid_response"


def test_call_bedrock_returns_valid_answer(monkeypatch):
    profile = _profile(llm={
        "provider": "bedrock",
        "region": "eu-west-1",
        "model_id": "anthropic.test-model",
        "max_tokens": 20,
    })
    r, _ = _query_runner(monkeypatch, profile, [])
    client = MagicMock()
    client.invoke_model.return_value = {
        "body": SimpleNamespace(read=lambda: b'{"content": [{"text": "bedrock answer"}]}')
    }
    sdk = _bedrock_sdk(client)
    monkeypatch.setattr(search_runner, "_load_bedrock_sdk", lambda: sdk)

    assert r._call_llm("q", "[1] context") == "bedrock answer"
    sdk.client.assert_called_once_with("bedrock-runtime", region_name="eu-west-1")
    assert client.invoke_model.call_args.kwargs["modelId"] == "anthropic.test-model"
