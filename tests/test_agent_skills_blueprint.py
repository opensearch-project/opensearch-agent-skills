"""Tests for skills/opensearch-skills/scripts/lib/blueprint.py

No cluster required — cluster interaction is exercised through fakes.
"""

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = _REPO_ROOT / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.blueprint import (  # noqa: E402
    BlueprintApplyError,
    apply_bundle,
    extract_bundle,
    format_findings,
    has_errors,
    iter_fields,
    lint_bundle,
    load_bundle,
    preflight_apply,
    probe_analyzers,
    render_blueprint,
    validate_queries,
)

_EXAMPLE_BUNDLE = (
    _REPO_ROOT / "skills" / "opensearch-skills" / "search" / "opensearch-blueprint"
    / "example-bundle.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def codes(findings, level=None):
    return {f["code"] for f in findings if level is None or f["level"] == level}


def minimal_bundle(**overrides):
    bundle = {
        "index": "things_v1",
        "mappings": {"properties": {"title": {"type": "text"}}},
    }
    bundle.update(overrides)
    return bundle


class _FakeIndices:
    def __init__(self, *, exists=False, settings=None, mappings=None, analyze=None,
                 create_fails=False):
        self._exists = exists
        self._settings = settings or {}
        self._mappings = mappings or {}
        self._analyze = analyze or {"tokens": []}
        # When set, the first create() raises; later creates (rollback) succeed.
        self._create_fails = create_fails
        self.created = []
        self.deleted = []
        self.analyzed = []
        self.validated = []
        self.validate_response = {"valid": True, "explanations": []}

    def exists(self, index):
        return self._exists

    def delete(self, index):
        self.deleted.append(index)

    def create(self, index, body):
        if self._create_fails:
            self._create_fails = False
            raise RuntimeError("mapper_parsing_exception: bad mapping")
        self.created.append((index, body))

    def analyze(self, body, index=None):
        self.analyzed.append((body, index))
        return self._analyze

    def validate_query(self, index, body, explain=False):
        self.validated.append((index, body, explain))
        return self.validate_response

    def get_settings(self, index):
        return self._settings

    def get_mapping(self, index):
        return self._mappings


class _FakeIngest:
    def __init__(self, pipelines=None):
        self.put = []
        self.deleted = []
        self._pipelines = pipelines or {}

    def put_pipeline(self, id, body):  # noqa: A002 - matches opensearch-py signature
        self.put.append((id, body))

    def get_pipeline(self, id):  # noqa: A002
        return self._pipelines

    def delete_pipeline(self, id):  # noqa: A002
        self.deleted.append(id)


class _FakeTransport:
    def __init__(self, responses=None):
        self.requests = []
        self._responses = responses or {}

    def perform_request(self, method, path, body=None):
        self.requests.append((method, path, body))
        return self._responses.get(path, {})


class _FakeClient:
    def __init__(self, **kwargs):
        self.indices = _FakeIndices(**kwargs.pop("indices", {}))
        self.ingest = _FakeIngest(kwargs.pop("pipelines", None))
        self.transport = _FakeTransport(kwargs.pop("responses", None))
        # None models a count API that cannot be reached.
        self._count = kwargs.pop("doc_count", 0)

    def count(self, index):
        if self._count is None:
            raise RuntimeError("cluster_block_exception")
        return {"count": self._count}


# ---------------------------------------------------------------------------
# iter_fields
# ---------------------------------------------------------------------------

class TestIterFields:
    def test_walks_multi_fields_and_nested_objects(self):
        properties = {
            "title": {
                "type": "text",
                "fields": {"raw": {"type": "keyword"}},
            },
            "author": {
                "properties": {"name": {"type": "keyword"}},
            },
        }
        paths = dict(iter_fields(properties))
        assert "title" in paths
        assert "title.raw" in paths
        assert "author.name" in paths
        assert paths["title.raw"]["type"] == "keyword"

    def test_tolerates_non_dict_input(self):
        assert list(iter_fields(None)) == []
        assert list(iter_fields({"bad": "not-a-dict"})) == []


# ---------------------------------------------------------------------------
# Bundle-level lint
# ---------------------------------------------------------------------------

class TestBundleLint:
    def test_rejects_non_object_bundle(self):
        assert codes(lint_bundle(["not", "a", "bundle"])) == {"bundle.type"}

    def test_requires_index_name(self):
        bundle = minimal_bundle()
        del bundle["index"]
        assert "index.missing" in codes(lint_bundle(bundle))

    def test_requires_explicit_mappings(self):
        bundle = {"index": "things_v1", "mappings": {"properties": {}}}
        assert "mappings.empty" in codes(lint_bundle(bundle))

    def test_clean_minimal_bundle_has_no_errors(self):
        assert not has_errors(lint_bundle(minimal_bundle()))


# ---------------------------------------------------------------------------
# Analysis references
# ---------------------------------------------------------------------------

class TestAnalysisLint:
    def test_flags_dangling_analyzer(self):
        bundle = minimal_bundle(
            mappings={"properties": {"title": {"type": "text", "analyzer": "nope_en"}}}
        )
        assert "analysis.dangling_analyzer" in codes(lint_bundle(bundle))

    def test_accepts_builtin_analyzer(self):
        bundle = minimal_bundle(
            mappings={"properties": {"title": {"type": "text", "analyzer": "english"}}}
        )
        assert "analysis.dangling_analyzer" not in codes(lint_bundle(bundle))

    def test_accepts_custom_analyzer_defined_in_settings(self):
        bundle = minimal_bundle(
            settings={
                "index": {
                    "analysis": {
                        "analyzer": {"title_en": {"tokenizer": "standard", "filter": ["lowercase"]}}
                    }
                }
            },
            mappings={"properties": {"title": {"type": "text", "analyzer": "title_en"}}},
        )
        assert not has_errors(lint_bundle(bundle))

    def test_accepts_flat_analysis_settings_form(self):
        """settings.analysis and settings.index.analysis are both valid input."""
        bundle = minimal_bundle(
            settings={
                "analysis": {
                    "analyzer": {"title_en": {"tokenizer": "standard", "filter": ["lowercase"]}}
                }
            },
            mappings={"properties": {"title": {"type": "text", "analyzer": "title_en"}}},
        )
        assert not has_errors(lint_bundle(bundle))

    def test_flags_dangling_tokenizer_and_filter(self):
        bundle = minimal_bundle(
            settings={
                "index": {
                    "analysis": {
                        "analyzer": {
                            "title_en": {
                                "tokenizer": "made_up_tokenizer",
                                "filter": ["made_up_filter"],
                                "char_filter": ["made_up_char_filter"],
                            }
                        }
                    }
                }
            },
            mappings={"properties": {"title": {"type": "text", "analyzer": "title_en"}}},
        )
        found = codes(lint_bundle(bundle))
        assert "analysis.dangling_tokenizer" in found
        assert "analysis.dangling_filter" in found
        assert "analysis.dangling_char_filter" in found

    def test_flags_dangling_normalizer(self):
        bundle = minimal_bundle(
            mappings={"properties": {"genre": {"type": "keyword", "normalizer": "nope"}}}
        )
        assert "analysis.dangling_normalizer" in codes(lint_bundle(bundle))

    def test_flags_normalizer_on_text_field(self):
        bundle = minimal_bundle(
            settings={"index": {"analysis": {"normalizer": {"lc": {"filter": ["lowercase"]}}}}},
            mappings={"properties": {"title": {"type": "text", "normalizer": "lc"}}},
        )
        assert "analysis.normalizer_on_non_keyword" in codes(lint_bundle(bundle))

    def test_reports_one_normalizer_problem_per_field(self):
        """A dangling normalizer on a text field reports the type error only."""
        bundle = minimal_bundle(
            mappings={"properties": {"title": {"type": "text", "normalizer": "ghost"}}}
        )
        found = codes(lint_bundle(bundle))
        assert found == {"analysis.normalizer_on_non_keyword"}


# ---------------------------------------------------------------------------
# k-NN
# ---------------------------------------------------------------------------

class TestKnnLint:
    def _knn_bundle(self, field, index_settings=None):
        return minimal_bundle(
            settings={"index": index_settings if index_settings is not None else {"knn": True}},
            mappings={"properties": {"embedding": field}},
        )

    def test_flags_knn_without_plugin_enabled(self):
        bundle = self._knn_bundle({"type": "knn_vector", "dimension": 384}, index_settings={})
        assert "knn.plugin_disabled" in codes(lint_bundle(bundle))

    def test_accepts_string_true_for_knn_setting(self):
        bundle = self._knn_bundle(
            {"type": "knn_vector", "dimension": 384}, index_settings={"knn": "true"}
        )
        assert "knn.plugin_disabled" not in codes(lint_bundle(bundle))

    def test_flags_missing_dimension(self):
        bundle = self._knn_bundle({"type": "knn_vector"})
        assert "knn.missing_dimension" in codes(lint_bundle(bundle))

    def test_flags_non_positive_dimension(self):
        bundle = self._knn_bundle({"type": "knn_vector", "dimension": 0})
        assert "knn.invalid_dimension" in codes(lint_bundle(bundle))

    def test_flags_unknown_engine(self):
        bundle = self._knn_bundle({
            "type": "knn_vector", "dimension": 384,
            "method": {"name": "hnsw", "engine": "pinecone"},
        })
        assert "knn.unknown_engine" in codes(lint_bundle(bundle))

    def test_flags_space_type_unsupported_by_engine(self):
        bundle = self._knn_bundle({
            "type": "knn_vector", "dimension": 384,
            "method": {"name": "hnsw", "engine": "lucene", "space_type": "hamming"},
        })
        assert "knn.unsupported_space_type" in codes(lint_bundle(bundle))

    def test_accepts_space_type_supported_by_engine(self):
        bundle = self._knn_bundle({
            "type": "knn_vector", "dimension": 384,
            "method": {"name": "hnsw", "engine": "faiss", "space_type": "hamming"},
        })
        assert "knn.unsupported_space_type" not in codes(lint_bundle(bundle))

    def test_warns_when_ef_construction_below_m(self):
        bundle = self._knn_bundle({
            "type": "knn_vector", "dimension": 384,
            "method": {
                "name": "hnsw", "engine": "lucene", "space_type": "l2",
                "parameters": {"ef_construction": 8, "m": 16},
            },
        })
        findings = lint_bundle(bundle)
        assert "knn.ef_below_m" in codes(findings, level="warning")
        assert not has_errors(findings)


# ---------------------------------------------------------------------------
# Ingest pipeline
# ---------------------------------------------------------------------------

class TestIngestLint:
    def _bundle(self, processors, properties=None):
        return minimal_bundle(
            settings={"index": {"knn": True}},
            mappings={"properties": properties or {
                "title": {"type": "text"},
                "embedding": {"type": "knn_vector", "dimension": 384},
            }},
            ingest_pipeline={"name": "embed", "body": {"processors": processors}},
        )

    def test_flags_dimension_mismatch_against_known_model(self):
        bundle = self._bundle([{
            "text_embedding": {
                "model_id": "huggingface/sentence-transformers/all-mpnet-base-v2",
                "field_map": {"title": "embedding"},
            }
        }])
        assert "ingest.dimension_mismatch" in codes(lint_bundle(bundle))

    def test_accepts_matching_dimension(self):
        bundle = self._bundle([{
            "text_embedding": {
                "model_id": "huggingface/sentence-transformers/all-MiniLM-L6-v2",
                "field_map": {"title": "embedding"},
            }
        }])
        assert not has_errors(lint_bundle(bundle))

    def test_flags_unmapped_source_and_target(self):
        bundle = self._bundle([{
            "text_embedding": {"model_id": "x", "field_map": {"nope": "also_nope"}}
        }])
        found = codes(lint_bundle(bundle))
        assert "ingest.unmapped_source" in found
        assert "ingest.unmapped_target" in found

    def test_flags_sparse_encoding_into_knn_vector(self):
        bundle = self._bundle([{
            "sparse_encoding": {"model_id": "x", "field_map": {"title": "embedding"}}
        }])
        assert "ingest.wrong_target_type" in codes(lint_bundle(bundle))

    def test_sparse_encoding_into_rank_features_is_clean(self):
        bundle = self._bundle(
            [{"sparse_encoding": {"model_id": "x", "field_map": {"title": "tokens"}}}],
            properties={"title": {"type": "text"}, "tokens": {"type": "rank_features"}},
        )
        assert not has_errors(lint_bundle(bundle))

    def test_text_image_embedding_field_map_is_modality_keyed(self):
        """field_map is {modality: source} and the target lives in 'embedding'."""
        bundle = self._bundle(
            [{
                "text_image_embedding": {
                    "model_id": "x",
                    "embedding": "embedding",
                    "field_map": {"text": "title", "image": "poster"},
                }
            }],
            properties={
                "title": {"type": "text"},
                "poster": {"type": "binary"},
                "embedding": {"type": "knn_vector", "dimension": 384},
            },
        )
        assert not has_errors(lint_bundle(bundle))

    def test_text_image_embedding_flags_unmapped_source(self):
        bundle = self._bundle(
            [{
                "text_image_embedding": {
                    "model_id": "x",
                    "embedding": "embedding",
                    "field_map": {"text": "ghost_field"},
                }
            }],
            properties={"embedding": {"type": "knn_vector", "dimension": 384}},
        )
        assert "ingest.unmapped_source" in codes(lint_bundle(bundle))

    def test_text_image_embedding_requires_embedding_target(self):
        bundle = self._bundle([{
            "text_image_embedding": {"model_id": "x", "field_map": {"text": "title"}}
        }])
        assert "ingest.missing_embedding_target" in codes(lint_bundle(bundle))

    def test_flags_pipeline_without_name(self):
        bundle = minimal_bundle(
            ingest_pipeline={"body": {"processors": [{"set": {"field": "a", "value": 1}}]}}
        )
        assert "ingest.missing_name" in codes(lint_bundle(bundle))


# ---------------------------------------------------------------------------
# Hybrid search pipeline
# ---------------------------------------------------------------------------

class TestHybridLint:
    def _bundle(self, weights=None, subqueries=2, with_pipeline=True):
        queries = [{"match": {"title": {"query": "x"}}} for _ in range(subqueries)]
        bundle = minimal_bundle(
            queries=[{"name": "hybrid_q", "body": {"query": {"hybrid": {"queries": queries}}}}]
        )
        if with_pipeline:
            combination = {"technique": "arithmetic_mean"}
            if weights is not None:
                combination["parameters"] = {"weights": weights}
            bundle["search_pipeline"] = {
                "name": "hp",
                "body": {"phase_results_processors": [{
                    "normalization-processor": {
                        "normalization": {"technique": "min_max"},
                        "combination": combination,
                    }
                }]},
            }
        return bundle

    def test_flags_hybrid_without_normalization_processor(self):
        assert "hybrid.missing_normalization" in codes(
            lint_bundle(self._bundle(with_pipeline=False))
        )

    def test_warns_on_normalization_without_hybrid_query(self):
        bundle = minimal_bundle(search_pipeline={
            "name": "hp",
            "body": {"phase_results_processors": [{
                "normalization-processor": {"normalization": {"technique": "min_max"}}
            }]},
        })
        findings = lint_bundle(bundle)
        assert "hybrid.unused_normalization" in codes(findings, level="warning")
        assert not has_errors(findings)

    def test_flags_weights_that_do_not_sum_to_one(self):
        assert "hybrid.weights_sum" in codes(lint_bundle(self._bundle(weights=[0.3, 0.9])))

    def test_accepts_weights_summing_to_one(self):
        assert not has_errors(lint_bundle(self._bundle(weights=[0.3, 0.7])))

    def test_flags_weight_count_mismatch(self):
        found = codes(lint_bundle(self._bundle(weights=[0.5, 0.5], subqueries=3)))
        assert "hybrid.weight_count" in found

    def test_flags_non_numeric_weights(self):
        assert "hybrid.invalid_weights" in codes(lint_bundle(self._bundle(weights=["a", "b"])))

    def test_flags_unknown_techniques(self):
        bundle = self._bundle(weights=[0.5, 0.5])
        proc = bundle["search_pipeline"]["body"]["phase_results_processors"][0]
        proc["normalization-processor"]["normalization"]["technique"] = "softmax"
        proc["normalization-processor"]["combination"]["technique"] = "median"
        found = codes(lint_bundle(bundle))
        assert "hybrid.unknown_normalization" in found
        assert "hybrid.unknown_combination" in found


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

class TestQueryLint:
    def test_flags_unmapped_field(self):
        bundle = minimal_bundle(
            queries=[{"name": "q", "body": {"query": {"term": {"nope": "x"}}}}]
        )
        assert "query.unmapped_field" in codes(lint_bundle(bundle))

    def test_accepts_mapped_field(self):
        bundle = minimal_bundle(
            queries=[{"name": "q", "body": {"query": {"match": {"title": "x"}}}}]
        )
        assert not has_errors(lint_bundle(bundle))

    def test_multi_match_boost_syntax_is_stripped(self):
        bundle = minimal_bundle(
            mappings={"properties": {"title": {"type": "text"}, "plot": {"type": "text"}}},
            queries=[{"name": "q", "body": {
                "query": {"multi_match": {"query": "x", "fields": ["title^3", "plot"]}}
            }}],
        )
        assert not has_errors(lint_bundle(bundle))

    def test_field_valued_clauses_read_the_field_key(self):
        """rank_feature/exists name their field in a value, not a key."""
        bundle = minimal_bundle(
            mappings={"properties": {"popularity": {"type": "rank_feature"}}},
            queries=[{"name": "q", "body": {"query": {"bool": {"should": [
                {"rank_feature": {"field": "popularity"}},
                {"exists": {"field": "popularity"}},
            ]}}}}],
        )
        assert not has_errors(lint_bundle(bundle))

    def test_multi_field_subfield_resolves_via_base(self):
        bundle = minimal_bundle(
            mappings={"properties": {
                "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}}
            }},
            queries=[{"name": "q", "body": {"query": {"term": {"title.raw": "x"}}}}],
        )
        assert not has_errors(lint_bundle(bundle))

    def test_aggregations_are_not_read_as_query_fields(self):
        """A terms agg is {"terms": {"field": ..., "size": ...}} — parameters, not fields."""
        bundle = minimal_bundle(
            mappings={"properties": {"genres": {"type": "keyword"}}},
            queries=[{"name": "faceted", "body": {
                "query": {"match_all": {}},
                "aggs": {"by_genre": {"terms": {"field": "genres", "size": 10}}},
            }}],
        )
        assert not has_errors(lint_bundle(bundle))

    def test_terms_lookup_reads_the_field_key_not_lookup_params(self):
        """Terms lookup nests index/id/path under the field name."""
        bundle = minimal_bundle(
            mappings={"properties": {"color": {"type": "keyword"}}},
            queries=[{"name": "q", "body": {"query": {"terms": {
                "color": {"index": "palettes", "id": "2", "path": "colors"}
            }}}}],
        )
        assert not has_errors(lint_bundle(bundle))

    def test_flags_malformed_query_body(self):
        bundle = minimal_bundle(queries=[{"name": "q", "body": {"size": 10}}])
        assert "query.malformed" in codes(lint_bundle(bundle))


# ---------------------------------------------------------------------------
# Settings and ISM
# ---------------------------------------------------------------------------

class TestSettingsLint:
    def test_flags_zero_shards(self):
        bundle = minimal_bundle(settings={"index": {"number_of_shards": 0}})
        assert "settings.invalid_shards" in codes(lint_bundle(bundle))

    def test_warns_on_replicas_for_single_node(self):
        bundle = minimal_bundle(settings={"index": {"number_of_replicas": 1}})
        findings = lint_bundle(bundle)
        assert "settings.replicas_on_single_node" in codes(findings, level="warning")
        assert not has_errors(findings)


class TestIsmLint:
    def test_flags_unknown_default_state(self):
        bundle = minimal_bundle(ism_policy={"name": "p", "body": {"policy": {
            "default_state": "blazing",
            "states": [{"name": "hot", "actions": [], "transitions": []}],
        }}})
        assert "ism.unknown_default_state" in codes(lint_bundle(bundle))

    def test_flags_unknown_transition_target(self):
        bundle = minimal_bundle(ism_policy={"name": "p", "body": {"policy": {
            "default_state": "hot",
            "states": [{
                "name": "hot", "actions": [],
                "transitions": [{"state_name": "glacier"}],
            }],
        }}})
        assert "ism.unknown_transition" in codes(lint_bundle(bundle))

    def test_flags_policy_without_name(self):
        bundle = minimal_bundle(ism_policy={"body": {"policy": {"states": []}}})
        assert "ism.missing_name" in codes(lint_bundle(bundle))

    def test_no_findings_when_policy_absent(self):
        assert not lint_bundle(minimal_bundle())


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

class TestRenderBlueprint:
    def test_renders_sections_separated_by_em_dashes(self):
        rendered = render_blueprint(load_bundle(_EXAMPLE_BUNDLE))
        for section in ("INDEX", "ANALYSIS", "MAPPINGS", "INGEST PIPELINE",
                        "SEARCH PIPELINE", "ISM", "QUERIES"):
            assert section in rendered
        assert "—" in rendered

    def test_render_is_a_single_line(self):
        assert "\n" not in render_blueprint(load_bundle(_EXAMPLE_BUNDLE))

    def test_renders_knn_parameters(self):
        rendered = render_blueprint(load_bundle(_EXAMPLE_BUNDLE))
        assert "dim 384" in rendered
        assert "hnsw/lucene/l2" in rendered
        assert "ef_construction 256" in rendered

    def test_renders_hybrid_weights(self):
        assert "weights 0.3/0.7" in render_blueprint(load_bundle(_EXAMPLE_BUNDLE))

    def test_singularizes_shard_and_replica_counts(self):
        rendered = render_blueprint(minimal_bundle(
            settings={"index": {"number_of_shards": 1, "number_of_replicas": 2}}
        ))
        assert "1 shard," in rendered
        assert "2 replicas" in rendered

    def test_renders_booleans_lowercase(self):
        rendered = render_blueprint(minimal_bundle(settings={"index": {"knn": True}}))
        assert "knn true" in rendered

    def test_handles_empty_bundle(self):
        assert "UNNAMED" in render_blueprint({})


# ---------------------------------------------------------------------------
# The shipped example must stay valid
# ---------------------------------------------------------------------------

class TestExampleBundle:
    def test_example_bundle_lints_clean(self):
        findings = lint_bundle(load_bundle(_EXAMPLE_BUNDLE))
        assert findings == [], format_findings(findings)

    def test_example_bundle_is_valid_json(self):
        assert json.loads(_EXAMPLE_BUNDLE.read_text(encoding="utf-8"))["index"] == "movies_v1"


# ---------------------------------------------------------------------------
# Cluster interaction (faked)
# ---------------------------------------------------------------------------

class TestProbeAnalyzers:
    def test_probe_passes_when_tokens_match_expectation(self):
        client = _FakeClient(indices={
            "analyze": {"tokens": [{"token": "lord"}, {"token": "ring"}]}
        })
        bundle = minimal_bundle(
            settings={"index": {"analysis": {"analyzer": {"title_en": {}}}}},
            probes=[{"analyzer": "title_en", "text": "The Lord of the Rings",
                     "expect_tokens": ["lord", "ring"]}],
        )
        result = probe_analyzers(client, bundle)
        assert result[0]["ok"] is True
        assert result[0]["tokens"] == ["lord", "ring"]

    def test_probe_fails_when_tokens_differ(self):
        client = _FakeClient(indices={"analyze": {"tokens": [{"token": "lords"}]}})
        bundle = minimal_bundle(
            settings={"index": {"analysis": {"analyzer": {"title_en": {}}}}},
            probes=[{"analyzer": "title_en", "text": "Lords", "expect_tokens": ["lord"]}],
        )
        result = probe_analyzers(client, bundle)
        assert result[0]["ok"] is False
        assert result[0]["expected"] == ["lord"]

    def test_probe_without_expectation_reports_tokens_and_passes(self):
        client = _FakeClient(indices={"analyze": {"tokens": [{"token": "bl"}, {"token": "bla"}]}})
        bundle = minimal_bundle(probes=[{"analyzer": "standard", "text": "Blade"}])
        result = probe_analyzers(client, bundle)
        assert result[0]["ok"] is True
        assert result[0]["tokens"] == ["bl", "bla"]

    def test_custom_analyzer_is_probed_against_the_index(self):
        client = _FakeClient(indices={"analyze": {"tokens": []}})
        bundle = minimal_bundle(
            settings={"index": {"analysis": {"analyzer": {"title_en": {}}}}},
            probes=[{"analyzer": "title_en", "text": "x"}],
        )
        probe_analyzers(client, bundle)
        _, index = client.indices.analyzed[0]
        assert index == "things_v1"

    def test_analyze_error_is_captured_not_raised(self):
        class _Boom(_FakeIndices):
            def analyze(self, body, index=None):
                raise RuntimeError("no such analyzer")

        client = _FakeClient()
        client.indices = _Boom()
        bundle = minimal_bundle(probes=[{"analyzer": "ghost", "text": "x"}])
        result = probe_analyzers(client, bundle)
        assert result[0]["ok"] is False
        assert "no such analyzer" in result[0]["error"]


class TestValidateQueries:
    def test_reports_valid_queries(self):
        client = _FakeClient()
        bundle = minimal_bundle(
            queries=[{"name": "q", "body": {"query": {"match_all": {}}}}]
        )
        result = validate_queries(client, "things_v1", bundle)
        assert result == [{"name": "q", "valid": True, "explanations": []}]
        assert client.indices.validated[0][2] is True

    def test_captures_validation_errors(self):
        class _Boom(_FakeIndices):
            def validate_query(self, index, body, explain=False):
                raise RuntimeError("parse_exception")

        client = _FakeClient()
        client.indices = _Boom()
        bundle = minimal_bundle(queries=[{"name": "q", "body": {"query": {}}}])
        result = validate_queries(client, "things_v1", bundle)
        assert result[0]["valid"] is False
        assert "parse_exception" in result[0]["error"]


class TestApplyBundle:
    def test_creates_pipelines_index_and_policy(self):
        client = _FakeClient()
        bundle = load_bundle(_EXAMPLE_BUNDLE)
        applied = apply_bundle(client, bundle)

        assert applied["ingest_pipeline"] == "movies_embed"
        assert applied["search_pipeline"] == "movies_hybrid"
        assert applied["index"] == "movies_v1"
        assert applied["ism_policy"] == "movies_lifecycle"

        assert client.ingest.put[0][0] == "movies_embed"
        paths = [path for _, path, _ in client.transport.requests]
        assert "/_search/pipeline/movies_hybrid" in paths
        assert "/_plugins/_ism/policies/movies_lifecycle" in paths

        index, body = client.indices.created[0]
        assert index == "movies_v1"
        assert "settings" in body and "mappings" in body

    def test_replace_deletes_existing_index_first(self):
        client = _FakeClient(indices={"exists": True})
        applied = apply_bundle(client, minimal_bundle(), replace=True, confirm=True)
        assert applied["deleted_existing"] is True
        assert client.indices.deleted == ["things_v1"]


class TestApplySafetyGates:
    """Every refusal must happen before the first mutation."""

    def test_existing_index_without_replace_is_refused_not_silently_skipped(self):
        client = _FakeClient(indices={"exists": True})
        with pytest.raises(BlueprintApplyError) as excinfo:
            apply_bundle(client, minimal_bundle(), replace=False)
        assert excinfo.value.code == "index_exists"
        assert client.indices.deleted == []
        assert client.indices.created == []
        assert client.ingest.put == []

    def test_replace_without_confirmation_refuses_and_mutates_nothing(self):
        client = _FakeClient(indices={"exists": True})
        with pytest.raises(BlueprintApplyError) as excinfo:
            apply_bundle(client, minimal_bundle(), replace=True, confirm=False)
        assert excinfo.value.code == "confirmation_required"
        assert client.indices.deleted == []
        assert client.ingest.put == []

    def test_nonempty_index_is_refused_even_with_confirmation(self):
        client = _FakeClient(indices={"exists": True}, doc_count=4200)
        with pytest.raises(BlueprintApplyError) as excinfo:
            apply_bundle(client, minimal_bundle(), replace=True, confirm=True)
        assert excinfo.value.code == "index_not_empty"
        assert "4200" in str(excinfo.value)
        assert client.indices.deleted == []

    def test_nonempty_index_deletable_with_explicit_opt_in(self):
        client = _FakeClient(indices={"exists": True}, doc_count=4200)
        applied = apply_bundle(
            client, minimal_bundle(), replace=True, confirm=True, allow_nonempty=True
        )
        assert applied["deleted_existing"] is True

    def test_unknown_doc_count_fails_closed(self):
        """An unreachable count API must never be read as 'empty, safe to delete'."""
        client = _FakeClient(indices={"exists": True}, doc_count=None)
        with pytest.raises(BlueprintApplyError) as excinfo:
            apply_bundle(client, minimal_bundle(), replace=True, confirm=True)
        assert excinfo.value.code == "index_not_empty"
        assert client.indices.deleted == []


class TestPreflightApply:
    def test_reports_the_delete_without_performing_it(self):
        client = _FakeClient(indices={"exists": True}, doc_count=7)
        plan = preflight_apply(client, minimal_bundle(), replace=True)
        assert plan["will_delete"] is True
        assert plan["doc_count"] == 7
        assert {h["code"] for h in plan["hazards"]} == {"destructive.delete_index"}
        assert client.indices.deleted == []

    def test_flags_conflict_when_replace_not_requested(self):
        client = _FakeClient(indices={"exists": True})
        plan = preflight_apply(client, minimal_bundle(), replace=False)
        assert plan["will_delete"] is False
        assert {h["code"] for h in plan["hazards"]} == {"conflict.index_exists"}

    def test_clean_create_has_no_hazards(self):
        plan = preflight_apply(_FakeClient(), load_bundle(_EXAMPLE_BUNDLE))
        assert plan["hazards"] == []
        kinds = {c["kind"] for c in plan["creates"]}
        assert {"index", "ingest_pipeline", "search_pipeline", "ism_policy"} <= kinds

    def test_separates_overwrites_from_creates(self):
        client = _FakeClient(pipelines={"movies_embed": {"processors": []}})
        plan = preflight_apply(client, load_bundle(_EXAMPLE_BUNDLE))
        assert {o["name"] for o in plan["overwrites"]} == {"movies_embed"}
        assert "movies_embed" not in {c["name"] for c in plan["creates"]}


class TestApplyRollback:
    def test_failed_index_create_unwinds_the_pipelines_it_made(self):
        client = _FakeClient(indices={"create_fails": True})
        with pytest.raises(BlueprintApplyError) as excinfo:
            apply_bundle(client, load_bundle(_EXAMPLE_BUNDLE))

        assert excinfo.value.code == "apply_failed"
        # The ingest pipeline it created is deleted again, not left orphaned.
        assert client.ingest.deleted == ["movies_embed"]
        assert ("DELETE", "/_search/pipeline/movies_hybrid", None) in client.transport.requests
        assert excinfo.value.details["rollback_failed"] == []

    def test_preexisting_pipeline_is_restored_not_deleted(self):
        prior = {"description": "the original", "processors": []}
        client = _FakeClient(
            indices={"create_fails": True},
            pipelines={"movies_embed": prior},
        )
        with pytest.raises(BlueprintApplyError):
            apply_bundle(client, load_bundle(_EXAMPLE_BUNDLE))

        assert client.ingest.deleted == []
        assert client.ingest.put[-1] == ("movies_embed", prior)

    def test_replaced_index_shell_is_recreated_after_a_failure(self):
        client = _FakeClient(
            indices={
                "exists": True,
                "create_fails": True,
                "settings": {"things_v1": {"settings": {"index": {
                    "number_of_shards": "3", "uuid": "abc",
                }}}},
                "mappings": {"things_v1": {"mappings": {
                    "properties": {"title": {"type": "text"}}
                }}},
            },
        )
        with pytest.raises(BlueprintApplyError) as excinfo:
            apply_bundle(client, minimal_bundle(), replace=True, confirm=True)

        restored = dict(client.indices.created)["things_v1"]
        assert restored["settings"]["index"]["number_of_shards"] == "3"
        assert "uuid" not in restored["settings"]["index"]
        assert restored["mappings"]["properties"]["title"]["type"] == "text"
        # Data loss is reported plainly rather than implied by a restored shell.
        assert excinfo.value.details["irreversible"]

    def test_no_rollback_flag_leaves_partial_state_and_reraises_cause(self):
        client = _FakeClient(indices={"create_fails": True})
        with pytest.raises(RuntimeError) as excinfo:
            apply_bundle(client, load_bundle(_EXAMPLE_BUNDLE), rollback=False)
        assert not isinstance(excinfo.value, BlueprintApplyError)
        assert client.ingest.deleted == []


class TestExtractBundle:
    def _client(self):
        return _FakeClient(
            indices={
                "settings": {"movies_v1": {"settings": {"index": {
                    "number_of_shards": "1",
                    "uuid": "abc123",
                    "creation_date": "1700000000000",
                    "provided_name": "movies_v1",
                    "knn": "true",
                    "default_pipeline": "movies_embed",
                }}}},
                "mappings": {"movies_v1": {"mappings": {
                    "properties": {"title": {"type": "text"}}
                }}},
            },
            pipelines={"movies_embed": {"processors": []}},
        )

    def test_strips_cluster_assigned_metadata(self):
        bundle = extract_bundle(self._client(), "movies_v1")
        index_settings = bundle["settings"]["index"]
        for key in ("uuid", "creation_date", "provided_name"):
            assert key not in index_settings
        assert index_settings["number_of_shards"] == "1"

    def test_carries_mappings_and_index_name(self):
        bundle = extract_bundle(self._client(), "movies_v1")
        assert bundle["index"] == "movies_v1"
        assert bundle["mappings"]["properties"]["title"]["type"] == "text"

    def test_pulls_attached_ingest_pipeline(self):
        bundle = extract_bundle(self._client(), "movies_v1")
        assert bundle["ingest_pipeline"]["name"] == "movies_embed"

    def test_extracted_bundle_round_trips_through_render(self):
        rendered = render_blueprint(extract_bundle(self._client(), "movies_v1"))
        assert "movies_v1" in rendered
        assert "MAPPINGS" in rendered

    def test_resolves_settings_and_mappings_keys_independently(self):
        """An alias resolves to a concrete name; the two responses may differ in order."""
        client = _FakeClient(
            indices={
                "settings": {"movies_v1": {"settings": {"index": {"number_of_shards": "2"}}}},
                # Deliberately different insertion order and an extra sibling index.
                "mappings": {
                    "other_index": {"mappings": {"properties": {"wrong": {"type": "text"}}}},
                    "movies_v1": {"mappings": {"properties": {"title": {"type": "text"}}}},
                },
            },
        )
        bundle = extract_bundle(client, "movies_v1")
        assert bundle["mappings"]["properties"] == {"title": {"type": "text"}}
        assert bundle["settings"]["index"]["number_of_shards"] == "2"

    def test_falls_back_to_first_key_for_alias_lookups(self):
        client = _FakeClient(
            indices={
                "settings": {"movies_v1": {"settings": {"index": {}}}},
                "mappings": {"movies_v1": {"mappings": {"properties": {"a": {"type": "text"}}}}},
            },
        )
        bundle = extract_bundle(client, "movies-alias")
        assert bundle["mappings"]["properties"] == {"a": {"type": "text"}}

    def test_missing_pipeline_does_not_raise(self):
        class _Boom(_FakeIngest):
            def get_pipeline(self, id):  # noqa: A002
                raise RuntimeError("pipeline_missing")

        client = self._client()
        client.ingest = _Boom()
        bundle = extract_bundle(client, "movies_v1")
        assert "ingest_pipeline" not in bundle


# ---------------------------------------------------------------------------
# Reporting helpers
# ---------------------------------------------------------------------------

class TestFormatFindings:
    def test_clean_message_when_no_findings(self):
        assert "No findings" in format_findings([])

    def test_counts_errors_and_warnings(self):
        findings = lint_bundle(minimal_bundle(
            settings={"index": {"number_of_replicas": 1, "number_of_shards": 0}}
        ))
        report = format_findings(findings)
        assert "ERROR" in report
        assert "WARN" in report
        assert "1 error(s), 1 warning(s)." in report


@pytest.mark.parametrize("bundle", [{}, {"index": "x"}, {"mappings": {}}])
def test_lint_never_raises_on_partial_bundles(bundle):
    assert isinstance(lint_bundle(bundle), list)
