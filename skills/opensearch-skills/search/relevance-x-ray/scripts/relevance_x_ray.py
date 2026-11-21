#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["opensearch-py>=2.4"]
# ///
"""Self-contained, evidence-backed relevance diagnostics for OpenSearch.

Commands:
    preflight-check
    inspect-index --index NAME
    explain --index NAME --query TEXT_OR_JSON --doc-id ID
    suggest-synonyms --index NAME --query-term TERM --doc-id ID
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path

from opensearchpy.exceptions import OpenSearchException

_SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from relevance_xray_lib.client import (  # noqa: E402
    build_client,
    can_connect,
    connection_ssl_modes,
    preflight_check_cluster,
    resolve_http_auth,
)
from relevance_xray_lib.explain_parser import (  # noqa: E402
    ExplainSummary,
    parse_explain,
    to_plain_english,
)
from relevance_xray_lib.relevance_diagnostics import (  # noqa: E402
    build_knn_parameter_sweep,
    compact_hit_context,
    find_rank,
    flatten_mapping,
    inspect_query,
    mapped_text_fields,
    parse_query_input,
)
from relevance_xray_lib.report import build_diagnosis_report  # noqa: E402
from relevance_xray_lib.query_tuner import (  # noqa: E402
    load_judgments,
    normalize_judgments,
    propose_query_candidates,
    query_fingerprint,
    validate_query_candidates,
)
from relevance_xray_lib.rules_engine import (  # noqa: E402
    rule_coverage,
    run_all_rules,
)
from relevance_xray_lib.synonym_suggester import (  # noqa: E402
    fetch_document_term_lists,
    fetch_sample_document_ids,
    mine_candidate_synonyms,
    validate_synonym_candidate,
)

MAX_TOP_K = 100
MAX_SAMPLE_SIZE = 500
MAX_SYNONYM_FIELDS = 20
MAX_HYBRID_LEGS_TO_EXPLAIN = 10
SEARCH_TIMEOUT = "10s"
SEARCH_TERMINATE_AFTER = 10_000
_ALLOWED_SEARCH_BODY_KEYS = frozenset({"query", "runtime_mappings"})


def _safe_error(exc: Exception) -> str:
    """Describe a cluster failure without echoing its response body."""
    status = getattr(exc, "status_code", None)
    suffix = f" (HTTP {status})" if status is not None else ""
    return f"{type(exc).__name__}{suffix}"


def _validate_concrete_index(index: str) -> None:
    if not str(index or "").strip():
        raise ValueError("A concrete index name is required.")
    if any(token in index for token in ("*", "?", ",")):
        raise ValueError(
            "Wildcard and multi-index expressions are not allowed; provide one "
            "concrete index name."
        )


def _unsupported_search_keys(body: dict) -> list[str]:
    return sorted(set(body) - _ALLOWED_SEARCH_BODY_KEYS)


def _redact_raw_response(value, *, _depth: int = 0, max_depth: int = 50):
    """Remove document content before emitting diagnostic JSON."""
    if _depth >= max_depth:
        return "<truncated>"
    if isinstance(value, list):
        return [
            _redact_raw_response(item, _depth=_depth + 1, max_depth=max_depth)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    return {
        key: _redact_raw_response(
            item,
            _depth=_depth + 1,
            max_depth=max_depth,
        )
        for key, item in value.items()
        if key not in {"_source", "fields", "highlight"}
    }


def _can_retry_without_per_hit_explain(exc: Exception) -> bool:
    """Only retry when the cluster rejects explain syntax, never on timeout/5xx."""
    return getattr(exc, "status_code", None) == 400


def _preflight_result(args) -> dict:
    return preflight_check_cluster(
        auth_mode=getattr(args, "auth_mode", "") or "",
        username=getattr(args, "username", "") or "",
        password=os.getenv("OPENSEARCH_PASSWORD", ""),
    )


def _checked_client(args):
    """Preflight in this process so diagnostic commands never bootstrap Docker."""
    result = _preflight_result(args)
    if result.get("status") != "available":
        raise RuntimeError(result.get("message") or "OpenSearch preflight failed.")
    http_auth = resolve_http_auth()
    for use_ssl in connection_ssl_modes(http_auth, host=result.get("host")):
        client = build_client(use_ssl=use_ssl, http_auth=http_auth)
        connected, _ = can_connect(client)
        if connected:
            return client
    raise RuntimeError(
        "OpenSearch became unavailable after preflight; no diagnostic request was sent."
    )


def _index_context(client, index: str) -> tuple[dict, dict, dict]:
    _validate_concrete_index(index)
    mapping_response = client.indices.get_mapping(index=index)
    settings_response = client.indices.get_settings(index=index)
    if len(mapping_response) != 1:
        raise RuntimeError(
            f"Index expression '{index}' resolved to {len(mapping_response)} indices; "
            "provide one concrete index so scores and mappings are unambiguous."
        )
    concrete_index = next(iter(mapping_response))
    properties = (
        mapping_response[concrete_index].get("mappings", {}).get("properties", {})
    )
    return mapping_response, settings_response, properties


def _search(
    client,
    index: str,
    body: dict,
    top_k: int,
    search_pipeline: str = "",
    explain: bool = False,
) -> dict:
    _validate_concrete_index(index)
    if not 1 <= top_k <= MAX_TOP_K:
        raise ValueError(f"top_k must be between 1 and {MAX_TOP_K}.")
    request = {
        key: copy.deepcopy(body[key])
        for key in _ALLOWED_SEARCH_BODY_KEYS
        if key in body
    }
    if not isinstance(request.get("query"), dict):
        raise ValueError("A search diagnosis requires a query object.")
    request["size"] = top_k
    request["from"] = 0
    request["explain"] = explain
    request["_source"] = False
    request["track_total_hits"] = False
    request["timeout"] = SEARCH_TIMEOUT
    request["terminate_after"] = SEARCH_TERMINATE_AFTER
    params = {"search_pipeline": search_pipeline} if search_pipeline else None
    kwargs = {"index": index, "body": request, "request_timeout": 15}
    if params:
        kwargs["params"] = params
    return client.search(**kwargs)


def _hits(response: dict) -> list[dict]:
    return response.get("hits", {}).get("hits", []) or []


def _analyze(client, index: str, analyzer: str, text: str) -> list[str]:
    response = client.indices.analyze(
        index=index,
        body={"analyzer": analyzer, "text": text},
    )
    return [
        str(token.get("token", ""))
        for token in response.get("tokens", [])
        if token.get("token")
    ]


def _analyze_field(client, index: str, field_name: str, text: str) -> list[str]:
    response = client.indices.analyze(
        index=index,
        body={"field": field_name, "text": text},
    )
    return [
        str(token.get("token", ""))
        for token in response.get("tokens", [])
        if token.get("token")
    ]


def _build_analyzer_evidence(
    client,
    index: str,
    doc_id: str,
    metadata,
    mapping_properties: dict,
) -> tuple[dict, list[str]]:
    """Use configured analyzers and target term vectors; never infer by spelling."""
    flattened = flatten_mapping(mapping_properties)
    candidate_fields = sorted(
        field_name.split("^", 1)[0]
        for field_name in metadata.query_fields
        if field_name.split("^", 1)[0] in flattened
    )
    comparable_fields = [
        field_name
        for field_name in candidate_fields
        if flattened[field_name].get("search_analyzer")
        and (
            not flattened[field_name].get("analyzer")
            or flattened[field_name].get("search_analyzer")
            != flattened[field_name].get("analyzer")
        )
    ]
    if not comparable_fields:
        return {}, []

    limitations: list[str] = []
    try:
        term_vectors = client.termvectors(
            index=index,
            id=doc_id,
            body={
                "fields": comparable_fields,
                "field_statistics": False,
                "term_statistics": False,
                "positions": False,
                "offsets": False,
                "payloads": False,
            },
        ).get("term_vectors", {})
    except OpenSearchException as exc:
        return {}, [
            "Analyzer comparison skipped because term vectors failed: "
            f"{_safe_error(exc)}"
        ]

    evidence: dict = {}
    for field_name in comparable_fields:
        spec = flattened[field_name]
        query_values = metadata.field_queries.get(field_name) or metadata.query_terms
        query_text = " ".join(query_values).strip()
        if not query_text:
            continue
        search_analyzer = spec["search_analyzer"]
        try:
            evidence[field_name] = {
                "index_tokens": _analyze_field(client, index, field_name, query_text),
                "search_tokens": _analyze(client, index, search_analyzer, query_text),
                "target_tokens": sorted(
                    (term_vectors.get(field_name, {}).get("terms") or {}).keys()
                ),
            }
        except OpenSearchException as exc:
            limitations.append(
                f"Analyzer comparison for field '{field_name}' failed: "
                f"{_safe_error(exc)}"
            )
    return evidence, limitations


def _explain_target(client, index: str, doc_id: str, query: dict) -> ExplainSummary:
    response = client.explain(index=index, id=doc_id, body={"query": query})
    return parse_explain(
        response.get("explanation") or {},
        doc_matched=response.get("matched"),
    )


def cmd_preflight_check(args) -> None:
    result = _preflight_result(args)
    print(json.dumps(result, indent=2))
    if result.get("status") != "available":
        raise RuntimeError(result.get("message") or "OpenSearch preflight failed.")


def cmd_inspect_index(args) -> None:
    client = _checked_client(args)
    mapping, settings, _ = _index_context(client, args.index)
    print(json.dumps({"mapping": mapping, "settings": settings}, indent=2))


def cmd_explain(args) -> None:
    client = _checked_client(args)
    mapping_response, _, mapping_properties = _index_context(client, args.index)
    search_body, plain_query = parse_query_input(args.query, mapping_properties)
    query = search_body["query"]
    metadata = inspect_query(query)
    limitations: list[str] = []
    unsupported_keys = _unsupported_search_keys(search_body)
    if unsupported_keys:
        limitations.append(
            "Unsupported search-body keys were not executed: "
            + ", ".join(unsupported_keys)
            + ". The diagnosis covers the query clause only."
        )

    try:
        search_response = _search(
            client,
            args.index,
            search_body,
            args.top_k,
            args.search_pipeline,
            explain=True,
        )
    except OpenSearchException as exc:
        if not _can_retry_without_per_hit_explain(exc):
            raise
        limitations.append(
            "Per-hit search explanations were rejected by the cluster: "
            f"{_safe_error(exc)}"
        )
        search_response = _search(
            client,
            args.index,
            search_body,
            args.top_k,
            args.search_pipeline,
            explain=False,
        )

    hits = _hits(search_response)
    target_rank = find_rank(hits, args.doc_id)
    target_hit = next(
        (hit for hit in hits if str(hit.get("_id")) == str(args.doc_id)),
        None,
    )

    leg_summaries: dict[str, ExplainSummary] = {}
    if metadata.hybrid_legs:
        legs_to_explain = metadata.hybrid_legs[:MAX_HYBRID_LEGS_TO_EXPLAIN]
        if len(metadata.hybrid_legs) > len(legs_to_explain):
            limitations.append(
                f"Only the first {MAX_HYBRID_LEGS_TO_EXPLAIN} of "
                f"{len(metadata.hybrid_legs)} hybrid legs were explained."
            )
        for index, leg_query in enumerate(legs_to_explain, start=1):
            try:
                leg_summaries[f"hybrid-leg-{index}"] = _explain_target(
                    client, args.index, args.doc_id, leg_query
                )
            except OpenSearchException as exc:
                limitations.append(
                    f"Hybrid leg {index} could not be explained: {_safe_error(exc)}"
                )
        limitations.append(
            "Raw hybrid leg scores are not compared with pipeline weights because "
            "normalization is computed across the result set."
        )

    if target_hit and target_hit.get("_explanation"):
        summary = parse_explain(target_hit["_explanation"], doc_matched=True)
    elif args.search_pipeline and not metadata.hybrid_legs:
        limitations.append(
            "The target was outside the explained result window and the search "
            "pipeline's rewritten query is unavailable to _explain."
        )
        summary = ExplainSummary(
            total_score=float(target_hit.get("_score") or 0.0) if target_hit else 0.0,
            matched=bool(target_hit),
            match_known=False,
        )
    elif not metadata.hybrid_legs:
        summary = _explain_target(client, args.index, args.doc_id, query)
    else:
        summary = ExplainSummary(
            total_score=float(target_hit.get("_score") or 0.0) if target_hit else 0.0,
            matched=bool(target_hit),
            match_known=bool(target_hit),
        )
    if summary.traversal_truncated:
        limitations.append(
            "The explain tree exceeded the supported depth and was truncated."
        )

    analyzer_evidence, analyzer_limitations = _build_analyzer_evidence(
        client,
        args.index,
        args.doc_id,
        metadata,
        mapping_properties,
    )
    limitations.extend(analyzer_limitations)

    knn_counterfactual = None
    if metadata.has_knn and not args.skip_knn_validation:
        try:
            swept_query, before_params, after_params = build_knn_parameter_sweep(query)
            if swept_query is None:
                limitations.append(
                    "k-NN recall was not evaluated because the query has no explicit "
                    "ef_search parameter to sweep while holding k constant."
                )
            else:
                swept_body = copy.deepcopy(search_body)
                swept_body["query"] = swept_query
                swept_hits = _hits(
                    _search(
                        client,
                        args.index,
                        swept_body,
                        args.top_k,
                        args.search_pipeline,
                        explain=False,
                    )
                )
                knn_counterfactual = {
                    "before_rank": target_rank,
                    "after_rank": find_rank(swept_hits, args.doc_id),
                    "before_params": before_params,
                    "after_params": after_params,
                }
                before_rank = knn_counterfactual["before_rank"]
                after_rank = knn_counterfactual["after_rank"]
                if after_rank is None or (
                    before_rank is not None and after_rank >= before_rank
                ):
                    limitations.append(
                        "Increasing ef_search while holding k constant did not improve "
                        "the target rank, so weak approximate recall was not established."
                    )
        except OpenSearchException as exc:
            limitations.append(
                "The optional k-NN parameter sweep failed and was skipped: "
                f"{_safe_error(exc)}"
            )

    concrete_index = next(iter(mapping_response))
    mapping_fields = flatten_mapping(mapping_properties)
    mapping_fields.update(
        mapping_response[concrete_index].get("mappings", {}).get("runtime", {})
    )
    mapping_fields.update(search_body.get("runtime_mappings") or {})
    context = {
        "mapping_properties": mapping_fields,
        "filter_or_exact_fields": sorted(metadata.exact_fields),
        "referenced_fields": sorted(metadata.referenced_fields),
        "analysis_by_field": analyzer_evidence,
        "summary": summary,
        "query_terms": metadata.query_terms,
        "knn_counterfactual": knn_counterfactual,
    }
    findings = run_all_rules(context)
    evaluated_rules, skipped_rules = rule_coverage(context)
    hit_context = compact_hit_context(hits)
    for item, hit in zip(hit_context, hits):
        explanation = hit.get("_explanation")
        if explanation:
            parsed_hit = parse_explain(explanation, doc_matched=True)
            if parsed_hit.traversal_truncated:
                limitations.append(
                    f"Explain evidence for hit '{item['id']}' was truncated at the "
                    "supported depth."
                )
            lines = to_plain_english(parsed_hit)
            if lines:
                item["score_evidence"] = lines[0]
    competitor_context = [
        item for item in hit_context if item["id"] != str(args.doc_id)
    ]

    if metadata.hybrid_legs:
        limitations.append(
            "Hybrid imbalance was not evaluated because normalized per-leg "
            "contributions are not exposed by this request."
        )
    if not metadata.query_terms and plain_query is None:
        limitations.append(
            "Vocabulary diagnostics were not evaluated because no textual query "
            "terms could be extracted from the DSL."
        )

    report = build_diagnosis_report(
        index=args.index,
        query_text=args.query,
        doc_id=args.doc_id,
        summary=summary,
        findings=findings,
        search_context={
            "target_rank": target_rank,
            "top_k": args.top_k,
            "top_hits": competitor_context,
        },
        evaluated_rules=evaluated_rules,
        skipped_rules=skipped_rules,
        limitations=limitations,
        leg_summaries=leg_summaries,
    )
    print(report)

    if args.raw:
        print("\nRAW SEARCH RESPONSE")
        print("-" * 72)
        print(json.dumps(_redact_raw_response(search_response), indent=2))


def _synonym_search_fn(fields: list[str], top_k: int):
    def search_fn(client, index: str, query_text: str) -> list[str]:
        response = _search(
            client,
            index,
            {
                "query": {
                    "multi_match": {
                        "query": query_text,
                        "fields": fields,
                        "operator": "or",
                    },
                }
            },
            top_k,
            explain=False,
        )
        return [str(hit.get("_id")) for hit in _hits(response)]

    return search_fn


def cmd_suggest_synonyms(args) -> None:
    client = _checked_client(args)
    _, _, mapping_properties = _index_context(client, args.index)
    available_fields = mapped_text_fields(mapping_properties)
    requested_fields = (
        [field.strip() for field in args.fields.split(",") if field.strip()]
        if args.fields
        else []
    )
    if len(requested_fields) > MAX_SYNONYM_FIELDS:
        raise ValueError(
            f"At most {MAX_SYNONYM_FIELDS} synonym fields may be requested."
        )
    fields = requested_fields or available_fields[:MAX_SYNONYM_FIELDS]
    if not requested_fields and len(available_fields) > len(fields):
        print(
            f"Auto-selected the first {MAX_SYNONYM_FIELDS} of "
            f"{len(available_fields)} mapped text fields."
        )
    unknown_fields = sorted(set(fields) - set(available_fields))
    if unknown_fields:
        raise ValueError(f"Synonym fields are not mapped text fields: {unknown_fields}")
    if not fields:
        raise ValueError("No text fields are available for synonym mining.")

    document_ids = fetch_sample_document_ids(
        client,
        args.index,
        size=args.sample_size,
    )
    corpus_term_lists = fetch_document_term_lists(
        client,
        args.index,
        document_ids,
        fields,
    )
    target_terms = fetch_document_term_lists(
        client,
        args.index,
        [str(args.doc_id)],
        fields,
    )[0]

    candidates = mine_candidate_synonyms(
        query_term=args.query_term,
        target_doc_terms=target_terms,
        corpus_term_lists=corpus_term_lists,
        min_support=args.min_support,
        min_neighborhood_documents=5,
    )
    if not candidates:
        print(
            f"No corpus-supported candidate was found for '{args.query_term}' "
            f"in the {len(document_ids)} sampled documents. At least five sampled "
            "documents containing the query term are required."
        )
        return

    search_fn = _synonym_search_fn(fields, args.top_k)
    supported: list[tuple] = []
    rejected: list[tuple] = []
    for candidate in candidates:
        validation = validate_synonym_candidate(
            client,
            args.index,
            args.query_term,
            candidate,
            target_doc_id=str(args.doc_id),
            search_fn=search_fn,
        )
        item = (candidate, validation)
        (supported if validation.get("improved") else rejected).append(item)

    print(
        "Validation method: non-mutating query expansion using "
        "multi_match(operator=or), "
        f"fields={fields}, top_k={args.top_k}"
    )
    if supported:
        print(f"Rank-improving expansion candidates for '{args.query_term}':")
        for candidate, validation in supported:
            print(
                f"  - '{candidate.candidate}': support_docs={candidate.support}, "
                f"P(candidate|query)={candidate.confidence:.3f}, "
                f"jaccard={candidate.association:.3f}, "
                f"rank={validation['before_rank']}->{validation['after_rank']}"
            )
    else:
        print(
            "No candidate improved the target rank; no query expansion or synonym "
            "experiment is recommended."
        )
    if rejected:
        print("Rejected after rank validation:")
        for candidate, validation in rejected:
            print(
                f"  - '{candidate.candidate}': "
                f"rank={validation['before_rank']}->{validation['after_rank']}"
            )


def cmd_tune_query(args) -> None:
    """Generate small query candidates and retain only measured improvements."""
    client = _checked_client(args)
    _, _, mapping_properties = _index_context(client, args.index)
    search_body, _ = parse_query_input(args.query, mapping_properties)
    unsupported_keys = _unsupported_search_keys(search_body)
    if unsupported_keys:
        raise ValueError(
            "Query tuning does not execute unsupported search-body keys: "
            + ", ".join(unsupported_keys)
        )
    fingerprint = query_fingerprint(search_body)
    judgments = normalize_judgments(
        load_judgments(args.judgments_file),
        fingerprint,
    )
    if not judgments:
        raise ValueError(
            "No usable pairwise judgments match this exact baseline query."
        )

    documents: dict[str, dict] = {}
    document_ids = {
        doc_id
        for judgment in judgments
        for doc_id in (
            judgment["preferred_doc_id"],
            judgment["rejected_doc_id"],
        )
    }
    for doc_id in sorted(document_ids):
        response = client.get(index=args.index, id=doc_id)
        documents[doc_id] = response.get("_source") or {}

    candidates = propose_query_candidates(
        search_body,
        judgments,
        documents,
        mapping_properties,
    )

    def search_fn(candidate_body: dict) -> list[dict]:
        response = _search(
            client,
            args.index,
            candidate_body,
            args.top_k,
            explain=False,
        )
        return _hits(response)

    result = validate_query_candidates(
        search_body,
        candidates,
        judgments,
        search_fn,
    )
    print(json.dumps(result, indent=2))


def _add_connection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--auth-mode",
        choices=["none", "default", "custom"],
        default="",
        help="Authentication mode; omit to auto-detect.",
    )
    parser.add_argument("--username", default="")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_preflight = sub.add_parser("preflight-check", help="Probe cluster connectivity")
    _add_connection_arguments(p_preflight)
    p_preflight.set_defaults(func=cmd_preflight_check)

    p_inspect = sub.add_parser(
        "inspect-index",
        help="Dump mapping/settings for one concrete index",
    )
    p_inspect.add_argument("--index", required=True)
    _add_connection_arguments(p_inspect)
    p_inspect.set_defaults(func=cmd_inspect_index)

    p_explain = sub.add_parser(
        "explain",
        help="Run the actual search and explain one target document",
    )
    p_explain.add_argument("--index", required=True)
    p_explain.add_argument(
        "--query",
        required=True,
        help="Plain text, a query clause, or a complete JSON search body",
    )
    p_explain.add_argument("--doc-id", required=True)
    p_explain.add_argument("--top-k", type=int, default=10)
    p_explain.add_argument("--search-pipeline", default="")
    p_explain.add_argument("--skip-knn-validation", action="store_true")
    p_explain.add_argument(
        "--raw",
        action="store_true",
        help="Also print the raw search response",
    )
    _add_connection_arguments(p_explain)
    p_explain.set_defaults(func=cmd_explain)

    p_syn = sub.add_parser(
        "suggest-synonyms",
        help="Mine candidates and retain only measured rank improvements",
    )
    p_syn.add_argument("--index", required=True)
    p_syn.add_argument("--query-term", required=True)
    p_syn.add_argument("--doc-id", required=True)
    p_syn.add_argument(
        "--fields",
        default="",
        help=(
            "Comma-separated mapped text fields; defaults to the first "
            f"{MAX_SYNONYM_FIELDS} text fields."
        ),
    )
    p_syn.add_argument("--sample-size", type=int, default=200)
    p_syn.add_argument("--min-support", type=int, default=2)
    p_syn.add_argument("--top-k", type=int, default=20)
    _add_connection_arguments(p_syn)
    p_syn.set_defaults(func=cmd_suggest_synonyms)

    p_tune = sub.add_parser(
        "tune-query",
        help="Propose and rank-validate small query changes from pairwise judgments",
    )
    p_tune.add_argument("--index", required=True)
    p_tune.add_argument(
        "--query",
        required=True,
        help="A query clause or complete JSON search body used as the immutable baseline",
    )
    p_tune.add_argument("--judgments-file", required=True)
    p_tune.add_argument("--top-k", type=int, default=20)
    _add_connection_arguments(p_tune)
    p_tune.set_defaults(func=cmd_tune_query)

    args = parser.parse_args()
    top_k = getattr(args, "top_k", 1)
    if top_k < 1 or top_k > MAX_TOP_K:
        parser.error(f"--top-k must be between 1 and {MAX_TOP_K}")
    sample_size = getattr(args, "sample_size", 1)
    if sample_size < 1 or sample_size > MAX_SAMPLE_SIZE:
        parser.error(f"--sample-size must be between 1 and {MAX_SAMPLE_SIZE}")
    if getattr(args, "min_support", 1) < 1:
        parser.error("--min-support must be at least 1")
    try:
        args.func(args)
    except OpenSearchException as exc:
        print(f"Error: OpenSearch request failed: {_safe_error(exc)}", file=sys.stderr)
        sys.exit(1)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
