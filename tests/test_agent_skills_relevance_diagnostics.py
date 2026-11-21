"""Tests for deterministic relevance query inspection helpers."""

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "search"
    / "relevance-x-ray"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

from relevance_xray_lib.relevance_diagnostics import (
    build_knn_parameter_sweep,
    find_rank,
    flatten_mapping,
    inspect_query,
    parse_query_input,
)


def test_parse_query_input_accepts_complete_search_body_without_double_wrapping():
    body, plain = parse_query_input(
        '{"query": {"match": {"title": "wireless"}}, "sort": ["_score"]}',
        {"title": {"type": "text"}},
    )
    assert body["query"] == {"match": {"title": "wireless"}}
    assert body["sort"] == ["_score"]
    assert plain is None


def test_parse_query_input_plain_text_targets_only_text_fields():
    body, plain = parse_query_input(
        "wireless charger",
        {
            "title": {"type": "text"},
            "price": {"type": "float"},
            "embedding": {"type": "knn_vector"},
        },
    )
    assert body["query"]["multi_match"]["fields"] == ["title"]
    assert plain == "wireless charger"


def test_parse_query_input_rejects_json_beyond_parser_recursion_limit():
    query = '{"bool":{"must":[' * 2000 + '{"match_all":{}}' + ']}}' * 2000
    with pytest.raises(ValueError, match="nesting depth"):
        parse_query_input(query, {"title": {"type": "text"}})


def test_flatten_mapping_includes_nested_and_multifields():
    flattened = flatten_mapping({
        "product": {
            "properties": {
                "name": {
                    "type": "text",
                    "fields": {"keyword": {"type": "keyword"}},
                }
            }
        }
    })
    assert "product.name" in flattened
    assert flattened["product.name.keyword"]["type"] == "keyword"


def test_inspect_query_derives_fields_terms_and_scoring_references():
    metadata = inspect_query({
        "function_score": {
            "query": {"bool": {"filter": [{"term": {"brand": "acme"}}]}},
            "field_value_factor": {"field": "popularity"},
            "script_score": {"script": {"source": "doc['freshness'].value"}},
        }
    })
    assert metadata.exact_fields == {"brand"}
    assert metadata.referenced_fields == {"popularity", "freshness"}
    assert "acme" in metadata.query_terms


def test_inspect_query_does_not_treat_filtered_match_as_exact():
    metadata = inspect_query({
        "bool": {
            "must_not": [{"match": {"brand": "acme corp"}}],
            "filter": [{"match": {"description": "wireless charger"}}],
        }
    })
    assert metadata.exact_fields == set()


def test_inspect_query_ignores_scripts_in_filter_context():
    metadata = inspect_query({
        "bool": {
            "filter": [
                {"script": {"script": {"source": "doc['internal'].value > 1"}}}
            ]
        }
    })
    assert metadata.referenced_fields == set()


def test_knn_parameter_sweep_changes_only_explicit_recall_parameters():
    query = {
        "knn": {
            "embedding": {
                "vector": [0.1, 0.2],
                "k": 5,
                "method_parameters": {"ef_search": 20},
            }
        }
    }
    swept, before, after = build_knn_parameter_sweep(query)
    assert query["knn"]["embedding"]["k"] == 5
    assert swept["knn"]["embedding"]["k"] == 5
    assert swept["knn"]["embedding"]["method_parameters"]["ef_search"] == 100
    assert before == {"embedding.ef_search": 20}
    assert after == {"embedding.ef_search": 100}


def test_knn_parameter_sweep_abstains_without_explicit_ef_search():
    query = {"knn": {"embedding": {"vector": [0.1, 0.2], "k": 5}}}

    swept, before, after = build_knn_parameter_sweep(query)

    assert swept is None
    assert before == {}
    assert after == {}


def test_find_rank_normalizes_document_ids_to_strings():
    assert find_rank([{"_id": 1}, {"_id": "2"}], "2") == 2
    assert find_rank([{"_id": 1}], "missing") is None


def test_query_walkers_reject_excessive_depth_cleanly():
    query = {"match": {"title": "wireless"}}
    for _ in range(55):
        query = {"bool": {"must": [query]}}
    with pytest.raises(ValueError, match="nesting depth"):
        inspect_query(query)


def test_flatten_mapping_rejects_excessive_depth_cleanly():
    properties = {"leaf": {"type": "text"}}
    for depth in range(55):
        properties = {f"level_{depth}": {"properties": properties}}
    with pytest.raises(ValueError, match="nesting depth"):
        flatten_mapping(properties)
