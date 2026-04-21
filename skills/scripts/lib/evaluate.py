"""Search quality evaluation engine.

General-purpose evaluation that accepts any number of search methods
and test queries with graded relevance judgments. Computes nDCG, P@k,
MRR metrics and produces actionable diagnostic findings.

The engine is method-agnostic: callers provide pre-computed search results
keyed by method name. Optional method tags ("lexical", "vector", "hybrid")
enable more specific diagnosis when available.

Usage as library:
    from lib.evaluate import evaluate_results, compute_query_metrics, format_report
"""

import math
from collections import defaultdict

# -- Visual helpers ------------------------------------------------------------

GRADE_LABELS = {3: "perfect", 2: "relevant", 1: "marginal", 0: ""}


def star_rating(score):
    if score >= 1.0:  return "★★★★★"
    if score >= 0.75: return "★★★★☆"
    if score >= 0.50: return "★★★☆☆"
    if score >= 0.25: return "★★☆☆☆"
    if score > 0:     return "★☆☆☆☆"
    return "✗ 0.00"


def bar(score, width=10):
    filled = round(score * width)
    return "█" * filled + "░" * (width - filled)


# -- Metrics -------------------------------------------------------------------

def dcg(relevances, k):
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevances[:k]))


def ndcg(relevances, ideal_relevances, k):
    ideal = dcg(sorted(ideal_relevances, reverse=True), k)
    return dcg(relevances, k) / ideal if ideal > 0 else 0.0


def precision_at_k(relevances, k):
    return sum(1 for r in relevances[:k] if r > 0) / k


def mrr(relevances):
    for i, r in enumerate(relevances):
        if r > 0:
            return 1.0 / (i + 1)
    return 0.0


# -- Query-level processing ----------------------------------------------------

def compute_query_metrics(results, relevance_map, title_field, k):
    """Compute metrics for a single query's search results.

    Args:
        results: OpenSearch search response dict.
        relevance_map: {document_title: relevance_grade}.
        title_field: Field name to extract document title from _source.
        k: Cutoff depth.

    Returns:
        dict with ndcg, p@k, mrr, rels, titles.
    """
    hits = results["hits"]["hits"][:k]
    titles = [h["_source"].get(title_field, h["_id"]) for h in hits]
    doc_ids = [h.get("_id", "") for h in hits]
    scores = [h.get("_score") for h in hits]
    rels = [relevance_map.get(t, 0) for t in titles]
    ideal_rels = list(relevance_map.values())
    # Per-position DCG contribution: rel_i / log2(i+2)
    dcg_contribs = [rel / math.log2(i + 2) for i, rel in enumerate(rels)]
    return {
        "ndcg": ndcg(rels, ideal_rels, k),
        "p@k": precision_at_k(rels, k),
        "mrr": mrr(rels),
        "rels": rels,
        "titles": titles,
        "doc_ids": doc_ids,
        "scores": scores,
        "dcg_contribs": dcg_contribs,
    }


# -- Diagnosis -----------------------------------------------------------------

_LEXICAL_TAGS = {"lexical", "bm25"}
_VECTOR_TAGS = {"vector", "knn", "sparse"}
_HYBRID_TAGS = {"hybrid", "combined"}


def _classify_methods(method_names, method_tags):
    """Classify methods into lexical, vector, hybrid, and untagged groups."""
    tags = method_tags or {}
    lexical = [m for m in method_names if tags.get(m) in _LEXICAL_TAGS]
    vector = [m for m in method_names if tags.get(m) in _VECTOR_TAGS]
    hybrid = [m for m in method_names if tags.get(m) in _HYBRID_TAGS]
    untagged = [m for m in method_names if m not in lexical + vector + hybrid]
    return lexical, vector, hybrid, untagged


