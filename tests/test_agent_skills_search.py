"""Tests for skills/opensearch-skills/scripts/lib/search.py"""

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.search import (
    _value_shape,
    _text_richness_score,
    extract_index_field_specs,
    _resolve_text_query_fields,
    _resolve_field_spec_for_doc_key,
    _build_default_lexical_query,
    _build_default_lexical_body,
    _build_neural_clause,
    _suggestion_candidates_from_doc,
    _is_vector_value,
    _strip_vector_fields,
    preview_text,
    generate_suggestions,
    detect_index_profile,
    _resolve_autocomplete_fields,
    _source_field_variants,
    _extract_values_from_source_by_path,
    autocomplete,
    search_ui_search,
    _search_configs,
)


# ---------------------------------------------------------------------------
# Shared field specs
# ---------------------------------------------------------------------------
def _base_field_specs():
    return {
        "primaryTitle": {"type": "text", "normalizer": ""},
        "primaryTitle.keyword": {"type": "keyword", "normalizer": ""},
        "embedding_vector": {"type": "knn_vector", "normalizer": ""},
        "genres": {"type": "keyword", "normalizer": ""},
        "startYear": {"type": "integer", "normalizer": ""},
        "isAdult": {"type": "boolean", "normalizer": ""},
    }


class _FakeClient:
    def __init__(self, search_response=None):
        self.calls = []
        self._search_response = search_response or {
            "hits": {"hits": [], "total": {"value": 0}},
            "took": 1,
        }

    def search(self, index, body, size=10):
        self.calls.append({"index": index, "body": body})
        return self._search_response


# ---------------------------------------------------------------------------
# _value_shape
# ---------------------------------------------------------------------------
def test_value_shape_basic():
    shape = _value_shape("Hello World 123")

    assert shape["token_count"] == 3
    assert shape["looks_numeric"] is False
    assert shape["looks_date"] is False


def test_value_shape_numeric():
    shape = _value_shape("42.5")

    assert shape["looks_numeric"] is True


def test_value_shape_date():
    shape = _value_shape("2024-01-15")

    assert shape["looks_date"] is True


def test_value_shape_empty():
    shape = _value_shape("")

    assert shape["length"] == 0
    assert shape["alpha_ratio"] == 0.0


# ---------------------------------------------------------------------------
# _text_richness_score
# ---------------------------------------------------------------------------
def test_text_richness_score_rich_text():
    score = _text_richness_score("The quick brown fox jumps over the lazy dog")

    assert score > 50


def test_text_richness_score_short_text():
    score = _text_richness_score("X")

    assert score == 0.0


def test_text_richness_score_numeric_text():
    score = _text_richness_score("12345")

    # Numeric text has low alpha ratio so lower score
    assert score < 30


# ---------------------------------------------------------------------------
# extract_index_field_specs
# ---------------------------------------------------------------------------
def test_extract_index_field_specs_walks_properties():
    class _FakeIndices:
        def get_mapping(self, index):
            return {
                "my-index": {
                    "mappings": {
                        "properties": {
                            "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                            "year": {"type": "integer"},
                            "nested": {"properties": {"inner": {"type": "text"}}},
                        }
                    }
                }
            }

    class _Client:
        indices = _FakeIndices()

    specs = extract_index_field_specs(_Client(), "my-index")

    assert specs["title"]["type"] == "text"
    assert specs["title.keyword"]["type"] == "keyword"
    assert specs["year"]["type"] == "integer"
    assert specs["nested.inner"]["type"] == "text"


def test_extract_index_field_specs_handles_exception():
    class _FakeIndices:
        def get_mapping(self, index):
            raise Exception("connection failed")

    class _Client:
        indices = _FakeIndices()

    specs = extract_index_field_specs(_Client(), "missing-index")

    assert specs == {}


# ---------------------------------------------------------------------------
# _resolve_text_query_fields
# ---------------------------------------------------------------------------
def test_resolve_text_query_fields_prefers_text_type():
    specs = _base_field_specs()

    fields = _resolve_text_query_fields(specs)

    assert "primaryTitle" in fields
    assert "primaryTitle.keyword" not in fields


