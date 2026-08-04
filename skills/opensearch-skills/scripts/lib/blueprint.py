"""Blueprint compile / lint / apply / extract for OpenSearch index designs.

A *blueprint bundle* is a single JSON document describing a complete OpenSearch
index design — settings, analysis chain, mappings, ingest pipeline, search
pipeline, ISM policy, and named queries. This module:

  - ``lint_bundle``      static correctness checks (no cluster required)
  - ``render_blueprint`` bundle -> dense single-block human/agent-readable spec
  - ``probe_analyzers``  verify analyzers via the ``_analyze`` API
  - ``validate_queries`` verify query DSL via the ``_validate/query`` API
  - ``apply_bundle``     create pipelines, index, and ISM policy on a cluster
  - ``extract_bundle``   read an existing index back into a bundle

The lint rules encode OpenSearch-specific failure modes that are easy to get
wrong by hand and expensive to discover after data is loaded (hybrid weight
sums, knn dimension/plugin mismatches, dangling analyzer references).
"""

import json

# ---------------------------------------------------------------------------
# Built-in analysis component names (non-exhaustive but covers common usage).
# A reference to anything outside these sets must be defined in
# settings.analysis or it is a dangling reference.
# ---------------------------------------------------------------------------

_LANGUAGE_ANALYZERS = {
    "arabic", "armenian", "basque", "bengali", "brazilian", "bulgarian",
    "catalan", "cjk", "czech", "danish", "dutch", "english", "estonian",
    "finnish", "french", "galician", "german", "greek", "hindi", "hungarian",
    "indonesian", "irish", "italian", "latvian", "lithuanian", "norwegian",
    "persian", "portuguese", "romanian", "russian", "sorani", "spanish",
    "swedish", "turkish", "thai",
}

BUILTIN_ANALYZERS = {
    "standard", "simple", "whitespace", "stop", "keyword", "pattern",
    "fingerprint", "default", "default_search",
} | _LANGUAGE_ANALYZERS

BUILTIN_TOKENIZERS = {
    "standard", "letter", "lowercase", "whitespace", "uax_url_email",
    "classic", "thai", "ngram", "edge_ngram", "keyword", "pattern",
    "simple_pattern", "simple_pattern_split", "char_group", "path_hierarchy",
}

BUILTIN_TOKEN_FILTERS = {
    "apostrophe", "asciifolding", "cjk_bigram", "cjk_width", "classic",
    "common_grams", "condition", "decimal_digit", "delimited_payload",
    "dictionary_decompounder", "edge_ngram", "elision", "fingerprint",
    "flatten_graph", "hunspell", "hyphenation_decompounder", "keep",
    "keep_types", "keyword_marker", "keyword_repeat", "kstem", "length",
    "limit", "lowercase", "min_hash", "multiplexer", "ngram",
    "pattern_capture", "pattern_replace", "phonetic", "porter_stem",
    "predicate_token_filter", "remove_duplicates", "reverse", "shingle",
    "snowball", "stemmer", "stemmer_override", "stop", "synonym",
    "synonym_graph", "trim", "truncate", "unique", "uppercase",
    "word_delimiter", "word_delimiter_graph",
}

BUILTIN_CHAR_FILTERS = {"html_strip", "mapping", "pattern_replace"}

# k-NN engines and the space types each one actually supports.
KNN_ENGINE_SPACES = {
    "lucene": {"l2", "cosinesimil", "innerproduct"},
    "faiss": {"l2", "innerproduct", "cosinesimil", "hamming"},
    "nmslib": {"l2", "cosinesimil", "innerproduct", "l1", "linf"},
}

# Vector dimensions for embedding models bundled with the launchpad skill.
KNOWN_MODEL_DIMENSIONS = {
    "huggingface/sentence-transformers/all-MiniLM-L6-v2": 384,
    "huggingface/sentence-transformers/all-MiniLM-L12-v2": 384,
    "huggingface/sentence-transformers/all-mpnet-base-v2": 768,
    "huggingface/sentence-transformers/all-distilroberta-v1": 768,
    "huggingface/sentence-transformers/multi-qa-MiniLM-L6-cos-v1": 384,
    "huggingface/sentence-transformers/multi-qa-mpnet-base-dot-v1": 768,
    "huggingface/sentence-transformers/paraphrase-MiniLM-L3-v2": 384,
    "huggingface/sentence-transformers/msmarco-distilbert-base-tas-b": 768,
    "amazon.titan-embed-text-v1": 1536,
    "amazon.titan-embed-text-v2:0": 1024,
    "cohere.embed-english-v3": 1024,
    "cohere.embed-multilingual-v3": 1024,
}

_HYBRID_COMBINATION_TECHNIQUES = {
    "arithmetic_mean", "geometric_mean", "harmonic_mean",
}
_HYBRID_NORMALIZATION_TECHNIQUES = {"min_max", "l2", "z_score"}

# Weights that sum to within this tolerance of 1.0 are accepted.
_WEIGHT_TOLERANCE = 1e-6


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

def _finding(level, code, message, path=""):
    return {"level": level, "code": code, "message": message, "path": path}


def _error(code, message, path=""):
    return _finding("error", code, message, path)


def _warning(code, message, path=""):
    return _finding("warning", code, message, path)


# ---------------------------------------------------------------------------
# Mapping traversal
# ---------------------------------------------------------------------------

def iter_fields(properties, prefix=""):
    """Yield ``(dotted_path, field_definition)`` for every mapped field.

    Recurses into ``properties`` (object/nested) and ``fields`` (multi-fields),
    so ``title.raw`` and ``author.name`` are both visited.
    """
    if not isinstance(properties, dict):
        return
    for name, defn in properties.items():
        if not isinstance(defn, dict):
            continue
        path = f"{prefix}{name}"
        yield path, defn
        if isinstance(defn.get("properties"), dict):
            yield from iter_fields(defn["properties"], prefix=f"{path}.")
        if isinstance(defn.get("fields"), dict):
            yield from iter_fields(defn["fields"], prefix=f"{path}.")