def diagnose_query(test, metrics_by_method, k, method_tags=None, embedded_fields=""):
    """Diagnose issues for a single query across all methods.

    Args:
        test: Test case dict with name, type, query, relevance.
        metrics_by_method: {method_name: metrics_dict} for this query.
        k: Cutoff used for metrics.
        method_tags: Optional {method_name: category} for smarter diagnosis.
            Recognised categories: "lexical", "bm25", "vector", "knn",
            "sparse", "hybrid", "combined".
        embedded_fields: Description of embedded fields (for messages).

    Returns:
        List of (tag, severity, message) tuples.
    """
    findings = []
    method_names = list(metrics_by_method.keys())
    if not method_names:
        return findings

    qtype = test.get("type", "")
    query = test.get("query", "")
    relevance = test.get("relevance", {})
    lexical, vector, hybrid, untagged = _classify_methods(method_names, method_tags)

    # Rule 1: All methods fail (nDCG < 0.3)
    if all(metrics_by_method[m]["ndcg"] < 0.3 for m in method_names):
        if qtype == "semantic":
            findings.append(("[MODEL_SELECTION]", "HIGH",
                f"All methods nDCG<0.30 for '{query}'. "
                f"The model cannot bridge the semantic gap. "
                f"Upgrade to a larger model or enrich documents with topic tags."))
        elif qtype == "combined":
            findings.append(("[INDEX_MAPPING]", "HIGH",
                f"All methods nDCG<0.30 for '{query}'. "
                f"Possible field type or mapping issue. "
                f"Check that relevant fields have proper analyzers and keyword sub-fields."))
        else:
            findings.append(("[INDEX_MAPPING]", "HIGH",
                f"All methods nDCG<0.30 for '{query}' (type={qtype}). "
                f"No method can retrieve relevant documents."))
        return findings  # skip remaining rules when everything fails

    # Rule 2: Pairwise method gaps (tag-aware)
    # Vector fails but lexical succeeds -> model issue
    for vm in vector:
        if metrics_by_method[vm]["ndcg"] >= 0.3:
            continue
        for lm in lexical:
            if metrics_by_method[lm]["ndcg"] > 0.5:
                findings.append(("[MODEL_SELECTION]", "MEDIUM",
                    f"{vm} nDCG={metrics_by_method[vm]['ndcg']:.2f} vs "
                    f"{lm} nDCG={metrics_by_method[lm]['ndcg']:.2f}. "
                    f"Embedding model cannot capture semantics that keyword matching handles."))
                break
    # Lexical fails but vector succeeds -> analyzer / field issue
    for lm in lexical:
        if metrics_by_method[lm]["ndcg"] >= 0.3:
            continue
        for vm in vector:
            if metrics_by_method[vm]["ndcg"] > 0.5:
                findings.append(("[INDEX_MAPPING]", "MEDIUM",
                    f"{lm} nDCG={metrics_by_method[lm]['ndcg']:.2f} vs "
                    f"{vm} nDCG={metrics_by_method[vm]['ndcg']:.2f}. "
                    f"Text fields may lack proper analyzers or boosting."))
                break
    # Generic pairwise: large gap between any two untagged methods
    for i, m1 in enumerate(untagged):
        for m2 in untagged[i + 1:]:
            n1 = metrics_by_method[m1]["ndcg"]
            n2 = metrics_by_method[m2]["ndcg"]
            if abs(n1 - n2) > 0.3:
                weak, strong = (m1, m2) if n1 < n2 else (m2, m1)
                findings.append(("[QUERY_TUNING]", "MEDIUM",
                    f"{weak} nDCG={metrics_by_method[weak]['ndcg']:.2f} vs "
                    f"{strong} nDCG={metrics_by_method[strong]['ndcg']:.2f}. "
                    f"Significant quality gap between methods."))

    # Rule 3: Hybrid/combined worse than best single-signal method
    single_methods = lexical + vector + untagged
    if single_methods and hybrid:
        best_single_ndcg = max(metrics_by_method[m]["ndcg"] for m in single_methods)
        best_single_name = max(single_methods, key=lambda m: metrics_by_method[m]["ndcg"])
        for hm in hybrid:
            gap = best_single_ndcg - metrics_by_method[hm]["ndcg"]
            if gap > 0.15:
                best_lex = max((metrics_by_method[m]["ndcg"] for m in lexical), default=0)
                best_vec = max((metrics_by_method[m]["ndcg"] for m in vector), default=0)
                if best_lex > best_vec:
                    findings.append(("[SEARCH_PIPELINE]", "MEDIUM",
                        f"{hm} nDCG={metrics_by_method[hm]['ndcg']:.2f} < "
                        f"{best_single_name} nDCG={best_single_ndcg:.2f}. "
                        f"Vector signal may be hurting results. "
                        f"Consider adjusting weights or query-type-aware routing."))
                else:
                    findings.append(("[SEARCH_PIPELINE]", "LOW",
                        f"{hm} nDCG={metrics_by_method[hm]['ndcg']:.2f} < "
                        f"{best_single_name} nDCG={best_single_ndcg:.2f}. "
                        f"Lexical noise may be pulling irrelevant keyword matches."))

    # Rule 4: Irrelevant doc in top-2 of any method
    for m in method_names:
        mm = metrics_by_method[m]
        if mm["rels"][:2].count(0) == 0 or mm["ndcg"] >= 0.8:
            continue
        irrelevant_top2 = [t for t, r in zip(mm["titles"][:2], mm["rels"][:2]) if r == 0]
        if not irrelevant_top2:
            continue
        other_methods = [om for om in method_names if om != m]
        doc_title = irrelevant_top2[0]
        if not other_methods:
            findings.append(("[QUERY_TUNING]", "MEDIUM",
                f"Irrelevant doc '{doc_title[:45]}' in top-2 of {m}. "
                f"Reduce field boost or restructure query."))
        else:
            in_others = [om for om in other_methods
                         if doc_title in set(metrics_by_method[om]["titles"][:3])]
            not_in_others = [om for om in other_methods
                             if doc_title not in set(metrics_by_method[om]["titles"][:3])]
            if not_in_others and in_others:
                findings.append(("[QUERY_TUNING]", "MEDIUM",
                    f"Irrelevant doc '{doc_title[:45]}' in top-2 of {m}. "
                    f"Also in {', '.join(in_others)} but not {', '.join(not_in_others)}. "
                    f"Reduce field boost or restructure query for {m}."))
            elif not_in_others:
                findings.append(("[QUERY_TUNING]", "MEDIUM",
                    f"Irrelevant doc '{doc_title[:45]}' in top-2 of {m} only. "
                    f"Noise specific to this method's retrieval signal."))
            elif in_others:
                findings.append(("[MODEL_SELECTION]", "LOW",
                    f"Irrelevant doc '{doc_title[:45]}' in top-2 of {m} "
                    f"(also in {', '.join(in_others)}). "
                    f"Document is broadly similar; a more capable model may help."))

    # Rule 5: Relevant docs missing from all methods' top-k
    all_returned = set()
    for m in method_names:
        all_returned.update(metrics_by_method[m]["titles"])
    missed = [t for t, r in relevance.items() if r >= 2 and t not in all_returned]
    if missed:
        fields_note = f" Embedded fields: {embedded_fields}." if embedded_fields else ""
        findings.append(("[MODEL_SELECTION]", "LOW",
            f"High-relevance docs not in any top-{k}: {', '.join(missed[:3])}.{fields_note} "
            f"Model capacity limitation."))

    return findings


