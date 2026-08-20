"""Search logic for the Agent Skills UI, ported from the MCP path.

Provides smart field detection, semantic/hybrid search, agentic search,
suggestions, autocomplete, and preview text generation.
"""

import json
import re
from opensearchpy import OpenSearch

from .client import normalize_text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_NUMERIC_FIELD_TYPES = {
    "byte", "short", "integer", "long", "float",
    "half_float", "double", "scaled_float",
}
_KEYWORD_FIELD_TYPES = {"keyword", "constant_keyword"}
_EXACT_TERM_FIELD_TYPES = _KEYWORD_FIELD_TYPES | _NUMERIC_FIELD_TYPES | {
    "boolean", "date", "date_nanos", "ip", "version", "unsigned_long",
}


# ---------------------------------------------------------------------------
# Value analysis helpers
# ---------------------------------------------------------------------------
def _value_shape(text: str) -> dict[str, object]:
    compact = normalize_text(text)
    tokens = re.findall(r"[A-Za-z0-9_]+", compact)
    alpha_count = sum(1 for ch in compact if ch.isalpha())
    digit_count = sum(1 for ch in compact if ch.isdigit())
    length = len(compact)
    alpha_ratio = (alpha_count / length) if length else 0.0
    digit_ratio = (digit_count / length) if length else 0.0
    return {
        "text": compact,
        "length": length,
        "tokens": tokens,
        "token_count": len(tokens),
        "alpha_ratio": alpha_ratio,
        "digit_ratio": digit_ratio,
        "looks_numeric": bool(re.fullmatch(r"[+-]?\d+(\.\d+)?", compact)),
        "looks_date": bool(re.fullmatch(r"\d{4}([-/]\d{1,2}([-/]\d{1,2})?)?", compact)),
    }


def _text_richness_score(value: str) -> float:
    shape = _value_shape(value)
    length = int(shape["length"])
    if length < 2:
        return 0.0
    alpha_ratio = float(shape["alpha_ratio"])
    token_count = int(shape["token_count"])
    return (
        alpha_ratio * 20.0
        + token_count * 10.0
        + min(length, 100) / 100.0 * 5.0
    )


# ---------------------------------------------------------------------------
# Index introspection
# ---------------------------------------------------------------------------
def extract_index_field_specs(client: OpenSearch, index_name: str) -> dict[str, dict[str, str]]:
    field_specs: dict[str, dict[str, str]] = {}
    try:
        mapping_response = client.indices.get_mapping(index=index_name)
    except Exception:
        return field_specs

    index_mapping = {}
    if isinstance(mapping_response, dict):
        index_mapping = next(iter(mapping_response.values()), {})
    mappings = index_mapping.get("mappings", {})

    def _walk(properties: dict, prefix: str = "") -> None:
        if not isinstance(properties, dict):
            return
        for field_name, config in properties.items():
            if not isinstance(config, dict):
                continue
            full_name = f"{prefix}.{field_name}" if prefix else field_name
            field_type = config.get("type")
            if isinstance(field_type, str):
                field_specs[full_name] = {
                    "type": field_type,
                    "normalizer": str(config.get("normalizer", "")).strip(),
                }
            sub_fields = config.get("fields")
            if isinstance(sub_fields, dict):
                for sub_name, sub_config in sub_fields.items():
                    if not isinstance(sub_config, dict):
                        continue
                    sub_type = sub_config.get("type")
                    if not isinstance(sub_type, str):
                        continue
                    field_specs[f"{full_name}.{sub_name}"] = {
                        "type": sub_type,
                        "normalizer": str(sub_config.get("normalizer", "")).strip(),
                    }
            nested_props = config.get("properties")
            if isinstance(nested_props, dict):
                _walk(nested_props, full_name)

    _walk(mappings.get("properties", {}))
    return field_specs


def _resolve_text_query_fields(field_specs: dict[str, dict[str, str]], limit: int = 6) -> list[str]:
    text_fields = [
        field for field, spec in field_specs.items()
        if spec.get("type") == "text" and not field.endswith(".keyword")
    ]
    keyword_fields = [
        field for field, spec in field_specs.items()
        if spec.get("type") in _KEYWORD_FIELD_TYPES and not field.endswith(".keyword")
    ]

    def _score(field_name: str) -> tuple[int, int]:
        return field_name.count("."), len(field_name)

    ranked = sorted(text_fields, key=_score)
    if not ranked:
        ranked = sorted(keyword_fields, key=_score)
    selected = ranked[:max(1, limit)]
    return selected if selected else ["*"]


def _resolve_field_spec_for_doc_key(
    field_name: str, field_specs: dict[str, dict[str, str]]
) -> tuple[str, dict[str, str]]:
    if field_name in field_specs:
        return field_name, field_specs[field_name]
    lowered = field_name.lower()
    for candidate_name, candidate_spec in field_specs.items():
        if candidate_name.lower() == lowered:
            return candidate_name, candidate_spec
    for candidate_name, candidate_spec in field_specs.items():
        if candidate_name.split(".")[-1].lower() == lowered:
            return candidate_name, candidate_spec
    return "", {}