def test_resolve_text_query_fields_falls_back_to_keyword():
    specs = {"genre": {"type": "keyword", "normalizer": ""}}

    fields = _resolve_text_query_fields(specs)

    assert "genre" in fields


def test_resolve_text_query_fields_empty_specs():
    fields = _resolve_text_query_fields({})

    assert fields == ["*"]


# ---------------------------------------------------------------------------
# _resolve_field_spec_for_doc_key
# ---------------------------------------------------------------------------
def test_resolve_field_spec_exact_match():
    specs = _base_field_specs()
    name, spec = _resolve_field_spec_for_doc_key("genres", specs)

    assert name == "genres"
    assert spec["type"] == "keyword"


def test_resolve_field_spec_case_insensitive():
    specs = _base_field_specs()
    name, spec = _resolve_field_spec_for_doc_key("GENRES", specs)

    assert name == "genres"


def test_resolve_field_spec_leaf_match():
    specs = {"nested.field.name": {"type": "text", "normalizer": ""}}
    name, spec = _resolve_field_spec_for_doc_key("name", specs)

    assert name == "nested.field.name"


def test_resolve_field_spec_no_match():
    specs = _base_field_specs()
    name, spec = _resolve_field_spec_for_doc_key("nonexistent", specs)

    assert name == ""
    assert spec == {}


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------
def test_build_default_lexical_query():
    q = _build_default_lexical_query("hello world", ["title", "body"])

    assert q["multi_match"]["query"] == "hello world"
    assert q["multi_match"]["fields"] == ["title", "body"]
    assert q["multi_match"]["fuzziness"] == "AUTO"


def test_build_default_lexical_query_wildcard_no_fuzziness():
    q = _build_default_lexical_query("test", ["*"])

    assert "fuzziness" not in q["multi_match"]


def test_build_default_lexical_body():
    body = _build_default_lexical_body("test", 20, ["title"])

    assert body["size"] == 20
    assert "multi_match" in body["query"]


def test_build_neural_clause():
    clause = _build_neural_clause("search text", "vec_field", "model-1", 5)

    assert "neural" in clause
    neural = clause["neural"]["vec_field"]
    assert neural["query_text"] == "search text"
    assert neural["model_id"] == "model-1"
    assert neural["k"] == 10  # max(5, 10)


def test_build_neural_clause_large_size():
    clause = _build_neural_clause("text", "vec", "m", 50)

    assert clause["neural"]["vec"]["k"] == 50


# ---------------------------------------------------------------------------
# Preview & suggestions
# ---------------------------------------------------------------------------
def test_suggestion_candidates_from_doc():
    doc = {
        "id": 1,
        "title": "The Matrix is a great movie",
        "year": 1999,
        "embedding": [0.1, 0.2],
    }
    candidates = _suggestion_candidates_from_doc(doc)

    assert any("Matrix" in c for c in candidates)


def test_suggestion_candidates_skips_numeric_and_short():
    doc = {"id": "1", "x": "42.5", "date": "2024-01-01"}
    candidates = _suggestion_candidates_from_doc(doc)

    assert candidates == []


def test_preview_text_returns_best_candidate():
    source = {"title": "A great movie about adventure", "id": 1}

    text = preview_text(source)

    assert "great movie" in text


def test_preview_text_empty_source():
    assert preview_text({}) == "(No preview text)"


def test_preview_text_non_dict_values():
    source = {"data": None, "nested": {"a": 1}, "list": [1, 2]}

    assert preview_text(source) == "(No preview text)"