# -- Evaluation engine ---------------------------------------------------------

def evaluate_results(tests, results_by_method, k=5, title_field="title",
                     method_tags=None, embedded_fields=""):
    """Evaluate search quality across multiple methods and test queries.

    Args:
        tests: [{"name", "type", "query", "relevance": {title: grade}}].
        results_by_method: {method_name: [opensearch_response_per_test]}.
            Each response is a standard OpenSearch search response dict.
        k: Cutoff depth for metrics.
        title_field: Field in _source to match against relevance judgments.
        method_tags: Optional {method_name: category} for smarter diagnosis.
            Recognised categories: "lexical"/"bm25", "vector"/"knn"/"sparse",
            "hybrid"/"combined".
        embedded_fields: Description of embedded fields (for diagnosis messages).

    Returns:
        dict with keys: methods, tests, metrics, findings, summary, k.
    """
    method_names = list(results_by_method.keys())
    all_metrics = {m: [] for m in method_names}
    all_findings = []

    for i, test in enumerate(tests):
        metrics_by_method = {}
        for method in method_names:
            response = results_by_method[method][i]
            m = compute_query_metrics(response, test["relevance"], title_field, k)
            metrics_by_method[method] = m
            all_metrics[method].append(m)

        findings = diagnose_query(test, metrics_by_method, k, method_tags, embedded_fields)
        if findings:
            all_findings.append((test["name"], findings))

    summary = {}
    for method in method_names:
        metrics = all_metrics[method]
        n = len(metrics)
        summary[method] = {
            "mean_ndcg": sum(m["ndcg"] for m in metrics) / n,
            "mean_pk": sum(m["p@k"] for m in metrics) / n,
            "mean_mrr": sum(m["mrr"] for m in metrics) / n,
        }

    return {
        "methods": method_names,
        "tests": tests,
        "metrics": all_metrics,
        "findings": all_findings,
        "summary": summary,
        "k": k,
    }