# ---------------------------------------------------------------------------
# Semantic / agentic runtime detection
# ---------------------------------------------------------------------------
def _resolve_semantic_runtime_hints(
    client: OpenSearch, index_name: str, field_specs: dict[str, dict[str, str]]
) -> dict[str, str]:
    vector_fields = [
        (field, spec.get("type"))
        for field, spec in field_specs.items()
        if spec.get("type") in ("knn_vector", "rank_features")
    ]
    vector_field = ""
    has_sparse = False
    if vector_fields:
        preferred = sorted(
            vector_fields,
            key=lambda item: (
                # Prefer dense over sparse when both exist
                0 if item[1] == "knn_vector" else 1,
                0 if ("embedding" in item[0].lower() or "vector" in item[0].lower()) else 1,
                len(item[0]), item[0],
            ),
        )
        vector_field = preferred[0][0]
        has_sparse = preferred[0][1] == "rank_features"

    default_pipeline = ""
    search_pipeline = ""
    model_id = ""
    has_agentic_pipeline = False

    try:
        settings_response = client.indices.get_settings(index=index_name)
        index_settings = next(iter(settings_response.values()), {})
        default_pipeline = normalize_text(
            index_settings.get("settings", {}).get("index", {}).get("default_pipeline", "")
        )
        _raw_search_pipeline = normalize_text(
            index_settings.get("settings", {}).get("index", {}).get("search", {}).get("default_pipeline", "")
        )
        search_pipeline = "" if _raw_search_pipeline in ("_none", "") else _raw_search_pipeline
    except Exception:
        pass

    has_neural_search_pipeline = False
    has_rag_processor = False
    rag_model_id = ""
    agentic_model_id = ""
    agentic_agent_type = ""

    if search_pipeline:
        try:
            pipeline_response = client.transport.perform_request("GET", f"/_search/pipeline/{search_pipeline}")
            pipeline = pipeline_response.get(search_pipeline, {})
            for processor in pipeline.get("request_processors", []):
                if isinstance(processor, dict):
                    if "agentic_query_translator" in processor:
                        has_agentic_pipeline = True
                        # Introspect the agent to get model_id and type
                        agent_id = processor["agentic_query_translator"].get("agent_id", "")
                        if agent_id:
                            try:
                                agent_resp = client.transport.perform_request("GET", f"/_plugins/_ml/agents/{agent_id}")
                                agentic_agent_type = agent_resp.get("type", "flow")
                                for tool in agent_resp.get("tools", []):
                                    if tool.get("type") == "QueryPlanningTool":
                                        agentic_model_id = tool.get("parameters", {}).get("model_id", "")
                                        break
                                if not agentic_model_id:
                                    agentic_model_id = agent_resp.get("llm", {}).get("model_id", "")
                            except Exception:
                                pass
                    if "neural_query_enricher" in processor:
                        has_neural_search_pipeline = True
            # Check response processors for RAG (conversational agent)
            for processor in pipeline.get("response_processors", []):
                if isinstance(processor, dict):
                    if "retrieval_augmented_generation" in processor:
                        has_rag_processor = True
                        rag_config = processor["retrieval_augmented_generation"]
                        rag_model_id = normalize_text(rag_config.get("model_id", ""))
            # normalization-processor in phase_results_processors also indicates neural search
            for processor in pipeline.get("phase_results_processors", []):
                if isinstance(processor, dict) and "normalization-processor" in processor:
                    has_neural_search_pipeline = True
        except Exception:
            pass

    if default_pipeline:
        try:
            pipeline_response = client.ingest.get_pipeline(id=default_pipeline)
            pipeline = pipeline_response.get(default_pipeline, {})
            for processor in pipeline.get("processors", []):
                if not isinstance(processor, dict):
                    continue
                # Support both text_embedding (dense) and sparse_encoding (sparse)
                embedding = processor.get("text_embedding") or processor.get("sparse_encoding")
                if processor.get("sparse_encoding") and not vector_fields:
                    has_sparse = True
                if not isinstance(embedding, dict):
                    continue
                candidate_model = normalize_text(embedding.get("model_id", ""))
                field_map = embedding.get("field_map", {})
                if not candidate_model:
                    continue
                if isinstance(field_map, dict) and field_map:
                    if vector_field:
                        for source, target in field_map.items():
                            if normalize_text(target) == vector_field:
                                model_id = candidate_model
                                break
                        if model_id:
                            break
                    if not model_id:
                        first_source, first_target = next(iter(field_map.items()))
                        model_id = candidate_model
                        if not vector_field:
                            vector_field = normalize_text(first_target)
                else:
                    model_id = candidate_model
                    break
        except Exception:
            pass

    # Check index _meta for sparse agentic config (agent searches directly)
    agentic_embedding_type = ""
    agentic_agent_id = ""
    try:
        mapping_resp = client.indices.get_mapping(index=index_name)
        meta = next(iter(mapping_resp.values()), {}).get("mappings", {}).get("_meta", {})
        if meta.get("agentic_type") == "sparse" and meta.get("agentic_agent_id"):
            agentic_embedding_type = "sparse"
            agentic_agent_id = meta["agentic_agent_id"]
            if meta.get("agentic_model_id"):
                agentic_model_id = meta["agentic_model_id"]
    except Exception:
        pass

    return {
        "vector_field": vector_field,
        "model_id": model_id,
        "default_pipeline": default_pipeline,
        "search_pipeline": search_pipeline,
        "has_agentic_pipeline": str(has_agentic_pipeline).lower(),
        "has_neural_search_pipeline": str(has_neural_search_pipeline).lower(),
        "has_sparse": str(has_sparse).lower(),
        "has_rag_processor": str(has_rag_processor).lower(),
        "rag_model_id": rag_model_id,
        "agentic_model_id": agentic_model_id,
        "agentic_agent_type": agentic_agent_type,
        "agentic_embedding_type": agentic_embedding_type,
        "agentic_agent_id": agentic_agent_id,
    }


# ---------------------------------------------------------------------------
# Structured query detection and building
# ---------------------------------------------------------------------------
_STRUCTURED_PATTERN = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*([:<>=!]+)\s*(.+)$")


def _parse_structured_query(query_text: str, field_specs: dict) -> list[dict] | None:
    """Parse a query string into structured filter clauses if it matches
    field:value patterns. Returns None if the query is not structured.

    Supports:
      - field:value (exact match for keyword/ip, term for numeric/date)
      - field:>value, field:>=value, field:<value, field:<=value (range)
      - Multiple clauses separated by spaces/AND (all must match)
    """
    if not field_specs:
        return None

    clauses = []
    # Split on " AND " or just try the whole string as a single clause
    parts = re.split(r"\s+AND\s+", query_text.strip())

    for part in parts:
        part = part.strip()
        m = _STRUCTURED_PATTERN.match(part)
        if not m:
            return None  # Not a structured query

        field_name, operator, value = m.group(1), m.group(2), m.group(3).strip()

        # Resolve field: check exact name, then try .keyword sub-field
        resolved_field = None
        field_type = None
        if field_name in field_specs:
            resolved_field = field_name
            field_type = field_specs[field_name].get("type", "")
        elif f"{field_name}.keyword" in field_specs:
            resolved_field = f"{field_name}.keyword"
            field_type = "keyword"
        else:
            # Try case-insensitive match
            for spec_name, spec in field_specs.items():
                if spec_name.lower() == field_name.lower():
                    resolved_field = spec_name
                    field_type = spec.get("type", "")
                    break
            if not resolved_field:
                return None  # Unknown field, not structured

        if field_type not in _EXACT_TERM_FIELD_TYPES and field_type != "text":
            return None

        # Build clause based on operator
        if operator in (":", ":=", "="):
            # For text fields, use match; for exact types, use term
            if field_type == "text":
                clauses.append({"match": {resolved_field: value}})
            else:
                # Coerce numeric values
                coerced = _coerce_value(value, field_type)
                clauses.append({"term": {resolved_field: coerced}})
        elif operator in (":>", ">"):
            clauses.append({"range": {resolved_field: {"gt": _coerce_value(value, field_type)}}})
        elif operator in (":>=", ">="):
            clauses.append({"range": {resolved_field: {"gte": _coerce_value(value, field_type)}}})
        elif operator in (":<", "<"):
            clauses.append({"range": {resolved_field: {"lt": _coerce_value(value, field_type)}}})
        elif operator in (":<=", "<="):
            clauses.append({"range": {resolved_field: {"lte": _coerce_value(value, field_type)}}})
        elif operator in (":!", "!="):
            if field_type == "text":
                clauses.append({"bool": {"must_not": [{"match": {resolved_field: value}}]}})
            else:
                coerced = _coerce_value(value, field_type)
                clauses.append({"bool": {"must_not": [{"term": {resolved_field: coerced}}]}})
        else:
            return None  # Unsupported operator

    return clauses if clauses else None


def _coerce_value(value: str, field_type: str):
    """Coerce a string value to the appropriate Python type for the field.

    For keyword, date, ip, and version fields, the string is kept as-is
    since OpenSearch expects string values for those types in term queries.
    For numeric and boolean fields, we parse to the native Python type
    so the JSON payload matches what OpenSearch expects.
    """
    # Keep string types as strings — OpenSearch handles them natively
    if field_type in _KEYWORD_FIELD_TYPES or field_type in ("date", "date_nanos", "ip", "version"):
        return value
    # For all other types (numeric, boolean, unsigned_long), attempt JSON parsing
    # which naturally handles int, float, true/false without per-type branches
    try:
        parsed = json.loads(value.lower() if value.lower() in ("true", "false") else value)
        if isinstance(parsed, (bool, int, float)):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return value