def test_generate_suggestions_returns_dicts_with_capability(monkeypatch):
    client = _FakeClient(search_response={
        "hits": {
            "hits": [
                {"_source": {"title": "The Matrix movie classic", "genre": "Action"}},
                {"_source": {"title": "Inception is mind bending", "genre": "Sci-Fi"}},
                {"_source": {"title": "The Godfather classic film", "genre": "Drama"}},
                {"_source": {"title": "Pulp Fiction great movie", "genre": "Crime"}},
                {"_source": {"title": "Forrest Gump heartwarming", "genre": "Drama"}},
                {"_source": {"title": "The Dark Knight rises", "genre": "Action"}},
            ],
            "total": {"value": 6},
        },
        "took": 1,
    })

    class _FakeIndices:
        def get_mapping(self, index):
            return {"movies": {"mappings": {"properties": {
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                "genre": {"type": "keyword"},
            }}}}
        def get_settings(self, index):
            return {"movies": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = generate_suggestions(client, "movies", max_count=6)

    suggestions = result["suggestions"]
    assert len(suggestions) > 0
    for s in suggestions:
        assert isinstance(s, dict)
        assert "text" in s
        assert "capability" in s
        assert s["capability"] in ("exact", "semantic", "structured", "combined", "autocomplete", "fuzzy")
        assert "query_mode" in s


def test_generate_suggestions_returns_deduped(monkeypatch):
    client = _FakeClient(search_response={
        "hits": {
            "hits": [
                {"_source": {"title": "The Matrix movie classic"}},
                {"_source": {"title": "the matrix movie classic"}},  # duplicate
                {"_source": {"title": "Inception is mind bending"}},
                {"_source": {"title": "The Godfather classic film"}},
                {"_source": {"title": "Pulp Fiction great movie"}},
                {"_source": {"title": "Forrest Gump heartwarming"}},
            ],
            "total": {"value": 6},
        },
        "took": 1,
    })

    class _FakeIndices:
        def get_mapping(self, index):
            return {"movies": {"mappings": {"properties": {
                "title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            }}}}
        def get_settings(self, index):
            return {"movies": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = generate_suggestions(client, "movies", max_count=6)

    texts_lowered = [s["text"].lower() for s in result["suggestions"]]
    assert len(texts_lowered) == len(set(texts_lowered))


def test_generate_suggestions_empty_index():
    client = _FakeClient()

    result = generate_suggestions(client, "", max_count=6)

    assert result["suggestions"] == []


# ---------------------------------------------------------------------------
# Autocomplete helpers
# ---------------------------------------------------------------------------
def test_resolve_autocomplete_fields_prefers_text():
    specs = {
        "title": {"type": "text", "normalizer": ""},
        "genre": {"type": "keyword", "normalizer": ""},
    }
    fields = _resolve_autocomplete_fields(specs)

    assert fields[0] == "title"


def test_resolve_autocomplete_fields_with_preferred():
    specs = {
        "title": {"type": "text", "normalizer": ""},
        "genre": {"type": "keyword", "normalizer": ""},
    }
    fields = _resolve_autocomplete_fields(specs, preferred_field="title")

    assert fields[0] == "title"


def test_source_field_variants_keyword_suffix():
    variants = _source_field_variants("title.keyword")

    assert variants == ["title", "title.keyword"]


def test_source_field_variants_plain():
    variants = _source_field_variants("title")

    assert variants == ["title"]


def test_source_field_variants_empty():
    assert _source_field_variants("") == []


def test_extract_values_from_source_simple():
    source = {"title": "Hello", "year": 2024}

    values = _extract_values_from_source_by_path(source, "title")

    assert values == ["Hello"]


def test_extract_values_from_source_nested():
    source = {"meta": {"author": {"name": "Alice"}}}

    values = _extract_values_from_source_by_path(source, "meta.author.name")

    assert values == ["Alice"]


def test_extract_values_from_source_list():
    source = {"tags": ["python", "java"]}

    values = _extract_values_from_source_by_path(source, "tags")

    assert "python" in values
    assert "java" in values


def test_extract_values_from_source_missing_path():
    values = _extract_values_from_source_by_path({"a": 1}, "b.c")

    assert values == []


# ---------------------------------------------------------------------------
# autocomplete
# ---------------------------------------------------------------------------
def test_autocomplete_empty_prefix():
    client = _FakeClient()

    result = autocomplete(client, "my-index", "")

    assert result["options"] == []
    assert result["error"] == ""


def test_autocomplete_empty_index():
    client = _FakeClient()

    result = autocomplete(client, "", "test")

    assert result["options"] == []


def test_autocomplete_returns_matching_options():
    client = _FakeClient(search_response={
        "hits": {
            "hits": [
                {"_source": {"genre": "Comedy"}},
                {"_source": {"genre": "Crime"}},
                {"_source": {"genre": "Action"}},
            ],
            "total": {"value": 3},
        },
        "took": 1,
    })

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {"genre": {"type": "keyword"}}}}}

    client.indices = _FakeIndices()

    result = autocomplete(client, "idx", "C", preferred_field="genre")

    assert "Comedy" in result["options"]
    assert "Crime" in result["options"]
    assert "Action" not in result["options"]  # doesn't start with "C"


# ---------------------------------------------------------------------------
# search_ui_search — integration
# ---------------------------------------------------------------------------
def test_search_ui_search_match_all_no_query(monkeypatch):
    client = _FakeClient()

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {"title": {"type": "text"}}}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = search_ui_search(client, "idx", "")

    assert result["error"] == ""
    assert result["query_mode"] == "match_all"


def test_search_ui_search_missing_index():
    client = _FakeClient()

    result = search_ui_search(client, "", "test query")

    assert result["error"] == "Missing index name."


def test_search_ui_search_bm25_default(monkeypatch):
    _search_configs.clear()
    client = _FakeClient()

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {"title": {"type": "text"}}}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = search_ui_search(client, "idx", "hello world")

    assert result["error"] == ""
    assert result["query_mode"] == "bm25"
    assert result["capability"] == "bm25"


def test_search_ui_search_structured_filter(monkeypatch):
    _search_configs.clear()
    client = _FakeClient()

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "startYear": {"type": "integer"},
                "genres": {"type": "keyword"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client.indices = _FakeIndices()

    result = search_ui_search(client, "idx", "startYear: 1999 and genres: Comedy")

    assert result["query_mode"] == "bm25"
    assert result["capability"] == "bm25"


def test_search_ui_search_dense_vector_no_search_pipeline(monkeypatch):
    _search_configs.clear()
    class _FakeIngest:
        def get_pipeline(self, id):
            return {id: {"processors": [
                {"text_embedding": {
                    "model_id": "model-1",
                    "field_map": {"title": "embedding"},
                }}
            ]}}

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "title": {"type": "text"},
                "embedding": {"type": "knn_vector"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {
                "default_pipeline": "my-ingest",
            }}}}

    client = _FakeClient()
    client.indices = _FakeIndices()
    client.ingest = _FakeIngest()

    result = search_ui_search(client, "idx", "semantic search test")

    assert result["query_mode"] == "dense_vector"
    assert result["capability"] == "dense_vector"