# -- Output formatting ---------------------------------------------------------

W = 90


def format_header(config, k, num_tests, method_names):
    lines = [
        f"\n{'=' * W}",
        f"  SEARCH QUALITY EVALUATION",
        f"  Index: {config.get('index', '?')}  |  Methods: {', '.join(method_names)}  |  k={k}  |  {num_tests} queries",
        f"{'=' * W}",
    ]
    return "\n".join(lines)


def format_query_results(test, metrics_by_method, k):
    method_names = list(metrics_by_method.keys())
    relevance = test.get("relevance", {})
    lines = [
        f"\n{'-' * W}",
        f"  {test['name']}  ({test.get('type', '')})",
        f"  Query: \"{test['query']}\"",
        f"  Relevance: " + ", ".join(
            f"{t} [{GRADE_LABELS.get(g, '')}={g}]"
            for t, g in sorted(relevance.items(), key=lambda x: -x[1])
        ) if relevance else "  Relevance: (none)",
        f"{'-' * W}",
    ]

    for method in method_names:
        m = metrics_by_method[method]
        stars = star_rating(m["ndcg"])
        ideal_dcg_val = dcg(sorted(test["relevance"].values(), reverse=True), k)
        actual_dcg_val = sum(m.get("dcg_contribs", []))
        lines.append(f"\n  {method}  {stars}  nDCG={m['ndcg']:.2f}  P@{k}={m['p@k']:.2f}  MRR={m['mrr']:.2f}")
        lines.append(f"  nDCG = DCG / iDCG = {actual_dcg_val:.3f} / {ideal_dcg_val:.3f}" if ideal_dcg_val > 0
                      else f"  nDCG = 0 (no relevant docs defined)")
        lines.append(f"  {'':4s}{'#':>2s}  {'Doc ID':<16s} {'Document':<36s} {'_score':>7s} {'Rel':>3s} {'DCG_i':>7s}  Label")
        lines.append(f"  {'':4s}{'-' * 82}")
        doc_ids = m.get("doc_ids", [""] * len(m["titles"]))
        os_scores = m.get("scores", [None] * len(m["titles"]))
        dcg_contribs = m.get("dcg_contribs", [0.0] * len(m["titles"]))
        for i, (doc_id, title, rel, os_score, dcg_c) in enumerate(
            zip(doc_ids, m["titles"], m["rels"], os_scores, dcg_contribs), 1
        ):
            icon = "+" if rel > 0 else "x"
            label = GRADE_LABELS.get(rel, "")
            score_str = f"{os_score:.2f}" if os_score is not None else "n/a"
            title_trunc = title[:35] + "..." if len(title) > 35 else title
            lines.append(
                f"  {i:>2}. {icon} {doc_id:<16s} {title_trunc:<36s} {score_str:>7s} {rel:>3d} {dcg_c:>7.3f}  {label}"
            )

    # Missed docs
    relevance = test["relevance"]
    all_returned = set()
    for m in metrics_by_method.values():
        all_returned.update(m["titles"])
    missed = [(t, r) for t, r in relevance.items() if r >= 2 and t not in all_returned]
    if missed:
        lines.append(f"\n  Missed (grade>=2, not in any top-{k}):")
        for title, grade in missed:
            lines.append(f"    - {title}  [grade={grade}]")

    return "\n".join(lines)


