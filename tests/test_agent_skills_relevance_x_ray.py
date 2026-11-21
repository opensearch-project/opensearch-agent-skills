"""CLI orchestration tests for Relevance X-Ray."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from opensearchpy.exceptions import NotFoundError

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "search"
    / "relevance-x-ray"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

import relevance_x_ray


def _term_explanation(doc_number=0, value=1.0):
    return {
        "value": value,
        "description": "sum of:",
        "details": [{
            "value": value,
            "description": (
                f"weight(title:wireless in {doc_number}) "
                "[PerFieldSimilarity], result of:"
            ),
            "details": [],
        }],
    }


class _Indices:
    def get_mapping(self, index):
        return {
            index: {
                "mappings": {
                    "properties": {
                        "title": {"type": "text"},
                        "description": {"type": "text"},
                        "price": {"type": "float"},
                    }
                }
            }
        }

    def get_settings(self, index):
        return {index: {"settings": {"index": {}}}}

    def analyze(self, index, body):
        text = body["text"]
        if isinstance(text, list):
            text = " ".join(text)
        return {
            "tokens": [
                {"token": token.strip(".,").lower()}
                for token in text.split()
                if token.strip(".,")
            ]
        }


class _ExplainClient:
    def __init__(self):
        self.indices = _Indices()
        self.search_requests = []

    def search(self, **kwargs):
        self.search_requests.append(kwargs)
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "competitor",
                        "_score": 2.0,
                        "_explanation": _term_explanation(0, 2.0),
                    },
                    {
                        "_id": "target",
                        "_score": 1.0,
                        "_explanation": _term_explanation(1, 1.0),
                    },
                ]
            }
        }


def test_checked_client_stops_after_failed_preflight(monkeypatch):
    monkeypatch.setattr(
        relevance_x_ray,
        "_preflight_result",
        lambda args: {"status": "no_cluster", "message": "unreachable"},
    )
    monkeypatch.setattr(
        relevance_x_ray,
        "build_client",
        lambda **kwargs: pytest.fail("no client must be built after failed preflight"),
    )
    with pytest.raises(RuntimeError, match="unreachable"):
        relevance_x_ray._checked_client(SimpleNamespace())


def test_checked_client_never_bootstraps_if_cluster_disappears(monkeypatch):
    monkeypatch.setattr(
        relevance_x_ray,
        "_preflight_result",
        lambda args: {"status": "available"},
    )
    monkeypatch.setattr(relevance_x_ray, "resolve_http_auth", lambda: None)
    monkeypatch.setattr(
        relevance_x_ray,
        "build_client",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        relevance_x_ray,
        "can_connect",
        lambda client: (False, False),
    )
    with pytest.raises(RuntimeError, match="became unavailable"):
        relevance_x_ray._checked_client(SimpleNamespace())


def test_checked_client_never_sends_remote_credentials_over_http(monkeypatch):
    attempts = []
    monkeypatch.setattr(
        relevance_x_ray,
        "_preflight_result",
        lambda args: {
            "status": "available",
            "host": "search.example.com",
        },
    )
    monkeypatch.setattr(
        relevance_x_ray,
        "resolve_http_auth",
        lambda: ("service-user", "secret"),
    )
    monkeypatch.setattr(
        relevance_x_ray,
        "build_client",
        lambda use_ssl, http_auth: attempts.append(use_ssl) or object(),
    )
    monkeypatch.setattr(
        relevance_x_ray,
        "can_connect",
        lambda client: (False, False),
    )

    with pytest.raises(RuntimeError, match="became unavailable"):
        relevance_x_ray._checked_client(SimpleNamespace())

    assert attempts == [True]


def test_preflight_reads_password_from_environment(monkeypatch):
    captured = {}
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "environment-secret")
    monkeypatch.setattr(
        relevance_x_ray,
        "preflight_check_cluster",
        lambda **kwargs: captured.update(kwargs) or {"status": "available"},
    )

    relevance_x_ray._preflight_result(
        SimpleNamespace(auth_mode="custom", username="service-user")
    )

    assert captured == {
        "auth_mode": "custom",
        "username": "service-user",
        "password": "environment-secret",
    }


def test_cli_rejects_password_argument(monkeypatch):
    monkeypatch.setattr(relevance_x_ray, "cmd_preflight_check", lambda args: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["relevance_x_ray.py", "preflight-check", "--password", "visible-secret"],
    )

    with pytest.raises(SystemExit) as exc_info:
        relevance_x_ray.main()

    assert exc_info.value.code == 2


def test_analyzer_evidence_uses_field_for_index_time_analysis():
    analyze_requests = []

    class _AnalyzerIndices:
        def analyze(self, index, body):
            analyze_requests.append(body)
            token = "run" if body.get("field") == "title" else "running"
            return {"tokens": [{"token": token}]}

    class _AnalyzerClient:
        indices = _AnalyzerIndices()

        def termvectors(self, index, id, body):
            return {
                "term_vectors": {
                    "title": {
                        "terms": {
                            "run": {},
                        }
                    }
                }
            }

    metadata = SimpleNamespace(
        query_fields={"title"},
        field_queries={"title": ["running"]},
        query_terms=["running"],
    )

    evidence, limitations = relevance_x_ray._build_analyzer_evidence(
        _AnalyzerClient(),
        "products",
        "target",
        metadata,
        {
            "title": {
                "type": "text",
                "search_analyzer": "keyword",
            }
        },
    )

    assert limitations == []
    assert evidence["title"]["index_tokens"] == ["run"]
    assert evidence["title"]["search_tokens"] == ["running"]
    assert analyze_requests == [
        {"field": "title", "text": "running"},
        {"analyzer": "keyword", "text": "running"},
    ]


def test_analyzer_evidence_does_not_hide_programming_errors():
    class _BrokenClient:
        def termvectors(self, **kwargs):
            raise RuntimeError("unexpected parser bug")

    metadata = SimpleNamespace(
        query_fields={"title"},
        field_queries={"title": ["running"]},
        query_terms=["running"],
    )

    with pytest.raises(RuntimeError, match="unexpected parser bug"):
        relevance_x_ray._build_analyzer_evidence(
            _BrokenClient(),
            "products",
            "target",
            metadata,
            {"title": {"type": "text", "search_analyzer": "keyword"}},
        )


def test_explain_runs_actual_search_and_reports_target_rank(monkeypatch, capsys):
    client = _ExplainClient()
    monkeypatch.setattr(relevance_x_ray, "_checked_client", lambda args: client)
    args = SimpleNamespace(
        index="products",
        query="wireless",
        doc_id="target",
        top_k=10,
        search_pipeline="",
        skip_knn_validation=False,
        raw=False,
    )

    relevance_x_ray.cmd_explain(args)

    output = capsys.readouterr().out
    assert "Observed target rank: 2" in output
    assert "Competing hit rank 1: doc 'competitor'" in output
    assert "Competing hit rank 2: doc 'target'" not in output
    assert "Evidence: Matched term 'wireless'" in output
    assert "No supported root cause was established" in output
    assert "scoring behaved as expected" not in output
    assert client.search_requests[0]["body"]["explain"] is True


def test_search_drops_unsafe_body_keys_and_injects_limits():
    client = _ExplainClient()
    relevance_x_ray._search(
        client,
        "products",
        {
            "query": {"match_all": {}},
            "aggs": {"all": {"terms": {"field": "brand", "size": 2_147_483_647}}},
            "sort": [{"_script": {"script": "Math.random()", "type": "number"}}],
            "profile": True,
            "track_total_hits": True,
        },
        top_k=10,
        explain=True,
    )
    request = client.search_requests[0]
    assert "aggs" not in request["body"]
    assert "sort" not in request["body"]
    assert "profile" not in request["body"]
    assert request["body"]["track_total_hits"] is False
    assert request["body"]["_source"] is False
    assert request["body"]["timeout"] == "10s"
    assert request["body"]["terminate_after"] == 10_000
    assert request["request_timeout"] == 15


def test_explain_reports_dropped_search_body_keys(monkeypatch, capsys):
    client = _ExplainClient()
    monkeypatch.setattr(relevance_x_ray, "_checked_client", lambda args: client)
    args = SimpleNamespace(
        index="products",
        query='{"query":{"match":{"title":"wireless"}},"sort":["_score"],"profile":true}',
        doc_id="target",
        top_k=10,
        search_pipeline="",
        skip_knn_validation=False,
        raw=False,
    )
    relevance_x_ray.cmd_explain(args)
    output = capsys.readouterr().out
    assert "Unsupported search-body keys were not executed: profile, sort" in output


def test_runtime_mapping_is_merged_before_scoring_field_rule(monkeypatch, capsys):
    client = _ExplainClient()
    monkeypatch.setattr(relevance_x_ray, "_checked_client", lambda args: client)
    args = SimpleNamespace(
        index="products",
        query=(
            '{"runtime_mappings":{"margin":{"type":"double"}},'
            '"query":{"script_score":{"query":{"match_all":{}},'
            '"script":{"source":"doc[\\u0027margin\\u0027].value"}}}}'
        ),
        doc_id="target",
        top_k=10,
        search_pipeline="",
        skip_knn_validation=False,
        raw=False,
    )
    relevance_x_ray.cmd_explain(args)
    assert "Field 'margin' is referenced in scoring but does not exist" not in (
        capsys.readouterr().out
    )


def test_raw_response_redaction_removes_document_content_recursively():
    redacted = relevance_x_ray._redact_raw_response({
        "hits": {
            "hits": [
                {
                    "_id": "1",
                    "_source": {"ssn": "111-22-3333"},
                    "inner_hits": {
                        "nested": {
                            "hits": {
                                "hits": [{"fields": {"secret": ["value"]}}]
                            }
                        }
                    },
                }
            ]
        }
    })
    assert "111-22-3333" not in str(redacted)
    assert "secret" not in str(redacted)


def test_raw_response_redaction_is_depth_bounded():
    response = {"value": "leaf"}
    for _ in range(100):
        response = {"nested": response}
    assert "<truncated>" in str(
        relevance_x_ray._redact_raw_response(response, max_depth=20)
    )


def test_index_wildcard_is_rejected_before_cluster_calls():
    class _NeverCalled:
        class indices:
            @staticmethod
            def get_mapping(index):
                pytest.fail("mapping request must not be sent")

    with pytest.raises(ValueError, match="Wildcard"):
        relevance_x_ray._index_context(_NeverCalled(), "prod-*")


def test_knn_sweep_does_not_hide_programming_errors(monkeypatch):
    client = _ExplainClient()
    monkeypatch.setattr(relevance_x_ray, "_checked_client", lambda args: client)
    monkeypatch.setattr(
        relevance_x_ray,
        "build_knn_parameter_sweep",
        lambda query: (_ for _ in ()).throw(RuntimeError("cluster internals")),
    )
    args = SimpleNamespace(
        index="products",
        query='{"knn":{"embedding":{"vector":[0.1,0.2],"k":5}}}',
        doc_id="target",
        top_k=10,
        search_pipeline="",
        skip_knn_validation=False,
        raw=False,
    )
    with pytest.raises(RuntimeError, match="cluster internals"):
        relevance_x_ray.cmd_explain(args)


def test_search_timeout_is_not_retried_without_explain(monkeypatch):
    class _TimeoutClient(_ExplainClient):
        def search(self, **kwargs):
            self.search_requests.append(kwargs)
            raise TimeoutError("timed out")

    client = _TimeoutClient()
    monkeypatch.setattr(relevance_x_ray, "_checked_client", lambda args: client)
    args = SimpleNamespace(
        index="products",
        query="wireless",
        doc_id="target",
        top_k=10,
        search_pipeline="",
        skip_knn_validation=False,
        raw=False,
    )
    with pytest.raises(TimeoutError):
        relevance_x_ray.cmd_explain(args)
    assert len(client.search_requests) == 1


def test_safe_error_does_not_include_cluster_response_body():
    error = NotFoundError(
        404,
        "index_not_found_exception",
        {"error": {"reason": "secret-index on node internal-node-7"}},
    )
    rendered = relevance_x_ray._safe_error(error)
    assert rendered == "NotFoundError (HTTP 404)"
    assert "secret-index" not in rendered


class _SynonymClient:
    def __init__(self):
        self.indices = _Indices()

    def search(self, index, body, **kwargs):
        if "function_score" in body["query"]:
            return {
                "hits": {
                    "hits": [
                        {"_id": str(doc_id)}
                        for doc_id in range(2, 7)
                    ]
                }
            }
        query_text = body["query"]["multi_match"]["query"]
        ids = ["2"] if query_text == "sneakers" else ["1", "2"]
        return {"hits": {"hits": [{"_id": doc_id} for doc_id in ids]}}

    def mtermvectors(self, index, body, **kwargs):
        terms_by_id = {
            "1": ["trainers", "running"],
            "2": ["sneakers", "trainers"],
            "3": ["sneakers", "trainers"],
            "4": ["sneakers", "casual"],
            "5": ["sneakers", "canvas"],
            "6": ["sneakers", "walking"],
        }
        return {
            "docs": [
                {
                    "_id": doc_id,
                    "term_vectors": {
                        "title": {
                            "terms": {
                                term: {} for term in terms_by_id[str(doc_id)]
                            }
                        }
                    },
                }
                for doc_id in body["ids"]
            ]
        }


def test_suggest_synonyms_only_recommends_rank_validated_candidate(
    monkeypatch, capsys
):
    client = _SynonymClient()
    monkeypatch.setattr(relevance_x_ray, "_checked_client", lambda args: client)
    args = SimpleNamespace(
        index="products",
        query_term="sneakers",
        doc_id="1",
        fields="title,description",
        sample_size=20,
        min_support=2,
        top_k=20,
    )

    relevance_x_ray.cmd_suggest_synonyms(args)

    output = capsys.readouterr().out
    assert "Rank-improving expansion candidates" in output
    assert "'trainers'" in output
    assert "rank=None->1" in output


class _TuningClient(_ExplainClient):
    def get(self, index, id):
        documents = {
            "target": {
                "title": "Wireless charging pad",
                "description": "Fast wireless charger",
            },
            "competitor": {
                "title": "Phone case",
                "description": "Popular accessory",
            },
        }
        return {"_source": documents[str(id)]}

    def search(self, **kwargs):
        self.search_requests.append(kwargs)
        function_score = kwargs["body"]["query"]["function_score"]
        factor = function_score["field_value_factor"]["factor"]
        boost_mode = function_score["boost_mode"]
        ids = (
            ["target", "competitor"]
            if boost_mode == "sum" and factor <= 0.1
            else ["competitor", "target"]
        )
        return {"hits": {"hits": [{"_id": doc_id} for doc_id in ids]}}


def test_tune_query_selects_only_rank_validated_candidate(
    monkeypatch, capsys, tmp_path
):
    client = _TuningClient()
    monkeypatch.setattr(relevance_x_ray, "_checked_client", lambda args: client)
    judgments = tmp_path / "judgments.json"
    judgments.write_text(
        '[{"type":"pairwise","preferred_doc_id":"target",'
        '"rejected_doc_id":"competitor","reason":"lexical intent"}]'
    )
    args = SimpleNamespace(
        index="products",
        query=(
            '{"query":{"function_score":{'
            '"query":{"multi_match":{"query":"wireless charger",'
            '"fields":["title","description"]}},'
            '"field_value_factor":{"field":"price","factor":1.0},'
            '"boost_mode":"replace"}}}'
        ),
        judgments_file=str(judgments),
        top_k=10,
    )

    relevance_x_ray.cmd_tune_query(args)

    result = __import__("json").loads(capsys.readouterr().out)
    assert result["selected"]["name"] == "temper-function-score-0.1"
    assert result["selected"]["improved_judgments"] == 1
    assert result["selected"]["regressed_judgments"] == 0