def test_search_ui_search_hybrid_with_search_pipeline(monkeypatch):
    _search_configs.clear()
    class _FakeTransport:
        def perform_request(self, method, url):
            return {"hybrid-pipeline": {
                "phase_results_processors": [
                    {"normalization-processor": {
                        "normalization": {"technique": "min_max"},
                        "combination": {"technique": "arithmetic_mean"},
                    }}
                ]
            }}

    class _FakeIngest:
        def get_pipeline(self, id):
            return {id: {"processors": [
                {"text_embedding": {
                    "model_id": "model-1",
                    "field_map": {"title": "embedding"},
                }}
            ]}}

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "title": {"type": "text"},
                "embedding": {"type": "knn_vector"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {
                "default_pipeline": "my-ingest",
                "search": {"default_pipeline": "hybrid-pipeline"},
            }}}}

    client = _FakeClient()
    client.indices = _FakeIndices()
    client.ingest = _FakeIngest()
    client.transport = _FakeTransport()

    result = search_ui_search(client, "idx", "hybrid search test")

    assert result["query_mode"] == "hybrid"
    assert result["capability"] == "hybrid"


# ---------------------------------------------------------------------------
# _is_vector_value / _strip_vector_fields
# ---------------------------------------------------------------------------
def test_is_vector_value_dense():
    vec = [0.1] * 128
    assert _is_vector_value(vec) is True


def test_is_vector_value_short_list():
    assert _is_vector_value([1, 2, 3]) is False


def test_is_vector_value_sparse():
    sparse = {str(i): 0.5 for i in range(32)}
    assert _is_vector_value(sparse) is True


def test_is_vector_value_small_dict():
    assert _is_vector_value({"a": 1, "b": 2}) is False