def format_ndcg_table(tests, all_metrics, k):
    method_names = list(all_metrics.keys())
    name_w = 44

    lines = [
        f"\n{'=' * W}",
        f"  PER-QUERY nDCG@{k}",
        f"{'=' * W}",
    ]

    header = f"  {'Query':<{name_w}s} {'Type':<10s}"
    for m in method_names:
        header += f" {m:>7s}"
    lines.append(header)
    lines.append(f"  {'-' * (name_w + 10 + 8 * len(method_names))}")

    for i, test in enumerate(tests):
        name = test["name"]
        if len(name) > name_w:
            name = name[:name_w - 1] + "..."
        row = f"  {name:<{name_w}s} {test.get('type', ''):<10s}"
        for m in method_names:
            row += f" {all_metrics[m][i]['ndcg']:>7.2f}"
        lines.append(row)

    lines.append(f"  {'-' * (name_w + 10 + 8 * len(method_names))}")
    mean_row = f"  {'MEAN':<{name_w}s} {'':10s}"
    for m in method_names:
        mean_val = sum(met["ndcg"] for met in all_metrics[m]) / len(all_metrics[m])
        mean_row += f" {mean_val:>7.3f}"
    lines.append(mean_row)

    return "\n".join(lines)


def format_summary(tests, all_metrics, k):
    method_names = list(all_metrics.keys())
    name_w = max(12, max((len(m) for m in method_names), default=12))
    row_w = name_w + 12 + 7 + 7 + 7 + 6  # bar + spaces + 3 metric columns
    lines = [
        f"\n{'=' * W}",
        f"  SUMMARY -- Mean Metrics Across {len(tests)} Queries",
        f"{'=' * W}",
        f"  {'Method':<{name_w}s} {'':12s} {'nDCG@'+str(k):>7s} {'P@'+str(k):>7s} {'MRR':>7s}",
        f"  {'-' * row_w}",
    ]

    for method in method_names:
        metrics = all_metrics[method]
        avg_ndcg = sum(m["ndcg"] for m in metrics) / len(metrics)
        avg_pk = sum(m["p@k"] for m in metrics) / len(metrics)
        avg_mrr = sum(m["mrr"] for m in metrics) / len(metrics)
        lines.append(f"  {method:<{name_w}s} {bar(avg_ndcg)}  {avg_ndcg:>7.3f} {avg_pk:>7.2f} {avg_mrr:>7.2f}")

    return "\n".join(lines)


def format_type_breakdown(tests, all_metrics, k):
    method_names = list(all_metrics.keys())
    types = defaultdict(lambda: defaultdict(list))
    for i, test in enumerate(tests):
        for method in method_names:
            types[test.get("type", "unknown")][method].append(all_metrics[method][i]["ndcg"])

    col_w = 12 + 8 + 10 * len(method_names)
    lines = [
        f"\n  Per-Type Breakdown (mean nDCG@{k})",
        f"  {'-' * col_w}",
    ]

    header = f"  {'Type':<12s} {'Queries':>7s}"
    for m in method_names:
        header += f" {m:>9s}"
    lines.append(header)
    lines.append(f"  {'-' * col_w}")

    for qtype in sorted(types.keys()):
        n = len(types[qtype][method_names[0]])
        row = f"  {qtype:<12s} {n:>7d}"
        for m in method_names:
            val = sum(types[qtype][m]) / n
            row += f" {val:>9.3f}"
        lines.append(row)

    return "\n".join(lines)