def _analysis(bundle):
    settings = bundle.get("settings") or {}
    index = settings.get("index")
    # Accept both {"index": {"analysis": ...}} and {"analysis": ...} forms.
    if isinstance(index, dict) and "analysis" in index:
        return index.get("analysis") or {}
    return settings.get("analysis") or {}


def _index_settings(bundle):
    """Return index-level settings, tolerating both nesting conventions."""
    settings = bundle.get("settings") or {}
    index = settings.get("index")
    merged = {k: v for k, v in settings.items() if k not in ("index", "analysis")}
    if isinstance(index, dict):
        merged.update({k: v for k, v in index.items() if k != "analysis"})
    return merged


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------

def lint_bundle(bundle):
    """Return a list of findings for a blueprint bundle. No cluster needed."""
    findings = []

    if not isinstance(bundle, dict):
        return [_error("bundle.type", "Blueprint bundle must be a JSON object.")]

    if not str(bundle.get("index", "")).strip():
        findings.append(_error("index.missing", "Bundle must declare an 'index' name.", "index"))

    mappings = bundle.get("mappings") or {}
    properties = mappings.get("properties") or {}
    if not properties:
        findings.append(_error(
            "mappings.empty",
            "Bundle declares no mapped fields; dynamic mapping is not a design.",
            "mappings.properties",
        ))

    fields = dict(iter_fields(properties))

    findings.extend(_lint_analysis_refs(bundle, fields))
    findings.extend(_lint_knn(bundle, fields))
    findings.extend(_lint_ingest_pipeline(bundle, fields))
    findings.extend(_lint_search_pipeline(bundle))
    findings.extend(_lint_queries(bundle, fields))
    findings.extend(_lint_index_settings(bundle))
    findings.extend(_lint_ism(bundle))

    return findings


def _lint_analysis_refs(bundle, fields):
    """Every analyzer/normalizer a field references must exist."""
    findings = []
    analysis = _analysis(bundle)
    custom_analyzers = set((analysis.get("analyzer") or {}).keys())
    custom_normalizers = set((analysis.get("normalizer") or {}).keys())
    custom_tokenizers = set((analysis.get("tokenizer") or {}).keys())
    custom_filters = set((analysis.get("filter") or {}).keys())
    custom_char_filters = set((analysis.get("char_filter") or {}).keys())

    for path, defn in fields.items():
        for key in ("analyzer", "search_analyzer", "search_quote_analyzer"):
            ref = defn.get(key)
            if ref and ref not in custom_analyzers and ref not in BUILTIN_ANALYZERS:
                findings.append(_error(
                    "analysis.dangling_analyzer",
                    f"Field '{path}' references analyzer '{ref}', "
                    f"which is neither built-in nor defined in settings.analysis.analyzer.",
                    f"mappings.properties.{path}.{key}",
                ))
        ref = defn.get("normalizer")
        if not ref:
            continue
        # Report one problem per field: a normalizer on a non-keyword field is
        # wrong regardless of whether the normalizer resolves, so that check
        # takes precedence over the dangling-reference check.
        if defn.get("type") != "keyword":
            findings.append(_error(
                "analysis.normalizer_on_non_keyword",
                f"Field '{path}' is type '{defn.get('type')}'; "
                f"normalizers apply only to keyword fields.",
                f"mappings.properties.{path}",
            ))
        elif ref not in custom_normalizers:
            findings.append(_error(
                "analysis.dangling_normalizer",
                f"Field '{path}' references normalizer '{ref}', "
                f"which is not defined in settings.analysis.normalizer.",
                f"mappings.properties.{path}.normalizer",
            ))

    # Custom analyzer internals must also resolve.
    for name, defn in (analysis.get("analyzer") or {}).items():
        if not isinstance(defn, dict):
            continue
        tok = defn.get("tokenizer")
        if tok and tok not in custom_tokenizers and tok not in BUILTIN_TOKENIZERS:
            findings.append(_error(
                "analysis.dangling_tokenizer",
                f"Analyzer '{name}' references tokenizer '{tok}', "
                f"which is neither built-in nor defined in settings.analysis.tokenizer.",
                f"settings.analysis.analyzer.{name}.tokenizer",
            ))
        for filt in defn.get("filter") or []:
            if filt not in custom_filters and filt not in BUILTIN_TOKEN_FILTERS:
                findings.append(_error(
                    "analysis.dangling_filter",
                    f"Analyzer '{name}' references token filter '{filt}', "
                    f"which is neither built-in nor defined in settings.analysis.filter.",
                    f"settings.analysis.analyzer.{name}.filter",
                ))
        for cf in defn.get("char_filter") or []:
            if cf not in custom_char_filters and cf not in BUILTIN_CHAR_FILTERS:
                findings.append(_error(
                    "analysis.dangling_char_filter",
                    f"Analyzer '{name}' references char filter '{cf}', which is "
                    f"neither built-in nor defined in settings.analysis.char_filter.",
                    f"settings.analysis.analyzer.{name}.char_filter",
                ))

    return findings