def _build_structured_filter(clauses: list[dict]) -> dict:
    """Build an OpenSearch query from parsed structured clauses."""
    if len(clauses) == 1:
        return clauses[0]
    return {"bool": {"must": clauses}}


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------
def _build_default_lexical_query(
    query: str, fields: list[str], fuzziness: str | None = "AUTO"
) -> dict:
    """Build a `multi_match` query.

    ``fuzziness`` defaults to ``"AUTO"`` for named fields; pass ``None`` to match
    exactly, which callers whose relevance is tuned for a fixed mapping rely on.
    """
    body: dict[str, object] = {"query": query, "fields": fields or ["*"]}
    if fuzziness and any(field != "*" for field in fields):
        body["fuzziness"] = fuzziness
    return {"multi_match": body}


def _build_default_lexical_body(query: str, size: int, fields: list[str]) -> dict:
    return {"size": size, "query": _build_default_lexical_query(query=query, fields=fields)}


def _build_neural_clause(query: str, vector_field: str, model_id: str, size: int) -> dict:
    return {
        "neural": {
            vector_field: {
                "query_text": query,
                "model_id": model_id,
                "k": max(size, 10),
            }
        }
    }


def _build_neural_sparse_clause(query: str, vector_field: str, model_id: str = "") -> dict:
    clause: dict = {"query_text": query}
    if model_id:
        clause["model_id"] = model_id
    return {"neural_sparse": {vector_field: clause}}


# ---------------------------------------------------------------------------
# Preview & suggestions
# ---------------------------------------------------------------------------
def _suggestion_candidates_from_doc(source: dict) -> list[str]:
    if not isinstance(source, dict):
        return []
    scored: list[tuple[float, str]] = []
    for value in source.values():
        if value is None or isinstance(value, (dict, list)):
            continue
        shape = _value_shape(str(value))
        compact = str(shape["text"])
        length = int(shape["length"])
        if length < 4 or length > 80:
            continue
        if shape["looks_numeric"] or shape["looks_date"]:
            continue
        score = _text_richness_score(str(value))
        scored.append((score, compact))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in scored]


def _is_vector_value(v: object) -> bool:
    """Return True if *v* looks like a dense or sparse embedding vector."""
    if isinstance(v, list) and len(v) >= 16:
        # Dense vector: list of 16+ numbers
        sample = v[:8]
        if all(isinstance(x, (int, float)) for x in sample):
            return True
    if isinstance(v, dict) and len(v) >= 4:
        # Sparse vector: dict with string keys and numeric values
        # Covers both numeric-key sparse vectors and neural sparse
        # token-weight vectors (e.g. {"movie": 0.33, "comedy": 0.12})
        # Use a low threshold (4) to catch pruned sparse vectors with
        # fewer tokens.
        items = list(v.items())
        sample = items[:16] if len(items) > 16 else items
        if all(
            isinstance(k, str) and isinstance(val, (int, float))
            for k, val in sample
        ):
            return True
    return False


_HIDDEN_FIELDS = {"bboxes"}


def _strip_vector_fields(source: dict) -> dict:
    """Return a shallow copy of *source* with embedding/vector and internal fields removed."""
    return {k: v for k, v in source.items() if not _is_vector_value(v) and k not in _HIDDEN_FIELDS}


def preview_text(source: dict) -> str:
    candidates = _suggestion_candidates_from_doc(source)
    if candidates:
        return candidates[0]
    if source:
        for value in source.values():
            if value is None or isinstance(value, (dict, list)):
                continue
            text = " ".join(str(value).split())
            if text:
                return text[:180]
    return "(No preview text)"