def format_findings(all_findings):
    flat = [(qname, tag, sev, msg)
            for qname, findings in all_findings for tag, sev, msg in findings]
    if not flat:
        return (
            f"\n{'=' * W}\n"
            f"  FINDINGS: None -- all queries performing well\n"
            f"{'=' * W}"
        )

    lines = [
        f"\n{'=' * W}",
        f"  FINDINGS & RECOMMENDATIONS ({len(flat)} total)",
        f"{'=' * W}",
    ]

    by_tag = defaultdict(list)
    for qname, tag, sev, msg in flat:
        by_tag[tag].append((qname, sev, msg))

    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    tag_order = [
        "[INDEX_MAPPING]", "[EMBEDDING_FIELDS]", "[MODEL_SELECTION]",
        "[SEARCH_PIPELINE]", "[QUERY_TUNING]",
    ]
    all_tags = tag_order + [t for t in by_tag if t not in tag_order]

    max_count = max(len(v) for v in by_tag.values())
    for tag in all_tags:
        items = by_tag.get(tag, [])
        if not items:
            continue
        tag_bar = "##" * len(items)
        label = " -- highest impact" if len(items) == max_count else ""
        lines.append(f"  {tag:22s} ({len(items)}) {tag_bar}{label}")
    lines.append("")

    for tag in all_tags:
        items = by_tag.get(tag, [])
        if not items:
            continue
        items.sort(key=lambda x: severity_order.get(x[1], 9))
        lines.append(f"  {tag} ({len(items)} finding{'s' if len(items) > 1 else ''})")
        lines.append(f"  {'-' * (W - 4)}")
        for qname, sev, msg in items:
            lines.append(f"  [{sev:6s}] {qname}")
            lines.append(f"          {msg}")
            lines.append("")

    high = [(q, t, s, m) for q, t, s, m in flat if s == "HIGH"]
    if high:
        _, tag, _, msg = high[0]
        lines.append(f"  RECOMMENDED NEXT ACTION: {tag}")
        lines.append(f"  {msg}")
    elif flat:
        tag_counts = {t: len(v) for t, v in by_tag.items()}
        top_tag = max(tag_counts, key=tag_counts.get)
        lines.append(f"  RECOMMENDED NEXT ACTION: {top_tag} ({tag_counts[top_tag]} findings)")

    return "\n".join(lines)


def format_completion(report):
    all_metrics = report["metrics"]
    all_findings = report["findings"]
    k = report["k"]

    flat = [(tag, sev) for _, findings in all_findings for tag, sev, _ in findings]
    all_ndcgs = [m["ndcg"] for metrics in all_metrics.values() for m in metrics]
    mean_all = sum(all_ndcgs) / len(all_ndcgs)
    high_count = sum(1 for _, s in flat if s == "HIGH")
    low_only = all(s == "LOW" for _, s in flat) if flat else True

    lines = [
        f"\n{'=' * W}",
        f"  COMPLETION CHECK",
        f"{'=' * W}",
        f"  Mean nDCG@{k} across all methods: {mean_all:.3f} (target > 0.7)",
        f"  HIGH severity findings: {high_count}",
        f"  All findings LOW only: {low_only}",
    ]

    if mean_all > 0.7:
        lines.append(f"  + Target met. Setup is well-optimized.")
    elif low_only and not high_count:
        lines.append(f"  + All findings are LOW severity. Setup is acceptable.")
    else:
        lines.append(f"  x Further optimization recommended. Apply the highest-impact fix and re-evaluate.")

    return "\n".join(lines)


def evaluate_search_results(client, index_name, title_field="title", k=5,
                            max_suggestions=8, extra_queries=None):
    """Phase 1 of evaluation: generate suggestions, run ALL queries in batch
    through the real search pipeline, and return results for the agent to judge.

    Args:
        client: OpenSearch client instance.
        index_name: Target index.
        title_field: Field used to identify documents in results output.
        k: Cutoff depth (number of results per query).
        max_suggestions: Max programmatic test queries to generate.
        extra_queries: Optional list of additional queries, each a dict
            with keys: text, capability.

    Returns:
        dict with:
            - queries: list of {query, capability, results: [{title, score}]}
              for the agent to review and assign relevance grades.
            - _raw: internal state to pass to evaluate_index() so searches
              are not re-run.
    """
    from .search import generate_suggestions, search_ui_search

    gen = generate_suggestions(client, index_name, max_count=max_suggestions)
    suggestions = gen.get("suggestions", []) if isinstance(gen, dict) else gen

    all_queries = []
    for s in suggestions:
        all_queries.append({"text": s["text"], "capability": s["capability"]})

    if extra_queries:
        for eq in extra_queries:
            if eq.get("text"):
                all_queries.append({
                    "text": eq["text"],
                    "capability": eq.get("capability", "semantic"),
                })

    # Batch search: run all queries through the real pipeline
    queries_out = []
    tests = []
    results = []
    for i, q in enumerate(all_queries):
        ui_result = search_ui_search(client, index_name, query_text=q["text"], size=k)
        os_response = _ui_result_to_os_response(ui_result)

        # Extract titles and scores for agent review
        hits_summary = []
        for h in ui_result.get("hits", []):
            title = h.get("source", {}).get(title_field, h.get("id", "?"))
            hits_summary.append({"title": title, "score": round(h.get("score", 0), 4)})

        queries_out.append({
            "query": q["text"],
            "capability": q["capability"],
            "results": hits_summary,
        })

        tests.append({
            "name": f"Q{i+1}: {q['capability']} query",
            "type": q["capability"],
            "query": q["text"],
            "relevance": {},  # filled in by evaluate_index
        })
        results.append(os_response)

    return {
        "queries": queries_out,
        "_raw": {"tests": tests, "results": results,
                 "index_name": index_name, "title_field": title_field, "k": k},
    }