def _lint_knn(bundle, fields):
    """k-NN fields need the plugin enabled, a dimension, and a valid engine."""
    findings = []
    knn_fields = {p: d for p, d in fields.items() if d.get("type") == "knn_vector"}
    if not knn_fields:
        return findings

    index_settings = _index_settings(bundle)
    if not _as_bool(index_settings.get("knn")):
        findings.append(_error(
            "knn.plugin_disabled",
            f"Index maps {len(knn_fields)} knn_vector field(s) but "
            f"settings.index.knn is not true; the index will reject them.",
            "settings.index.knn",
        ))

    for path, defn in knn_fields.items():
        dim = _as_int(defn.get("dimension"))
        if dim is None:
            findings.append(_error(
                "knn.missing_dimension",
                f"knn_vector field '{path}' has no 'dimension'.",
                f"mappings.properties.{path}.dimension",
            ))
        elif dim <= 0:
            findings.append(_error(
                "knn.invalid_dimension",
                f"knn_vector field '{path}' has non-positive dimension {dim}.",
                f"mappings.properties.{path}.dimension",
            ))

        method = defn.get("method") or {}
        if not isinstance(method, dict) or not method:
            continue
        engine = method.get("engine", "nmslib")
        space = method.get("space_type")
        supported = KNN_ENGINE_SPACES.get(engine)
        if supported is None:
            findings.append(_error(
                "knn.unknown_engine",
                f"knn_vector field '{path}' uses unknown engine '{engine}'. "
                f"Expected one of: {', '.join(sorted(KNN_ENGINE_SPACES))}.",
                f"mappings.properties.{path}.method.engine",
            ))
        elif space and space not in supported:
            findings.append(_error(
                "knn.unsupported_space_type",
                f"knn_vector field '{path}' uses space_type '{space}', which "
                f"engine '{engine}' does not support "
                f"({', '.join(sorted(supported))}).",
                f"mappings.properties.{path}.method.space_type",
            ))

        params = method.get("parameters") or {}
        ef = _as_int(params.get("ef_construction"))
        m = _as_int(params.get("m"))
        if ef is not None and m is not None and ef < m:
            findings.append(_warning(
                "knn.ef_below_m",
                f"knn_vector field '{path}' has ef_construction={ef} below m={m}; "
                f"recall will suffer. Typical: ef_construction 128-512, m 16-48.",
                f"mappings.properties.{path}.method.parameters",
            ))

    return findings


# Expected mapping type for each embedding processor's target field.
_EMBEDDING_TARGET_TYPES = {
    "text_embedding": "knn_vector",
    "text_image_embedding": "knn_vector",
    "sparse_encoding": "rank_features",
}


def _embedding_pairs(kind, cfg):
    """Yield ``(source_field, target_field)`` pairs for an embedding processor.

    ``text_embedding`` and ``sparse_encoding`` use ``field_map`` as
    ``{source: target}``. ``text_image_embedding`` inverts this: ``field_map`` is
    ``{modality: source}`` (e.g. ``{"text": "name", "image": "image_binary"}``)
    and the single vector target lives in ``embedding``.
    """
    field_map = cfg.get("field_map") or {}
    if not isinstance(field_map, dict):
        return
    if kind == "text_image_embedding":
        target = cfg.get("embedding")
        for source in field_map.values():
            if isinstance(source, str):
                yield source, target
        return
    for source, target in field_map.items():
        yield source, target


def _lint_ingest_pipeline(bundle, fields):
    """Embedding processors must target real knn_vector fields of the right size."""
    findings = []
    pipeline = bundle.get("ingest_pipeline") or {}
    body = pipeline.get("body") or {}
    processors = body.get("processors") or []

    for idx, processor in enumerate(processors):
        if not isinstance(processor, dict):
            continue
        for kind, expected_type in _EMBEDDING_TARGET_TYPES.items():
            cfg = processor.get(kind)
            if not isinstance(cfg, dict):
                continue
            if kind == "text_image_embedding" and not cfg.get("embedding"):
                findings.append(_error(
                    "ingest.missing_embedding_target",
                    "text_image_embedding processor has no 'embedding' field naming "
                    "the target knn_vector.",
                    f"ingest_pipeline.processors[{idx}].embedding",
                ))
                continue
            for source, target in _embedding_pairs(kind, cfg):
                if source not in fields:
                    findings.append(_error(
                        "ingest.unmapped_source",
                        f"{kind} processor reads '{source}', which is not a mapped field.",
                        f"ingest_pipeline.processors[{idx}].field_map",
                    ))
                target_def = fields.get(target)
                if target_def is None:
                    findings.append(_error(
                        "ingest.unmapped_target",
                        f"{kind} processor writes '{target}', which is not a mapped field.",
                        f"ingest_pipeline.processors[{idx}].field_map",
                    ))
                    continue
                if target_def.get("type") != expected_type:
                    findings.append(_error(
                        "ingest.wrong_target_type",
                        f"{kind} processor writes '{target}', which is type "
                        f"'{target_def.get('type')}'; expected '{expected_type}'.",
                        f"mappings.properties.{target}.type",
                    ))
                    continue
                if expected_type != "knn_vector":
                    continue
                model_id = cfg.get("model_id", "")
                expected_dim = KNOWN_MODEL_DIMENSIONS.get(model_id)
                actual_dim = _as_int(target_def.get("dimension"))
                if expected_dim and actual_dim and expected_dim != actual_dim:
                    findings.append(_error(
                        "ingest.dimension_mismatch",
                        f"Model '{model_id}' emits {expected_dim}-dim vectors but "
                        f"'{target}' is mapped with dimension {actual_dim}.",
                        f"mappings.properties.{target}.dimension",
                    ))

    if processors and not str(pipeline.get("name", "")).strip():
        findings.append(_error(
            "ingest.missing_name",
            "Ingest pipeline defines processors but has no 'name'.",
            "ingest_pipeline.name",
        ))

    return findings


def _iter_hybrid_queries(bundle):
    """Yield ``(query_name, hybrid_clause)`` for every hybrid query in the bundle."""
    for query in bundle.get("queries") or []:
        if not isinstance(query, dict):
            continue
        clause = ((query.get("body") or {}).get("query") or {}).get("hybrid")
        if isinstance(clause, dict):
            yield query.get("name", "<unnamed>"), clause