def test_is_vector_value_sparse_token_weights():
    """Neural sparse token-weight vectors with word keys should be detected."""
    sparse = {"movie": 0.33, "comedy": 0.12, "funny": 0.08, "film": 0.05}
    assert _is_vector_value(sparse) is True


def test_is_vector_value_small_sparse():
    """Sparse vectors with fewer than 16 but >= 4 entries should be detected."""
    sparse = {str(i): 0.5 for i in range(5)}
    assert _is_vector_value(sparse) is True


def test_is_vector_value_string():
    assert _is_vector_value("not a vector") is False


def test_is_vector_value_none():
    assert _is_vector_value(None) is False


def test_strip_vector_fields_removes_embeddings():
    source = {
        "title": "The Matrix",
        "year": 1999,
        "embedding": [0.1] * 128,
    }
    cleaned = _strip_vector_fields(source)

    assert "title" in cleaned
    assert "year" in cleaned
    assert "embedding" not in cleaned


def test_strip_vector_fields_removes_sparse_vectors():
    source = {
        "title": "Test",
        "sparse_vec": {str(i): 0.5 for i in range(32)},
    }
    cleaned = _strip_vector_fields(source)

    assert "title" in cleaned
    assert "sparse_vec" not in cleaned


def test_strip_vector_fields_keeps_all_when_no_vectors():
    source = {"title": "Test", "genre": "Action", "rating": 8.5}
    cleaned = _strip_vector_fields(source)

    assert cleaned == source


# ---------------------------------------------------------------------------
# detect_index_profile
# ---------------------------------------------------------------------------
def test_detect_index_profile_document_search():
    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "title": {"type": "text"},
                "body": {"type": "text"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client = _FakeClient()
    client.indices = _FakeIndices()

    profile = detect_index_profile(client, "idx")

    assert profile["suggested_template"] == "document"
    assert "lexical" in profile["capabilities"]
    assert profile["has_semantic"] is False
    assert profile["has_agentic"] is False
    assert "title" in profile["field_categories"]["text"]


def test_detect_index_profile_media_template_disabled():
    """Media template is disabled; falls back to document-search."""
    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "title": {"type": "text"},
                "poster": {"type": "text"},
                "genre": {"type": "keyword"},
                "rating": {"type": "float"},
                "year": {"type": "integer"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client = _FakeClient()
    client.indices = _FakeIndices()

    profile = detect_index_profile(client, "idx")

    # Media is disabled; falls back to document
    assert profile["suggested_template"] == "document"
    assert "structured" in profile["capabilities"]


def test_detect_index_profile_catalog_template():
    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "name": {"type": "text"},
                "category": {"type": "keyword"},
                "brand": {"type": "keyword"},
                "price": {"type": "float"},
                "stock": {"type": "integer"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client = _FakeClient()
    client.indices = _FakeIndices()

    profile = detect_index_profile(client, "idx")

    assert profile["suggested_template"] == "ecommerce"


def test_detect_index_profile_hides_vector_fields():
    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "title": {"type": "text"},
                "embedding_vector": {"type": "knn_vector"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {}}}}

    client = _FakeClient()
    client.indices = _FakeIndices()

    profile = detect_index_profile(client, "idx")

    assert "embedding_vector" not in profile["fields"]
    assert "embedding_vector" in profile["field_categories"]["vector"]


def test_detect_index_profile_semantic_capability():
    class _FakeIngest:
        def get_pipeline(self, id):
            return {id: {"processors": [
                {"text_embedding": {
                    "model_id": "model-1",
                    "field_map": {"title": "embedding"},
                }}
            ]}}

    class _FakeIndices:
        def get_mapping(self, index):
            return {"idx": {"mappings": {"properties": {
                "title": {"type": "text"},
                "embedding": {"type": "knn_vector"},
            }}}}
        def get_settings(self, index):
            return {"idx": {"settings": {"index": {
                "default_pipeline": "my-ingest",
            }}}}

    client = _FakeClient()
    client.indices = _FakeIndices()
    client.ingest = _FakeIngest()

    profile = detect_index_profile(client, "idx")

    assert profile["has_semantic"] is True
    assert "semantic" in profile["capabilities"]