def generate_suggestions(
    client: OpenSearch, index_name: str, max_count: int = 8,
) -> dict:
    """Generate diverse suggestions with capability/query_mode metadata.

    Returns a dict with:
        - suggestions: list of test queries covering exact, structured,
          autocomplete, fuzzy, combined, and semantic (when available).
        - sample_docs: list of sample documents (vector fields stripped).
        - has_semantic: whether the index supports semantic/hybrid search.
    """
    empty = {"suggestions": [], "sample_docs": [], "has_semantic": False}
    if not index_name:
        return empty

    field_specs = extract_index_field_specs(client, index_name)
    runtime_hints = _resolve_semantic_runtime_hints(client, index_name, field_specs)
    has_semantic = bool(
        (runtime_hints.get("vector_field") and runtime_hints.get("model_id"))
        or runtime_hints.get("has_neural_search_pipeline", "false") == "true"
    )

    # Categorise fields
    text_fields, keyword_fields, numeric_fields = [], [], []
    # Track text fields that have .keyword sub-fields (filterable)
    filterable_fields = []
    for name, spec in field_specs.items():
        ftype = spec.get("type", "")
        if ftype == "text" and not name.endswith(".keyword"):
            text_fields.append(name)
            # Check if this text field has a .keyword sub-field
            if f"{name}.keyword" in field_specs:
                filterable_fields.append(name)
        elif ftype in _KEYWORD_FIELD_TYPES and not name.endswith(".keyword"):
            keyword_fields.append(name)
            filterable_fields.append(name)
        elif ftype in _NUMERIC_FIELD_TYPES:
            numeric_fields.append(name)

    # Sample a few documents
    try:
        response = client.search(
            index=index_name,
            body={"size": 20, "query": {"match_all": {}}},
        )
        docs = [h.get("_source", {}) for h in response.get("hits", {}).get("hits", [])]
    except Exception:
        docs = []

    if not docs:
        return empty

    # Strip vector fields from sample docs for agent readability
    sample_docs = [_strip_vector_fields(doc) for doc in docs]

    meta: list[dict] = []
    seen: set[str] = set()

    def _add(text: str, capability: str, query_mode: str, field: str = ""):
        key = text.lower().strip()
        if key in seen or not key:
            return
        seen.add(key)
        meta.append({
            "text": text.strip(),
            "capability": capability,
            "query_mode": query_mode,
            "field": field,
            "value": "",
            "case_insensitive": False,
        })

    # Resolve title fields early (used by exact, structured, and other sections)
    title_fields = [f for f in text_fields if any(h in f.lower() for h in ("title", "name", "label"))]
    title_set = set(f.lower() for f in (title_fields or []))

    # 1. Exact match — title/name value
    if title_fields:
        for doc in docs[1:6]:
            val = str(doc.get(title_fields[0], "")).strip()
            if 3 < len(val) < 100:
                _add(val, "exact", "TERM")
                break

    # 2. Structured — filterable field:value
    filter_candidates = [f for f in filterable_fields if f.lower() not in title_set]
    if not filter_candidates and numeric_fields:
        filter_candidates = numeric_fields[:2]
    if filter_candidates:
        for doc in docs[:10]:
            for kf in filter_candidates:
                val = doc.get(kf)
                if val is None:
                    continue
                # For array fields, use the first element
                if isinstance(val, list):
                    val = val[0] if val else None
                    if val is None:
                        continue
                val_str = str(val).strip()
                if val_str and len(val_str) < 60:
                    _add(f"{kf}:{val_str}", "structured", "FILTER", field=kf)
                    break
            if sum(1 for m in meta if m["capability"] == "structured") >= 1:
                break

    # 3. Combined — text + filter (semantic + structured)
    if has_semantic and filter_candidates and title_fields:
        for doc in docs[3:10]:
            title_val = str(doc.get(title_fields[0], "")).strip()
            for kf in filter_candidates:
                kf_val = doc.get(kf)
                if kf_val is None:
                    continue
                if isinstance(kf_val, list):
                    kf_val = kf_val[0] if kf_val else None
                    if kf_val is None:
                        continue
                kf_val_str = str(kf_val).strip()
                if title_val and kf_val_str and len(kf_val_str) < 40:
                    words = title_val.split()[:3]
                    _add(f"{' '.join(words)} {kf}:{kf_val_str}", "combined", "HYBRID+FILTER")
                    break
            if sum(1 for m in meta if m["capability"] == "combined") >= 1:
                break

    # 4. Autocomplete — prefix of a title/name
    if title_fields:
        for doc in docs[2:8]:
            val = str(doc.get(title_fields[0], "")).strip()
            if len(val) > 5:
                prefix = val[:max(4, len(val) // 3)]
                _add(prefix, "autocomplete", "PREFIX", field=title_fields[0])
                break

    # 5. Fuzzy — intentional slight misspelling of a title
    if title_fields:
        for doc in docs[4:10]:
            val = str(doc.get(title_fields[0], "")).strip()
            words = val.split()
            if words and len(words[0]) > 4:
                # Swap two middle characters to create a typo
                w = words[0]
                mid = len(w) // 2
                fuzzy_word = w[:mid-1] + w[mid] + w[mid-1] + w[mid+1:]
                rest = " ".join(words[1:])
                fuzzy_text = f"{fuzzy_word} {rest}".strip() if rest else fuzzy_word
                _add(fuzzy_text, "fuzzy", "FUZZY")
                break

    # 6. Semantic — natural language query from descriptive text fields
    if has_semantic:
        # Find long text fields likely to contain descriptions
        desc_fields = [f for f in text_fields if any(
            h in f.lower() for h in ("overview", "description", "plot", "summary", "content", "body", "text", "abstract")
        )]
        if not desc_fields:
            # Fall back to any text field that isn't a title
            desc_fields = [f for f in text_fields if f.lower() not in title_set]
        if desc_fields:
            for doc in docs[:10]:
                val = str(doc.get(desc_fields[0], "")).strip()
                if len(val) < 20:
                    continue
                # Use the first sentence or clause as a natural query
                for sep in ",;.—":
                    pos = val.find(sep)
                    if 15 < pos < 80:
                        phrase = val[:pos].strip()
                        break
                else:
                    # No sentence boundary — take first ~8 words
                    words = val.split()
                    phrase = " ".join(words[:min(8, len(words))]).rstrip(".,;:")
                if 10 < len(phrase) < 120:
                    _add(phrase, "semantic", "SEMANTIC")
                    break

    # 7. Another exact if we have room
    if title_fields and len(meta) < max_count:
        for doc in docs[5:12]:
            val = str(doc.get(title_fields[0], "")).strip()
            if 3 < len(val) < 100:
                _add(val, "exact", "TERM")
                if sum(1 for m in meta if m["capability"] == "exact") >= 2:
                    break

    return {
        "suggestions": meta[:max_count],
        "sample_docs": sample_docs,
        "has_semantic": has_semantic,
    }


# ---------------------------------------------------------------------------
# Autocomplete
# ---------------------------------------------------------------------------
def _resolve_autocomplete_fields(
    field_specs: dict[str, dict[str, str]],
    preferred_field: str = "",
    limit: int = 4,
) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    def _append(field_name: str) -> None:
        normalized = normalize_text(field_name)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        selected.append(normalized)

    preferred = normalize_text(preferred_field)
    if preferred:
        resolved_field, resolved_spec = _resolve_field_spec_for_doc_key(preferred, field_specs)
        candidate = resolved_field or preferred
        candidate_type = str(resolved_spec.get("type", "")).strip().lower()
        if candidate_type in {"keyword", "constant_keyword", "text"}:
            _append(candidate)

    keyword_fields = [
        name for name, spec in field_specs.items()
        if str(spec.get("type", "")).strip().lower() in {"keyword", "constant_keyword"}
    ]
    text_fields = [
        name for name, spec in field_specs.items()
        if str(spec.get("type", "")).strip().lower() == "text"
    ]

    def _rank(field_name: str) -> tuple[int, int, str]:
        return (field_name.count("."), len(field_name), field_name)

    for field_name in sorted(text_fields, key=_rank):
        _append(field_name)
        if len(selected) >= max(1, limit):
            return selected
    for field_name in sorted(keyword_fields, key=_rank):
        _append(field_name)
        if len(selected) >= max(1, limit):
            return selected
    return selected


def _source_field_variants(field_name: str) -> list[str]:
    normalized = normalize_text(field_name)
    if not normalized:
        return []
    variants = [normalized]
    if normalized.endswith(".keyword"):
        base_field = normalized[:-8]
        if base_field:
            variants.insert(0, base_field)
    return variants


def _extract_values_from_source_by_path(source: object, field_path: str) -> list[object]:
    path = normalize_text(field_path)
    if not path:
        return []
    segments = [segment for segment in path.split(".") if segment]
    if not segments:
        return []
    values: list[object] = []

    def _walk(node: object, idx: int) -> None:
        if idx >= len(segments):
            if isinstance(node, list):
                for item in node:
                    _walk(item, idx)
                return
            if isinstance(node, dict) or node is None:
                return
            values.append(node)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item, idx)
            return
        if isinstance(node, dict):
            child = node.get(segments[idx])
            if child is not None:
                _walk(child, idx + 1)

    _walk(source, 0)
    return values


def autocomplete(
    client: OpenSearch, index_name: str, prefix_text: str,
    size: int = 8, preferred_field: str = "",
) -> dict[str, object]:
    target_index = normalize_text(index_name)
    prefix = normalize_text(prefix_text)
    effective_size = max(1, min(size, 20))
    if not target_index or not prefix:
        return {"index": target_index, "prefix": prefix, "field": "", "options": [], "error": ""}

    try:
        field_specs = extract_index_field_specs(client, target_index)
        fields = _resolve_autocomplete_fields(field_specs, preferred_field, limit=4)
        if not fields:
            return {"index": target_index, "prefix": prefix, "field": "", "options": [],
                    "error": "No suitable autocomplete fields found."}

        should_clauses = [{"prefix": {f: {"value": prefix.lower(), "case_insensitive": True}}} for f in fields]
        body = {
            "size": max(effective_size * 8, 24),
            "query": {"bool": {"should": should_clauses, "minimum_should_match": 1}},
        }
        response = client.search(index=target_index, body=body)

        options: list[str] = []
        seen: set[str] = set()
        prefix_lower = prefix.lower()

        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            if not isinstance(source, dict):
                continue
            for field_name in fields:
                for variant in _source_field_variants(field_name):
                    raw_values = _extract_values_from_source_by_path(source, variant)
                    for raw_value in raw_values:
                        candidate = normalize_text(raw_value)
                        if not candidate or len(candidate) > 100 or not candidate.lower().startswith(prefix_lower):
                            continue
                        key = candidate.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        options.append(candidate[:120])
                        if len(options) >= effective_size:
                            return {"index": target_index, "prefix": prefix,
                                    "field": fields[0], "options": options, "error": ""}

        return {"index": target_index, "prefix": prefix, "field": fields[0] if fields else "",
                "options": options, "error": ""}
    except Exception as e:
        return {"index": target_index, "prefix": prefix, "field": "", "options": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Search config: one query configuration per index from the execution plan
# ---------------------------------------------------------------------------
_search_configs: dict[str, dict] = {}

# Agent prompts cache: {index_name: (timestamp, prompts_dict)}
_agent_prompts_cache: dict[str, tuple[float, dict]] = {}
_AGENT_PROMPTS_CACHE_TTL = 300  # 5 minutes


def set_search_config(index_name: str, config: dict) -> None:
    """Store the execution plan's query configuration for an index.

    Config keys:
        strategy: "bm25" | "neural_sparse" | "dense_vector" | "hybrid" | "agentic_flow" | "agentic_conversational"
        lexical_fields: list of field names (with optional ^boost)
        vector_field: name of the vector/rank_features field (if semantic)
        vector_type: "sparse" | "dense" (if semantic)
        model_id: ML model ID for query-time encoding (if semantic)
    """
    _search_configs[index_name] = config


def get_search_config(index_name: str) -> dict | None:
    """Retrieve the stored search config for an index, or None."""
    return _search_configs.get(index_name)


def clear_search_config(index_name: str = None) -> None:
    """Clear cached search config for an index, or all indices if None."""
    if index_name:
        _search_configs.pop(index_name, None)
    else:
        _search_configs.clear()


def _introspect_search_config(client: OpenSearch, index_name: str) -> dict:
    """Derive a search config by introspecting the index (fallback when no
    execution plan config is available)."""
    field_specs = extract_index_field_specs(client, index_name)
    lexical_fields = _resolve_text_query_fields(field_specs)
    hints = _resolve_semantic_runtime_hints(client, index_name, field_specs)

    vector_field = hints.get("vector_field", "")
    model_id = hints.get("model_id", "")
    has_sparse = hints.get("has_sparse", "false") == "true"
    has_neural = hints.get("has_neural_search_pipeline", "false") == "true"
    has_agentic = hints.get("has_agentic_pipeline", "false") == "true"
    agentic_embedding_type = hints.get("agentic_embedding_type", "")
    semantic_ready = bool(vector_field and (model_id or (has_sparse and has_neural)))

    has_search_pipeline = bool(hints.get("search_pipeline", ""))
    has_rag = hints.get("has_rag_processor", "false") == "true"

    # Sparse agentic (detected via _meta) is also a flow agent
    if agentic_embedding_type == "sparse":
        strategy = "agentic_flow"
    elif has_agentic:
        # Conversational agent has RAG processor, flow agent does not
        strategy = "agentic_conversational" if has_rag else "agentic_flow"
    elif semantic_ready and has_search_pipeline:
        strategy = "hybrid"
    elif semantic_ready:
        strategy = "neural_sparse" if has_sparse else "dense_vector"
    else:
        strategy = "bm25"

    # Determine agentic_embedding_type if not already set from _meta
    if not agentic_embedding_type and has_agentic:
        agentic_embedding_type = "dense"

    return {
        "strategy": strategy,
        "lexical_fields": lexical_fields,
        "field_specs": field_specs,
        "vector_field": vector_field,
        "vector_type": "sparse" if has_sparse else "dense",
        "model_id": model_id,
        "rag_model_id": hints.get("rag_model_id", ""),
        "agentic_model_id": hints.get("agentic_model_id", ""),
        "agentic_agent_type": hints.get("agentic_agent_type", ""),
        "agentic_embedding_type": agentic_embedding_type,
        "agentic_agent_id": hints.get("agentic_agent_id", ""),
    }


def _build_search_query(config: dict, query_text: str, size: int, memory_id: str = "") -> dict:
    """Build the search query clause from a search config and query text.

    If the query matches a structured pattern (field:value), build a term/range
    query. Otherwise, use the configured strategy (BM25, hybrid, neural, etc.).
    """
    strategy = config.get("strategy", "bm25")
    lexical_fields = config.get("lexical_fields", ["*"])
    vector_field = config.get("vector_field", "")
    vector_type = config.get("vector_type", "sparse")
    model_id = config.get("model_id", "")
    field_specs = config.get("field_specs", {})

    # Try structured query parsing first (field:value, field:>value, etc.)
    structured_clauses = _parse_structured_query(query_text, field_specs)
    if structured_clauses is not None:
        return _build_structured_filter(structured_clauses)

    lexical = _build_default_lexical_query(query_text, lexical_fields)

    if strategy == "hybrid":
        if vector_type == "sparse":
            semantic = _build_neural_sparse_clause(query_text, vector_field, model_id)
        else:
            semantic = _build_neural_clause(query_text, vector_field, model_id, size)
        return {"hybrid": {"queries": [lexical, semantic]}}
    elif strategy == "neural_sparse":
        return _build_neural_sparse_clause(query_text, vector_field, model_id)
    elif strategy == "dense_vector":
        return _build_neural_clause(query_text, vector_field, model_id, size)
    elif strategy in ("agentic_flow", "agentic_conversational"):
        agentic_query: dict = {"query_text": query_text}
        if memory_id:
            agentic_query["memory_id"] = memory_id
        return {"agentic": agentic_query}
    else:
        return lexical


# ---------------------------------------------------------------------------
# Sparse agentic search (agent calls NeuralSparseSearchTool directly)
# ---------------------------------------------------------------------------
def _search_sparse_agentic(
    client: OpenSearch, index_name: str, query: str, size: int, config: dict,
) -> dict:
    """Execute agentic search with sparse embedding.

    The flow agent uses NeuralSparseSearchTool to perform neural_sparse search
    directly (no agentic_query_translator pipeline). Results are parsed from the
    tool output and formatted for the UI.
    """
    agent_id = config.get("agentic_agent_id", "")
    agentic_model_id = config.get("agentic_model_id", "")

    if not agent_id:
        return {
            "error": "Sparse agentic agent_id not found in index _meta.",
            "hits": [], "total": 0, "took_ms": 0,
            "query_mode": "agentic", "capability": "agentic_flow",
            "used_semantic": True, "fallback_reason": "missing agent_id",
        }

    try:
        import time as _t
        t0 = _t.time()
        resp = client.transport.perform_request(
            "POST",
            f"/_plugins/_ml/agents/{agent_id}/_execute",
            body={"parameters": {"input": query}},
        )
        took_ms = int((_t.time() - t0) * 1000)

        # Parse NeuralSparseSearchTool output: newline-delimited JSON documents
        raw_result = ""
        for inference in resp.get("inference_results", []):
            for output in inference.get("output", []):
                raw_result += output.get("result", "")

        hits_out = _parse_sparse_tool_results(raw_result)

        result: dict = {
            "error": "",
            "hits": hits_out[:size],
            "total": len(hits_out),
            "took_ms": took_ms,
            "query_mode": "agentic",
            "capability": "agentic_flow",
            "used_semantic": True,
            "fallback_reason": "",
        }

        # Generate RAG answer via LLM predict
        if agentic_model_id and hits_out:
            rag_answer = _generate_rag_summary(client, agentic_model_id, query, hits_out)
            if rag_answer:
                result["rag_answer"] = rag_answer

        return result

    except Exception as e:
        # Fallback to BM25 on agent failure
        lexical_fields = config.get("lexical_fields", ["*"])
        try:
            fallback_body = _build_default_lexical_body(query=query, size=size, fields=lexical_fields)
            response = client.search(index=index_name, body=fallback_body)
            return _format_search_response(
                response, "agentic_fallback_bm25", "agentic_flow",
                False, f"agent execution failed: {e}",
            )
        except Exception:
            return {
                "error": str(e), "hits": [], "total": 0, "took_ms": 0,
                "query_mode": "agentic", "capability": "agentic_flow",
                "used_semantic": False, "fallback_reason": str(e),
            }


def _parse_sparse_tool_results(raw_result: str) -> list[dict]:
    """Parse NeuralSparseSearchTool output into hit dicts for the UI."""
    hits_out = []

    # Try newline-delimited JSON first
    for line in raw_result.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
            if isinstance(doc, list):
                # Got a JSON array on a single line — handle below
                hits_out = []
                break
            source = doc.get("_source", doc)
            clean_source = _strip_vector_fields(source)
            hits_out.append({
                "id": doc.get("_id", ""),
                "score": doc.get("_score"),
                "preview": preview_text(source),
                "source": clean_source,
            })
        except json.JSONDecodeError:
            continue

    # Fallback: try as single JSON array
    if not hits_out and raw_result.strip():
        try:
            parsed = json.loads(raw_result)
            if isinstance(parsed, list):
                for doc in parsed:
                    source = doc.get("_source", doc)
                    clean_source = _strip_vector_fields(source)
                    hits_out.append({
                        "id": doc.get("_id", ""),
                        "score": doc.get("_score"),
                        "preview": preview_text(source),
                        "source": clean_source,
                    })
        except json.JSONDecodeError:
            pass

    return hits_out


def _generate_rag_summary(
    client: OpenSearch, model_id: str, query: str, hits: list[dict],
) -> str:
    """Generate a RAG summary from search hits using the LLM model."""
    try:
        context_parts = []
        for i, hit in enumerate(hits[:5]):
            src = hit.get("source", {})
            parts = [f"{i + 1}."]
            for key, val in src.items():
                if val is not None and not isinstance(val, (dict, list)) and str(val).strip():
                    sv = str(val).strip()
                    if len(sv) > 120:
                        sv = sv[:117] + "..."
                    parts.append(f"{key}: {sv}")
                if len(parts) > 8:
                    break
            context_parts.append(" | ".join(parts))
        context_text = "\n".join(context_parts)

        llm_prompt = (
            f'The user asked: "{query}"\n\n'
            f"Search returned {len(hits)} results. Here are the top matches:\n"
            f"{context_text}\n\n"
            f"Provide a brief, conversational summary of these results. "
            f"Mention specific items and key details. Keep it under 100 words."
        )
        predict_body = {
            "parameters": {
                "system_prompt": "You are a helpful search assistant. Summarize search results concisely.",
                "user_prompt": llm_prompt,
            }
        }
        llm_response = client.transport.perform_request(
            "POST", f"/_plugins/_ml/models/{model_id}/_predict", body=predict_body,
        )
        inference = llm_response.get("inference_results", [{}])[0]
        output_data = inference.get("output", [{}])[0].get("dataAsMap", {})
        return (
            output_data.get("output", {})
            .get("message", {})
            .get("content", [{}])[0]
            .get("text", "")
        )
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Main search
# ---------------------------------------------------------------------------
def search_ui_search(
    client: OpenSearch,
    index_name: str,
    query_text: str,
    size: int = 20,
    debug: bool = False,
    search_intent: str = "",
    field_hint: str = "",
    memory_id: str = "",
) -> dict:
    empty_response = {
        "error": "", "hits": [], "total": 0, "took_ms": 0,
        "query_mode": "", "capability": "",
        "used_semantic": False, "fallback_reason": "",
    }

    if not index_name:
        empty_response["error"] = "Missing index name."
        return empty_response

    # Load execution plan config, or introspect once and cache
    config = get_search_config(index_name)
    if not config:
        config = _introspect_search_config(client, index_name)
        set_search_config(index_name, config)

    strategy = config.get("strategy", "bm25")
    query = query_text.strip()
    fallback_reason = ""
    is_agentic = strategy in ("agentic_flow", "agentic_conversational")
    agentic_embedding_type = config.get("agentic_embedding_type", "")
    used_semantic = strategy in ("hybrid", "neural_sparse", "dense_vector") or is_agentic

    # Sparse embedding: agent executes search directly via NeuralSparseSearchTool
    if is_agentic and agentic_embedding_type == "sparse" and query:
        return _search_sparse_agentic(client, index_name, query, size, config)

    if not query:
        executed_body: dict = {"size": size, "query": {"match_all": {}}}
        query_mode = "match_all"
    else:
        # Build query from the execution plan config — same for all queries
        executed_body = {
            "size": size,
            "query": _build_search_query(config, query, size, memory_id=memory_id),
        }
        query_mode = "agentic" if is_agentic else strategy

        # Conversational agent: add ext.generative_qa_parameters for RAG processor
        # llm_model must start with "bedrock/" to trigger BEDROCK provider format
        # in ML Commons, which sends ${parameters.inputs} to the connector.
        if strategy == "agentic_conversational":
            rag_params: dict = {
                "llm_model": "bedrock/claude",
                "llm_question": query,
                "context_size": 5,
                "message_size": 5,
                "timeout": 60,
            }
            executed_body["ext"] = {"generative_qa_parameters": rag_params}

    # Preserve RAG ext params for fallback queries (pipeline requires them)
    rag_ext = executed_body.get("ext")

    # Agentic search needs longer timeout (agent + RAG both call Bedrock)
    search_timeout = 60 if is_agentic else 10
    try:
        response = client.search(index=index_name, body=executed_body, request_timeout=search_timeout)
        # Retry once on zero hits for agentic queries — the agent may generate
        # different DSL on a second attempt due to LLM non-determinism.
        if is_agentic and query and not response.get("hits", {}).get("hits"):
            try:
                response = client.search(index=index_name, body=executed_body, request_timeout=search_timeout)
            except Exception:
                pass  # Keep the original zero-hit response
    except Exception as query_error:
        if query:
            fallback_reason = f"primary query failed: {query_error}"
            lexical_fields = config.get("lexical_fields", ["*"])
            executed_body = _build_default_lexical_body(
                query=query, size=size, fields=lexical_fields,
            )
            if rag_ext:
                executed_body["ext"] = rag_ext
            try:
                response = client.search(index=index_name, body=executed_body)
            except Exception:
                executed_body = {
                    "size": size,
                    "query": {"multi_match": {"query": query, "fields": ["*"]}},
                }
                if rag_ext:
                    executed_body["ext"] = rag_ext
                response = client.search(index=index_name, body=executed_body)
            used_semantic = False
            query_mode = f"{query_mode}_fallback_bm25"
        else:
            raise

    capability = strategy

    result = _format_search_response(
        response, query_mode, capability, used_semantic,
        fallback_reason, executed_body if debug else None,
    )

    # LLM summary fallback chain for agentic search:
    # 1. RAG processor answer (already extracted by _format_search_response)
    # 2. Model predict summary via /_plugins/_ml/models/{model_id}/_predict
    # 3. Client-side generateChatSummary (handled by UI)
    if is_agentic and query and not result.get("rag_answer") and result.get("hits"):
        predict_model_id = config.get("agentic_model_id", "")
        if predict_model_id:
            try:
                context_parts = []
                for i, hit in enumerate(result["hits"][:5]):
                    src = hit.get("source", {})
                    parts = [f"{i + 1}."]
                    for key, val in src.items():
                        if val is not None and not isinstance(val, (dict, list)) and str(val).strip():
                            sv = str(val).strip()
                            if len(sv) > 120:
                                sv = sv[:117] + "..."
                            parts.append(f"{key}: {sv}")
                        if len(parts) > 8:
                            break
                    context_parts.append(" | ".join(parts))
                context_text = "\n".join(context_parts)
                total_count = result.get("total", len(result["hits"]))

                llm_prompt = (
                    f'The user asked: "{query}"\n\n'
                    f"Search returned {total_count} results. Here are the top matches:\n"
                    f"{context_text}\n\n"
                    f"Provide a brief, conversational summary of these results. "
                    f"Mention specific items and key details. Keep it under 100 words."
                )
                predict_body = {
                    "parameters": {
                        "system_prompt": "You are a helpful search assistant. Summarize search results concisely.",
                        "user_prompt": llm_prompt,
                    }
                }
                llm_response = client.transport.perform_request(
                    "POST",
                    f"/_plugins/_ml/models/{predict_model_id}/_predict",
                    body=predict_body,
                )
                inference = llm_response.get("inference_results", [{}])[0]
                output_data = inference.get("output", [{}])[0].get("dataAsMap", {})
                answer_text = (
                    output_data.get("output", {})
                    .get("message", {})
                    .get("content", [{}])[0]
                    .get("text", "")
                )
                if answer_text:
                    result["rag_answer"] = answer_text
            except Exception:
                pass  # Fall through to client-side summary

    return result


def detect_index_profile(client: OpenSearch, index_name: str) -> dict:
    """Analyze index to detect field categories, capabilities, and suggest a UI template."""
    field_specs = extract_index_field_specs(client, index_name)
    runtime_hints = _resolve_semantic_runtime_hints(client, index_name, field_specs)

    text_fields = []
    keyword_fields = []
    numeric_fields = []
    date_fields = []
    vector_fields = []

    for name, spec in field_specs.items():
        ftype = spec.get("type", "")
        if ftype == "text" and not name.endswith(".keyword"):
            text_fields.append(name)
        elif ftype in _KEYWORD_FIELD_TYPES and not name.endswith(".keyword"):
            keyword_fields.append(name)
        elif ftype in _NUMERIC_FIELD_TYPES:
            numeric_fields.append(name)
        elif ftype in ("date", "date_nanos"):
            date_fields.append(name)
        elif ftype in ("knn_vector", "rank_features"):
            vector_fields.append(name)

    has_agentic = (
        runtime_hints.get("has_agentic_pipeline", "false") == "true"
        or bool(runtime_hints.get("agentic_agent_id"))
    )
    has_sparse = runtime_hints.get("has_sparse", "false") == "true"
    has_neural_search_pipeline = runtime_hints.get("has_neural_search_pipeline", "false") == "true"
    has_semantic = bool(
        (runtime_hints.get("vector_field") and (
            runtime_hints.get("model_id") or (has_sparse and has_neural_search_pipeline)
        ))
        or has_neural_search_pipeline
    )

    capabilities = ["lexical"]
    if has_semantic:
        capabilities.insert(0, "semantic")
    if has_agentic:
        capabilities.insert(0, "agentic")
    if keyword_fields or numeric_fields:
        capabilities.append("structured")

    # Detect image-like fields
    _image_hints = {"image", "img", "poster", "photo", "thumbnail", "picture", "cover", "avatar", "logo", "icon"}
    has_image_field = any(
        any(hint in name.lower() for hint in _image_hints)
        for name in field_specs
    )

    # Detect price/cost fields (strong ecommerce signal)
    _price_hints = {"price", "cost", "msrp", "amount", "discount", "sale_price", "list_price"}
    has_price_field = any(
        any(hint in name.lower() for hint in _price_hints)
        for name in numeric_fields
    )

    # Detect category/brand fields (ecommerce signal)
    _ecommerce_hints = {"category", "brand", "sku", "product", "vendor", "manufacturer", "color", "size", "stock", "inventory"}
    has_ecommerce_field = any(
        any(hint in name.lower() for hint in _ecommerce_hints)
        for name in keyword_fields
    )

    structured_count = len(keyword_fields) + len(numeric_fields) + len(date_fields)
    # NOTE: agentic-chat and media templates are disabled in the UI for now.
    # if has_agentic:
    #     template = "agentic-chat"
    # elif has_image_field and structured_count >= 2:
    #     template = "media"
    if has_agentic:
        template = "agent"
    elif has_price_field or (has_image_field and has_ecommerce_field):
        template = "ecommerce"
    elif text_fields or vector_fields:
        template = "document"
    else:
        template = "document"

    # Hide vector/embedding fields from UI-facing field lists
    _embedding_hints = {"embedding", "vector", "knn", "dense_vector", "rank_features"}
    _hidden = set(vector_fields)
    for name in field_specs:
        if any(h in name.lower() for h in _embedding_hints):
            _hidden.add(name)

    ui_fields = {n: s["type"] for n, s in field_specs.items() if n not in _hidden}
    ui_field_specs = {n: s for n, s in field_specs.items() if n not in _hidden}

    return {
        "fields": ui_fields,
        "field_specs": ui_field_specs,
        "field_categories": {
            "text": [f for f in text_fields if f not in _hidden],
            "keyword": [f for f in keyword_fields if f not in _hidden],
            "numeric": [f for f in numeric_fields if f not in _hidden],
            "date": [f for f in date_fields if f not in _hidden],
            "vector": vector_fields,
        },
        "capabilities": capabilities,
        "suggested_template": template,
        "has_semantic": has_semantic,
        "has_agentic": has_agentic,
        "agentic_agent_type": runtime_hints.get("agentic_agent_type", "") or (
            "flow" if runtime_hints.get("agentic_agent_id") else ""
        ),
    }


def generate_agent_prompts(client: OpenSearch, index_name: str) -> dict:
    """Generate data-aware natural language prompts for the agent template.

    Samples a few docs from the index, inspects field names and values,
    then uses the agentic LLM to generate contextual search/chat prompts.
    Falls back to schema-based heuristic prompts if LLM is unavailable.
    Results are cached per index for 5 minutes.
    """
    import time as _time

    cached = _agent_prompts_cache.get(index_name)
    if cached:
        ts, prompts = cached
        if _time.time() - ts < _AGENT_PROMPTS_CACHE_TTL:
            return prompts
    fallback: dict = {"search": [], "chat": []}
    try:
        resp = client.search(
            index=index_name,
            body={"size": 3, "query": {"match_all": {}}},
            params={"search_pipeline": "_none"},
        )
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            return fallback

        # Collect field names and sample values
        field_samples: dict = {}
        for hit in hits:
            src = hit.get("_source", {})
            for key, val in src.items():
                if val is not None and not isinstance(val, (dict, list)):
                    sv = str(val).strip()
                    if sv and key not in field_samples and len(sv) < 100:
                        field_samples[key] = sv

        # Try LLM-based generation
        config = get_search_config(index_name)
        if not config:
            config = _introspect_search_config(client, index_name)
            set_search_config(index_name, config)

        agentic_model_id = config.get("agentic_model_id", "")
        if agentic_model_id:
            try:
                # Detect document-style index (has text + headings/section/chunk_id fields)
                all_source_keys: set = set()
                for hit in hits:
                    all_source_keys.update(hit.get("_source", {}).keys())
                is_document_index = "text" in all_source_keys and any(
                    k in all_source_keys for k in ("headings", "section", "chunk_id")
                )

                if is_document_index:
                    # For document indices: gather headings and text snippets
                    headings_set: set = set()
                    text_snippets: list = []
                    for hit in hits:
                        src = hit.get("_source", {})
                        hdgs = src.get("headings", [])
                        if isinstance(hdgs, list):
                            for h in hdgs:
                                if h and len(h) > 3:
                                    headings_set.add(h)
                        sect = src.get("section", "")
                        if sect and len(sect) > 3:
                            headings_set.add(sect)
                        txt = str(src.get("text", "")).strip()
                        if len(txt) > 30:
                            text_snippets.append(txt[:200])

                    # Fetch more docs to get diverse headings
                    try:
                        more_resp = client.search(
                            index=index_name,
                            body={"size": 15, "query": {"match_all": {}}, "_source": ["headings", "section", "text"]},
                            params={"search_pipeline": "_none"},
                        )
                        for hit in more_resp.get("hits", {}).get("hits", []):
                            src = hit.get("_source", {})
                            hdgs = src.get("headings", [])
                            if isinstance(hdgs, list):
                                for h in hdgs:
                                    if h and len(h) > 3:
                                        headings_set.add(h)
                            sect = src.get("section", "")
                            if sect and len(sect) > 3:
                                headings_set.add(sect)
                            txt = str(src.get("text", "")).strip()
                            if len(txt) > 30 and len(text_snippets) < 5:
                                text_snippets.append(txt[:200])
                    except Exception:
                        pass

                    headings_list = sorted(headings_set)[:15]
                    context_parts = []
                    if headings_list:
                        context_parts.append("Document sections/headings:\n" + "\n".join(f"- {h}" for h in headings_list))
                    if text_snippets:
                        context_parts.append("Sample text excerpts:\n" + "\n---\n".join(text_snippets[:3]))

                    prompt = (
                        f"This is a search index '{index_name}' containing text content from documents.\n\n"
                        f"{chr(10).join(context_parts)}\n\n"
                        "Generate exactly 4 SEARCH queries and 4 CHAT queries that a user would naturally ask about this content.\n\n"
                        "SEARCH queries: concise natural language questions targeting specific concepts or facts in the content.\n"
                        "CHAT queries: broader conversational questions that explore themes, ask for explanations, or request summaries.\n\n"
                        "All queries should be natural language questions a real user would type. "
                        "Derive them from the actual content provided above.\n\n"
                        'Return ONLY a JSON object: {"search": [...], "chat": [...]}\n'
                        "No explanation, just the JSON."
                    )
                else:
                    field_desc = "\n".join(
                        f"- {k}: {v}" for k, v in list(field_samples.items())[:10]
                    )
                    prompt = (
                        f"Given an OpenSearch index '{index_name}' with these fields and sample values:\n"
                        f"{field_desc}\n\n"
                        "Generate exactly 4 natural language SEARCH queries and 4 CHAT queries.\n\n"
                        "SEARCH queries: specific lookups that find particular items.\n"
                        "CHAT queries: conversational questions that explore the data or ask for recommendations.\n\n"
                        'Return ONLY a JSON object: {"search": [...], "chat": [...]}\n'
                        "No explanation, just the JSON."
                    )
                predict_body = {
                    "parameters": {
                        "system_prompt": "You generate example search queries. Return only valid JSON.",
                        "user_prompt": prompt,
                    }
                }
                llm_resp = client.transport.perform_request(
                    "POST",
                    f"/_plugins/_ml/models/{agentic_model_id}/_predict",
                    body=predict_body,
                )
                inference = llm_resp.get("inference_results", [{}])[0]
                output_data = inference.get("output", [{}])[0].get("dataAsMap", {})
                text = (
                    output_data.get("output", {})
                    .get("message", {})
                    .get("content", [{}])[0]
                    .get("text", "")
                )
                if text:
                    import json as _json

                    clean = text.strip()
                    if clean.startswith("```"):
                        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                    parsed = _json.loads(clean)
                    if isinstance(parsed.get("search"), list) and isinstance(
                        parsed.get("chat"), list
                    ):
                        result = {
                            "search": [str(s) for s in parsed["search"][:4]],
                            "chat": [str(s) for s in parsed["chat"][:4]],
                        }
                        _agent_prompts_cache[index_name] = (_time.time(), result)
                        return result
            except Exception:
                pass  # Fall through to heuristic

        # Heuristic fallback: build prompts from field names and values
        fields = list(field_samples.keys())
        search_prompts: list[str] = []
        chat_prompts: list[str] = []
        if fields:
            f0 = fields[0]
            v0 = field_samples.get(f0, "")
            search_prompts.append(f"Find items where {f0} is '{v0}'")
            if len(fields) > 1:
                search_prompts.append(f"Show me entries with specific {fields[1]}")
            search_prompts.append("Top rated items in this collection")
            search_prompts.append("Recent entries added to the index")

            chat_prompts.append(f"What types of {f0} are in this dataset?")
            chat_prompts.append("Summarize the most common categories")
            chat_prompts.append("What patterns do you see in the data?")
            chat_prompts.append("Recommend something interesting")

        result = {"search": search_prompts[:4], "chat": chat_prompts[:4]}
        _agent_prompts_cache[index_name] = (_time.time(), result)
        return result
    except Exception:
        return fallback


def _format_search_response(
    response: dict,
    query_mode: str,
    capability: str,
    used_semantic: bool,
    fallback_reason: str,
    query_body: dict | None = None,
) -> dict:
    hits_out: list[dict] = []
    for hit in response.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        clean_source = _strip_vector_fields(source)
        hits_out.append({
            "id": hit.get("_id"),
            "score": hit.get("_score"),
            "preview": preview_text(source),
            "source": clean_source,
        })
    result = {
        "error": "",
        "hits": hits_out,
        "total": response.get("hits", {}).get("total", {}).get("value", len(hits_out)),
        "took_ms": response.get("took", 0),
        "query_mode": query_mode,
        "capability": capability,
        "used_semantic": used_semantic,
        "fallback_reason": fallback_reason,
    }
    if query_body is not None:
        result["query_body"] = query_body

    # Extract agentic/RAG fields from response.ext
    ext = response.get("ext", {})
    if isinstance(ext, dict):
        if ext.get("memory_id"):
            result["memory_id"] = ext["memory_id"]
        if ext.get("agent_steps_summary"):
            result["agent_steps_summary"] = ext["agent_steps_summary"]
        if ext.get("dsl_query"):
            result["dsl_query"] = ext["dsl_query"]
        # RAG answer from retrieval_augmented_generation response processor
        rag_ext = ext.get("retrieval_augmented_generation", {})
        if isinstance(rag_ext, dict) and rag_ext.get("answer"):
            result["rag_answer"] = rag_ext["answer"]

    return result