def _normalization_processors(bundle):
    body = (bundle.get("search_pipeline") or {}).get("body") or {}
    for processor in body.get("phase_results_processors") or []:
        if isinstance(processor, dict) and isinstance(
            processor.get("normalization-processor"), dict
        ):
            yield processor["normalization-processor"]


def _lint_search_pipeline(bundle):
    """Hybrid search has strict, easily-violated normalization constraints."""
    findings = []
    procs = list(_normalization_processors(bundle))
    hybrids = list(_iter_hybrid_queries(bundle))

    if hybrids and not procs:
        findings.append(_error(
            "hybrid.missing_normalization",
            f"Query '{hybrids[0][0]}' uses a hybrid clause, but no search pipeline "
            f"defines a normalization-processor. Hybrid queries require one.",
            "search_pipeline.phase_results_processors",
        ))
    if procs and not hybrids:
        findings.append(_warning(
            "hybrid.unused_normalization",
            "Search pipeline defines a normalization-processor but no bundled "
            "query uses a hybrid clause.",
            "search_pipeline",
        ))

    subquery_counts = {len(h.get("queries") or []) for _, h in hybrids}

    for proc in procs:
        technique = (proc.get("normalization") or {}).get("technique")
        if technique and technique not in _HYBRID_NORMALIZATION_TECHNIQUES:
            findings.append(_error(
                "hybrid.unknown_normalization",
                f"Unknown normalization technique '{technique}'. Expected one of: "
                f"{', '.join(sorted(_HYBRID_NORMALIZATION_TECHNIQUES))}.",
                "search_pipeline.normalization.technique",
            ))

        combination = proc.get("combination") or {}
        ctechnique = combination.get("technique")
        if ctechnique and ctechnique not in _HYBRID_COMBINATION_TECHNIQUES:
            findings.append(_error(
                "hybrid.unknown_combination",
                f"Unknown combination technique '{ctechnique}'. Expected one of: "
                f"{', '.join(sorted(_HYBRID_COMBINATION_TECHNIQUES))}.",
                "search_pipeline.combination.technique",
            ))

        weights = (combination.get("parameters") or {}).get("weights")
        if weights is None:
            continue
        if not isinstance(weights, list) or not all(
            isinstance(w, (int, float)) and not isinstance(w, bool) for w in weights
        ):
            findings.append(_error(
                "hybrid.invalid_weights",
                "Combination weights must be a list of numbers.",
                "search_pipeline.combination.parameters.weights",
            ))
            continue

        total = sum(weights)
        if abs(total - 1.0) > _WEIGHT_TOLERANCE:
            findings.append(_error(
                "hybrid.weights_sum",
                f"Combination weights {weights} sum to {total:g}; OpenSearch "
                f"requires them to sum to 1.0.",
                "search_pipeline.combination.parameters.weights",
            ))

        for count in subquery_counts:
            if count != len(weights):
                findings.append(_error(
                    "hybrid.weight_count",
                    f"Combination declares {len(weights)} weight(s) but a hybrid "
                    f"query has {count} sub-quer(ies); the counts must match.",
                    "search_pipeline.combination.parameters.weights",
                ))

    return findings


# Clauses shaped {clause: {<field>: {...}}} — the field is the key.
_FIELD_KEYED_CLAUSES = frozenset({
    "term", "terms", "match", "match_phrase", "match_phrase_prefix", "range",
    "prefix", "wildcard", "regexp", "fuzzy", "knn", "neural", "neural_sparse",
})

# Clauses shaped {clause: {"field": "<field>", ...}} — the field is a value.
_FIELD_VALUED_CLAUSES = frozenset({"exists", "rank_feature", "distance_feature"})

# Clauses shaped {clause: {"fields": ["a^3", "b"], ...}}.
_FIELD_LIST_CLAUSES = frozenset({"multi_match", "query_string", "simple_query_string"})

_NON_FIELD_KEYS = frozenset({"boost", "_name"})