def evaluate_index(client=None, index_name="", title_field="title", k=5,
                   max_suggestions=8, relevance_overrides=None,
                   extra_queries=None, search_results=None):
    """Compute metrics and produce the evaluation report.

    Can be called in two ways:
    1. With search_results from evaluate_search_results() — skips re-running
       searches (preferred, avoids duplicate work).
    2. Without search_results — runs suggestions + searches from scratch.

    Args:
        client: OpenSearch client (required if search_results is None).
        index_name: Target index (required if search_results is None).
        title_field: Field used to identify documents in relevance judgments.
        k: Cutoff depth for metrics.
        max_suggestions: Max programmatic test queries to generate.
        relevance_overrides: Dict mapping query text to {doc_title: grade}.
        extra_queries: Optional additional queries (only used when
            search_results is None).
        search_results: Output from evaluate_search_results(). When provided,
            client/index_name/k/max_suggestions/extra_queries are ignored.

    Returns:
        Formatted report string.
    """
    overrides = relevance_overrides or {}

    if search_results and "_raw" in search_results:
        raw = search_results["_raw"]
        tests = raw["tests"]
        results = raw["results"]
        index_name = raw["index_name"]
        title_field = raw.get("title_field", title_field)
        k = raw.get("k", k)
    else:
        from .search import generate_suggestions, search_ui_search

        gen = generate_suggestions(client, index_name, max_count=max_suggestions)
        suggestions = gen.get("suggestions", []) if isinstance(gen, dict) else gen

        all_queries = []
        for s in suggestions:
            all_queries.append({"text": s["text"], "capability": s["capability"]})
        if extra_queries:
            for eq in extra_queries:
                if eq.get("text"):
                    all_queries.append({
                        "text": eq["text"],
                        "capability": eq.get("capability", "semantic"),
                    })

        tests = []
        results = []
        for i, q in enumerate(all_queries):
            ui_result = search_ui_search(client, index_name, query_text=q["text"], size=k)
            os_response = _ui_result_to_os_response(ui_result)
            tests.append({
                "name": f"Q{i+1}: {q['capability']} query",
                "type": q["capability"],
                "query": q["text"],
                "relevance": {},
            })
            results.append(os_response)

    # Apply relevance overrides
    for test in tests:
        test["relevance"] = overrides.get(test["query"], {})

    report = evaluate_results(
        tests=tests,
        results_by_method={"Search": results},
        k=k,
        title_field=title_field,
    )
    return format_report(report, config={"index": index_name})


def _ui_result_to_os_response(ui_result):
    """Convert a search_ui_search response to OpenSearch-style response."""
    return {
        "hits": {
            "total": {"value": ui_result.get("total", 0)},
            "hits": [
                {"_id": h["id"], "_source": h["source"], "_score": h["score"]}
                for h in ui_result.get("hits", [])
            ],
        }
    }


def format_report(report, config=None):
    """Format a complete evaluation report as a string."""
    tests = report["tests"]
    all_metrics = report["metrics"]
    k = report["k"]
    method_names = report["methods"]

    parts = []
    parts.append(format_header(config or {}, k, len(tests), method_names))

    for i, test in enumerate(tests):
        metrics_by_method = {m: all_metrics[m][i] for m in method_names}
        parts.append(format_query_results(test, metrics_by_method, k))

    parts.append(format_ndcg_table(tests, all_metrics, k))
    parts.append(format_summary(tests, all_metrics, k))
    parts.append(format_type_breakdown(tests, all_metrics, k))
    parts.append(format_findings(report["findings"]))
    parts.append(format_completion(report))

    return "\n".join(parts)