def _collect_query_fields(node, found):
    """Walk a query body collecting field names referenced by leaf clauses."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _FIELD_VALUED_CLAUSES and isinstance(value, dict):
                if isinstance(value.get("field"), str):
                    found.add(value["field"])
            elif key in _FIELD_KEYED_CLAUSES and isinstance(value, dict):
                for field in value:
                    if field not in _NON_FIELD_KEYS:
                        found.add(field)
            elif key in _FIELD_LIST_CLAUSES and isinstance(value, dict):
                for field in value.get("fields") or []:
                    found.add(str(field).split("^", 1)[0])
            if isinstance(value, (dict, list)):
                _collect_query_fields(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_query_fields(item, found)
    return found


def _lint_queries(bundle, fields):
    """Named queries must only reference mapped fields."""
    findings = []
    known = set(fields)
    for query in bundle.get("queries") or []:
        if not isinstance(query, dict):
            continue
        name = query.get("name", "<unnamed>")
        body = query.get("body")
        if not isinstance(body, dict) or "query" not in body:
            findings.append(_error(
                "query.malformed",
                f"Query '{name}' must be an object containing a 'query' clause.",
                f"queries.{name}",
            ))
            continue
        # Scope collection to the query clause. Walking the whole body would
        # misread aggregations — a `terms` agg is {"terms": {"field": "genres",
        # "size": 10}}, whose keys are parameters, not field names.
        for field in sorted(_collect_query_fields(body.get("query"), set())):
            base = field.split(".")[0]
            if field in known or base in known or field.startswith("_"):
                continue
            findings.append(_error(
                "query.unmapped_field",
                f"Query '{name}' references field '{field}', which is not mapped.",
                f"queries.{name}",
            ))
    return findings


def _lint_index_settings(bundle):
    findings = []
    settings = _index_settings(bundle)

    shards = _as_int(settings.get("number_of_shards"))
    if shards is not None and shards < 1:
        findings.append(_error(
            "settings.invalid_shards",
            f"number_of_shards must be >= 1, got {shards}.",
            "settings.index.number_of_shards",
        ))

    replicas = _as_int(settings.get("number_of_replicas"))
    if replicas is not None and replicas > 0:
        findings.append(_warning(
            "settings.replicas_on_single_node",
            f"number_of_replicas is {replicas}; on a single-node dev cluster the "
            f"index will sit at yellow health. Use 0 locally.",
            "settings.index.number_of_replicas",
        ))

    return findings


def _lint_ism(bundle):
    findings = []
    policy = bundle.get("ism_policy") or {}
    body = policy.get("body") or {}
    if not body:
        return findings

    if not str(policy.get("name", "")).strip():
        findings.append(_error(
            "ism.missing_name", "ISM policy has a body but no 'name'.", "ism_policy.name"
        ))

    spec = body.get("policy") or {}
    states = spec.get("states") or []
    names = {s.get("name") for s in states if isinstance(s, dict)}

    default_state = spec.get("default_state")
    if default_state and default_state not in names:
        findings.append(_error(
            "ism.unknown_default_state",
            f"ISM default_state '{default_state}' is not among the defined states "
            f"({', '.join(sorted(n for n in names if n))}).",
            "ism_policy.policy.default_state",
        ))

    for state in states:
        if not isinstance(state, dict):
            continue
        for transition in state.get("transitions") or []:
            target = transition.get("state_name") if isinstance(transition, dict) else None
            if target and target not in names:
                findings.append(_error(
                    "ism.unknown_transition",
                    f"ISM state '{state.get('name')}' transitions to unknown state "
                    f"'{target}'.",
                    "ism_policy.policy.states",
                ))
    return findings


def has_errors(findings):
    return any(f.get("level") == "error" for f in findings)


# ---------------------------------------------------------------------------
# Render — bundle to the dense single-block blueprint
# ---------------------------------------------------------------------------

def _render_field(path, defn):
    ftype = defn.get("type", "object")
    bits = []
    if ftype == "knn_vector":
        dim = defn.get("dimension")
        bits.append(f"dim {dim}" if dim is not None else "dim ?")
        method = defn.get("method") or {}
        if method:
            triple = "/".join(
                str(method.get(k)) for k in ("name", "engine", "space_type") if method.get(k)
            )
            if triple:
                bits.append(triple)
            params = method.get("parameters") or {}
            bits.extend(f"{k} {v}" for k, v in sorted(params.items()))
    else:
        if defn.get("analyzer"):
            bits.append(f"analyzer {defn['analyzer']}")
        if defn.get("search_analyzer"):
            bits.append(f"search_analyzer {defn['search_analyzer']}")
        if defn.get("normalizer"):
            bits.append(f"normalizer {defn['normalizer']}")
        if defn.get("ignore_above") is not None:
            bits.append(f"ignore_above {defn['ignore_above']}")
        if defn.get("format"):
            bits.append(f"format {defn['format']}")
    inner = ", ".join([ftype] + bits)
    return f"{path} ({inner})"


def _render_analysis(analysis):
    chunks = []
    for name, defn in sorted((analysis.get("analyzer") or {}).items()):
        parts = []
        if defn.get("char_filter"):
            parts.append("/".join(defn["char_filter"]) + " char_filters")
        if defn.get("tokenizer"):
            parts.append(f"{defn['tokenizer']} tokenizer")
        if defn.get("filter"):
            parts.append("/".join(defn["filter"]))
        chunks.append(f"analyzer {name} ({', '.join(parts)})")
    for name, defn in sorted((analysis.get("normalizer") or {}).items()):
        filters = "/".join(defn.get("filter") or []) or "none"
        chunks.append(f"normalizer {name} ({filters})")
    return chunks


def render_blueprint(bundle):
    """Render a bundle as one dense, single-line OpenSearch blueprint."""
    sections = []

    version = bundle.get("opensearch_version") or "opensearch"
    name = (bundle.get("name") or bundle.get("index") or "UNNAMED").upper()
    pitch = bundle.get("pitch") or ""
    head = f"{version}, {name}"
    if pitch:
        head += f" — {pitch}"
    sections.append(head)

    settings = _index_settings(bundle)
    knobs = []
    for key, label in (
        ("number_of_shards", "shards"),
        ("number_of_replicas", "replicas"),
        ("refresh_interval", "refresh_interval"),
        ("codec", "codec"),
        ("knn", "knn"),
    ):
        if key not in settings:
            continue
        value = settings[key]
        if label in ("shards", "replicas"):
            count = _as_int(value)
            noun = label[:-1] if count == 1 else label
            knobs.append(f"{value} {noun}")
        elif isinstance(value, bool):
            knobs.append(f"{label} {'true' if value else 'false'}")
        else:
            knobs.append(f"{label} {value}")
    index_section = f"INDEX {bundle.get('index', '?')}"
    if knobs:
        index_section += f" ({', '.join(knobs)})"
    sections.append(index_section)

    analysis_chunks = _render_analysis(_analysis(bundle))
    if analysis_chunks:
        sections.append("ANALYSIS " + ", ".join(analysis_chunks))

    properties = (bundle.get("mappings") or {}).get("properties") or {}
    rendered = [
        _render_field(path, defn)
        for path, defn in iter_fields(properties)
        if defn.get("type")
    ]
    if rendered:
        sections.append("MAPPINGS " + ", ".join(rendered))

    ingest = bundle.get("ingest_pipeline") or {}
    if ingest.get("body"):
        moves = []
        for processor in (ingest["body"].get("processors") or []):
            for kind, cfg in (processor or {}).items():
                if not isinstance(cfg, dict):
                    continue
                for source, target in (cfg.get("field_map") or {}).items():
                    moves.append(f"{kind}: {source}→{target}")
        label = f"INGEST PIPELINE {ingest.get('name', '?')}"
        sections.append(f"{label} ({', '.join(moves)})" if moves else label)

    search_pipeline = bundle.get("search_pipeline") or {}
    if search_pipeline.get("body"):
        bits = []
        for proc in _normalization_processors(bundle):
            technique = (proc.get("normalization") or {}).get("technique")
            if technique:
                bits.append(f"normalization {technique}")
            combination = proc.get("combination") or {}
            if combination.get("technique"):
                bits.append(f"combination {combination['technique']}")
            weights = (combination.get("parameters") or {}).get("weights")
            if weights:
                bits.append("weights " + "/".join(str(w) for w in weights))
        label = f"SEARCH PIPELINE {search_pipeline.get('name', '?')}"
        sections.append(f"{label} ({', '.join(bits)})" if bits else label)

    ism = bundle.get("ism_policy") or {}
    if ism.get("body"):
        states = ((ism["body"].get("policy") or {}).get("states")) or []
        chain = " → ".join(s.get("name", "?") for s in states if isinstance(s, dict))
        label = f"ISM {ism.get('name', '?')}"
        sections.append(f"{label} ({chain})" if chain else label)

    queries = [q.get("name", "?") for q in (bundle.get("queries") or []) if isinstance(q, dict)]
    if queries:
        sections.append("QUERIES " + ", ".join(queries))

    sections.append("validated against _analyze / _validate/query / _search")
    return " — ".join(sections)


# ---------------------------------------------------------------------------
# Cluster interaction
# ---------------------------------------------------------------------------

def probe_analyzers(client, bundle):
    """Run each declared probe through the ``_analyze`` API.

    Probes prove an analyzer tokenizes the way the design claims, before any
    data is indexed. Returns a list of ``{analyzer, text, tokens, ok}`` dicts.
    """
    results = []
    analysis = _analysis(bundle)
    index = bundle.get("index")
    for probe in bundle.get("probes") or []:
        analyzer = probe.get("analyzer")
        text = probe.get("text", "")
        body = {"text": text}
        if analyzer in (analysis.get("analyzer") or {}):
            # Analyzer is index-scoped: resolve it through the index itself.
            body["analyzer"] = analyzer
            target = index
        else:
            body["analyzer"] = analyzer
            target = None
        try:
            response = client.indices.analyze(body=body, index=target)
            tokens = [t.get("token") for t in response.get("tokens", [])]
            entry = {"analyzer": analyzer, "text": text, "tokens": tokens, "ok": True}
            expected = probe.get("expect_tokens")
            if expected is not None:
                entry["expected"] = expected
                entry["ok"] = tokens == expected
        except Exception as exc:  # noqa: BLE001 - surfaced to the agent verbatim
            entry = {"analyzer": analyzer, "text": text, "error": str(exc), "ok": False}
        results.append(entry)
    return results


def validate_queries(client, index, bundle):
    """Validate every bundled query against the index via ``_validate/query``."""
    results = []
    for query in bundle.get("queries") or []:
        if not isinstance(query, dict):
            continue
        name = query.get("name", "<unnamed>")
        try:
            response = client.indices.validate_query(
                index=index, body=query.get("body") or {}, explain=True
            )
            results.append({
                "name": name,
                "valid": bool(response.get("valid")),
                "explanations": response.get("explanations", []),
            })
        except Exception as exc:  # noqa: BLE001
            results.append({"name": name, "valid": False, "error": str(exc)})
    return results


class BlueprintApplyError(RuntimeError):
    """Raised when an apply is refused by a safety gate, or fails mid-flight.

    ``code`` is a stable machine-readable reason; ``details`` carries the
    preflight plan and, for a mid-flight failure, what was rolled back.
    """

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _count_docs(client, index):
    """Document count for an index, or ``None`` if it cannot be determined.

    ``None`` is deliberately distinct from ``0``: callers must treat an unknown
    count as non-empty so an unreachable count API can never widen the blast
    radius of a delete.
    """
    try:
        response = client.count(index=index)
    except Exception:  # noqa: BLE001 - count is advisory; fail closed instead
        return None
    if isinstance(response, dict):
        count = response.get("count")
        return count if isinstance(count, int) else None
    return None


def _existing_ingest_pipeline(client, name):
    try:
        response = client.ingest.get_pipeline(id=name)
    except Exception:  # noqa: BLE001 - absent pipeline raises 404
        return None
    return response.get(name) if isinstance(response, dict) else None


def _existing_search_pipeline(client, name):
    try:
        response = client.transport.perform_request("GET", f"/_search/pipeline/{name}")
    except Exception:  # noqa: BLE001
        return None
    return response.get(name) if isinstance(response, dict) else None


def _existing_ism_policy(client, name):
    try:
        response = client.transport.perform_request(
            "GET", f"/_plugins/_ism/policies/{name}"
        )
    except Exception:  # noqa: BLE001
        return None
    if isinstance(response, dict) and response.get("policy"):
        return response
    return None


def _index_shell(client, index):
    """Capture an existing index's settings + mappings before a replace.

    Lets a failed replace restore the empty index structure. Documents are
    **not** recoverable — that is why deleting a non-empty index needs its own
    opt-in rather than relying on this.
    """
    try:
        settings_response = client.indices.get_settings(index=index)
        mappings_response = client.indices.get_mapping(index=index)
    except Exception:  # noqa: BLE001
        return None

    settings_key = _resolve_response_key(settings_response, index)
    mappings_key = _resolve_response_key(
        mappings_response, index, preferred=settings_key
    )
    raw_settings = (settings_response.get(settings_key) or {}).get("settings") or {}
    index_settings = dict(raw_settings.get("index") or {})
    for key in _NON_PORTABLE_SETTINGS:
        index_settings.pop(key, None)
    mappings = (mappings_response.get(mappings_key) or {}).get("mappings") or {}

    body = {}
    if index_settings:
        body["settings"] = {"index": index_settings}
    if mappings:
        body["mappings"] = mappings
    return body


def preflight_apply(client, bundle, replace=False):
    """Read-only report of everything applying this bundle would change.

    Touches nothing. Returns a plan describing what would be created, what
    would be overwritten, and every hazard the caller must clear before any
    mutation happens.
    """
    index = bundle.get("index")
    plan = {
        "index": index,
        "index_exists": False,
        "doc_count": 0,
        "will_delete": False,
        "creates": [],
        "overwrites": [],
        "hazards": [],
    }

    exists = bool(client.indices.exists(index=index))
    plan["index_exists"] = exists
    if exists:
        count = _count_docs(client, index)
        plan["doc_count"] = count
        if replace:
            plan["will_delete"] = True
            shown = "an unknown number of" if count is None else count
            plan["hazards"].append({
                "code": "destructive.delete_index",
                "message": (
                    f"index '{index}' exists and holds {shown} document(s); "
                    "--replace deletes it and the documents cannot be restored"
                ),
            })
        else:
            plan["hazards"].append({
                "code": "conflict.index_exists",
                "message": (
                    f"index '{index}' already exists; pass --replace to delete "
                    "and recreate it, or change the bundle's index name"
                ),
            })
    else:
        plan["creates"].append({"kind": "index", "name": index})

    ingest = bundle.get("ingest_pipeline") or {}
    if ingest.get("name") and ingest.get("body"):
        target = "overwrites" if _existing_ingest_pipeline(client, ingest["name"]) else "creates"
        plan[target].append({"kind": "ingest_pipeline", "name": ingest["name"]})

    search_pipeline = bundle.get("search_pipeline") or {}
    if search_pipeline.get("name") and search_pipeline.get("body"):
        target = (
            "overwrites"
            if _existing_search_pipeline(client, search_pipeline["name"])
            else "creates"
        )
        plan[target].append({"kind": "search_pipeline", "name": search_pipeline["name"]})

    ism = bundle.get("ism_policy") or {}
    if ism.get("name") and ism.get("body"):
        target = "overwrites" if _existing_ism_policy(client, ism["name"]) else "creates"
        plan[target].append({"kind": "ism_policy", "name": ism["name"]})

    return plan


def _unwind(undo_steps):
    """Run rollback steps newest-first. Never raises — reports what failed."""
    rolled_back, failed = [], []
    for label, action in reversed(undo_steps):
        try:
            action()
            rolled_back.append(label)
        except Exception as exc:  # noqa: BLE001 - report, do not mask the cause
            failed.append({"step": label, "error": str(exc)})
    return rolled_back, failed


def apply_bundle(client, bundle, replace=False, confirm=False,
                 allow_nonempty=False, rollback=True):
    """Create ingest pipeline, search pipeline, index, and ISM policy.

    Every hazard is resolved by a read-only preflight *before* the first
    mutation, so a refused apply leaves the cluster untouched. Deleting an
    existing index requires ``replace``; deleting one that holds documents
    additionally requires ``allow_nonempty``; either way ``confirm`` must be
    set. The delete runs as late as possible, and any failure after the first
    mutation unwinds what this call created (restoring overwritten pipelines
    and policies, and recreating the replaced index's empty shell).
    """
    index = bundle.get("index")
    plan = preflight_apply(client, bundle, replace=replace)

    if plan["index_exists"] and not replace:
        raise BlueprintApplyError(
            "index_exists",
            f"index '{index}' already exists; refusing to apply without --replace",
            {"plan": plan},
        )
    if plan["will_delete"] and plan["doc_count"] != 0:
        if not allow_nonempty:
            shown = "an unknown number of" if plan["doc_count"] is None else plan["doc_count"]
            raise BlueprintApplyError(
                "index_not_empty",
                f"index '{index}' holds {shown} document(s); refusing to delete it. "
                "Re-run with --allow-nonempty if that data is genuinely disposable",
                {"plan": plan},
            )
    if plan["will_delete"] and not confirm:
        raise BlueprintApplyError(
            "confirmation_required",
            f"applying this blueprint deletes index '{index}'; confirm with --yes",
            {"plan": plan},
        )

    applied = {"plan": plan}
    undo = []

    try:
        ingest = bundle.get("ingest_pipeline") or {}
        if ingest.get("name") and ingest.get("body"):
            name = ingest["name"]
            prior = _existing_ingest_pipeline(client, name)
            client.ingest.put_pipeline(id=name, body=ingest["body"])
            applied["ingest_pipeline"] = name
            undo.append((
                f"ingest_pipeline:{name}",
                (lambda n=name, p=prior: client.ingest.put_pipeline(id=n, body=p))
                if prior is not None
                else (lambda n=name: client.ingest.delete_pipeline(id=n)),
            ))

        search_pipeline = bundle.get("search_pipeline") or {}
        if search_pipeline.get("name") and search_pipeline.get("body"):
            name = search_pipeline["name"]
            prior = _existing_search_pipeline(client, name)
            client.transport.perform_request(
                "PUT", f"/_search/pipeline/{name}", body=search_pipeline["body"]
            )
            applied["search_pipeline"] = name
            undo.append((
                f"search_pipeline:{name}",
                (lambda n=name, p=prior: client.transport.perform_request(
                    "PUT", f"/_search/pipeline/{n}", body=p))
                if prior is not None
                else (lambda n=name: client.transport.perform_request(
                    "DELETE", f"/_search/pipeline/{n}")),
            ))

        # Destructive step, deliberately as late as possible: everything above
        # is restorable, so a failure before this point costs nothing.
        if plan["will_delete"]:
            shell = _index_shell(client, index)
            client.indices.delete(index=index)
            applied["deleted_existing"] = True
            if shell is not None:
                undo.append((
                    f"index-shell:{index}",
                    lambda i=index, b=shell: client.indices.create(index=i, body=b),
                ))

        body = {}
        if bundle.get("settings"):
            body["settings"] = bundle["settings"]
        if bundle.get("mappings"):
            body["mappings"] = bundle["mappings"]
        client.indices.create(index=index, body=body)
        applied["index"] = index
        undo.append((f"index:{index}", lambda i=index: client.indices.delete(index=i)))

        ism = bundle.get("ism_policy") or {}
        if ism.get("name") and ism.get("body"):
            name = ism["name"]
            prior = _existing_ism_policy(client, name)
            path = f"/_plugins/_ism/policies/{name}"
            if prior is not None:
                seq_no = prior.get("_seq_no")
                primary_term = prior.get("_primary_term")
                suffix = (
                    f"?if_seq_no={seq_no}&if_primary_term={primary_term}"
                    if seq_no is not None and primary_term is not None
                    else ""
                )
                client.transport.perform_request("PUT", path + suffix, body=ism["body"])
            else:
                client.transport.perform_request("PUT", path, body=ism["body"])
            applied["ism_policy"] = name
            undo.append((
                f"ism_policy:{name}",
                (lambda p=path, b={"policy": prior["policy"]}: client.transport.perform_request(
                    "PUT", p, body=b))
                if prior is not None
                else (lambda p=path: client.transport.perform_request("DELETE", p)),
            ))
    except Exception as exc:  # noqa: BLE001 - re-raised with rollback detail
        if not rollback:
            raise
        # The index we just created (if any) is not part of the damage to undo
        # when it is also the thing that failed — _unwind reports either way.
        rolled_back, failed = _unwind(undo)
        details = {"applied": applied, "rolled_back": rolled_back, "rollback_failed": failed}
        if applied.get("deleted_existing"):
            details["irreversible"] = [
                f"index '{index}' was deleted before the failure; its structure was "
                "restored if possible, but its documents are gone"
            ]
        raise BlueprintApplyError(
            "apply_failed", f"blueprint apply failed: {exc}", details
        ) from exc

    return applied


# Cluster-assigned settings that describe *this* index instance rather than the
# design, so they are stripped from anything meant to be portable or replayed.
_NON_PORTABLE_SETTINGS = (
    "uuid", "version", "provided_name", "creation_date", "routing",
)


def _resolve_response_key(response, index, preferred=None):
    """Pick the key an index-keyed API response is stored under.

    Prefers an exact match on the requested name, then the key already resolved
    from a sibling response, then the first key present.
    """
    if not isinstance(response, dict) or not response:
        return index
    if index in response:
        return index
    if preferred and preferred in response:
        return preferred
    return next(iter(response), index)


def extract_bundle(client, index):
    """Read a live index back into a blueprint bundle.

    Useful for documenting, reviewing, or migrating an index that was built by
    hand — the inverse of ``apply_bundle``.
    """
    settings_response = client.indices.get_settings(index=index)
    mappings_response = client.indices.get_mapping(index=index)

    # Resolve each response independently. When `index` is an alias or pattern,
    # the responses are keyed by concrete index name, and there is no guarantee
    # both dicts enumerate in the same order.
    settings_key = _resolve_response_key(settings_response, index)
    mappings_key = _resolve_response_key(mappings_response, index, preferred=settings_key)

    raw_settings = (settings_response.get(settings_key) or {}).get("settings") or {}
    index_settings = dict(raw_settings.get("index") or {})

    # Drop cluster-assigned metadata that is not part of a portable design.
    for key in _NON_PORTABLE_SETTINGS:
        index_settings.pop(key, None)

    mappings = (mappings_response.get(mappings_key) or {}).get("mappings") or {}

    bundle = {
        "name": index.upper(),
        "index": index,
        "settings": {"index": index_settings},
        "mappings": mappings,
        "queries": [],
    }

    default_pipeline = index_settings.get("default_pipeline")
    if default_pipeline:
        try:
            pipelines = client.ingest.get_pipeline(id=default_pipeline)
            bundle["ingest_pipeline"] = {
                "name": default_pipeline,
                "body": pipelines.get(default_pipeline, {}),
            }
        except Exception:  # noqa: BLE001 - pipeline may have been deleted
            pass

    search_pipeline = index_settings.get("search", {})
    if isinstance(search_pipeline, dict):
        default_search = search_pipeline.get("default_pipeline")
        if default_search:
            try:
                response = client.transport.perform_request(
                    "GET", f"/_search/pipeline/{default_search}"
                )
                bundle["search_pipeline"] = {
                    "name": default_search,
                    "body": response.get(default_search, {}),
                }
            except Exception:  # noqa: BLE001
                pass

    return bundle


def format_findings(findings):
    """Render findings as a human-readable report."""
    if not findings:
        return "No findings. Blueprint is internally consistent."
    lines = []
    for f in findings:
        marker = "ERROR  " if f["level"] == "error" else "WARN   "
        location = f" [{f['path']}]" if f.get("path") else ""
        lines.append(f"{marker} {f['code']}{location}: {f['message']}")
    errors = sum(1 for f in findings if f["level"] == "error")
    warnings = len(findings) - errors
    lines.append(f"\n{errors} error(s), {warnings} warning(s).")
    return "\n".join(lines)


def load_bundle(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
