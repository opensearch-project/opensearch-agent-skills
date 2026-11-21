"""Quality metrics for retrieval evaluation.

This module implements the correctness backbone of ai-search-tuner. All functions
are pure (no I/O, no cluster access) and unit-tested against hand-computed values.

Metrics
-------
- **Recall@k**: Fidelity of approximate search (DENSE_KNN, SPARSE_ANN) to exact
  search. Measures |top-k(retrieved) ∩ top-k(reference)| / min(k, |reference|).
  Only meaningful for approximate modes.

- **NDCG@k**: Normalized Discounted Cumulative Gain. Standard relevance metric
  using graded judgments (qrels). Gain = relevance_grade, discount = log2(rank+1).

- **MAP@k**: Mean Average Precision at k. For a single query, this is Average
  Precision (mean of precision@i for each relevant doc in top-k).

Per-mode scoring rules (see DESIGN.md §6)
-----------------------------------------
- DENSE_KNN (approximate): Recall@k vs FP32-brute-force reference
- SPARSE_RANK_FEATURES (exact): NDCG/MAP vs qrels or result-overlap vs unpruned
  baseline (NOT recall-vs-itself, which is trivially 1.0)
- SPARSE_ANN (approximate): Recall@k vs exact sparse + NDCG/MAP vs qrels
- HYBRID: NDCG@k lift vs best-standalone reference
"""

from __future__ import annotations

import math
from typing import Iterable

from model import Mode, Metric, QualityScore, RunResult, QueryResult
from corpus import Qrels


def recall_at_k(retrieved: list[str], reference: list[str], k: int) -> float:
    """Compute recall@k: fidelity of approximate search to exact search.

    Args:
        retrieved: Ranked doc ids from the approximate system (best-first)
        reference: Ranked doc ids from the exact reference (best-first)
        k: Cutoff depth

    Returns:
        Fraction of reference top-k docs that appear in retrieved top-k:
        |top-k(retrieved) ∩ top-k(reference)| / min(k, |reference|)

    Notes:
        - Returns 0.0 if reference is empty
        - Handles k > len(reference) gracefully (denominator = len(reference))
        - Handles k > len(retrieved) gracefully (uses what's available)
    """
    if not reference or k <= 0:
        return 0.0

    # Clamp k to what's actually available in reference
    effective_k = min(k, len(reference))

    # Top-k sets
    retrieved_topk = set(retrieved[:k])
    reference_topk = set(reference[:effective_k])

    # Intersection size / denominator
    overlap = len(retrieved_topk & reference_topk)
    return overlap / effective_k


def ndcg_at_k(retrieved: list[str], graded: dict[str, int], k: int) -> float:
    """Compute NDCG@k: normalized discounted cumulative gain with graded judgments.

    Args:
        retrieved: Ranked doc ids from the system (best-first)
        graded: Graded relevance judgments {doc_id: grade}. Grade >= 1 is relevant.
        k: Cutoff depth

    Returns:
        NDCG@k ∈ [0, 1]. Returns 0.0 if no relevant docs exist in graded.

    Formula:
        DCG@k = Σ(gain / log2(rank+1)) for rank in [1, k]
        where gain = graded.get(doc_id, 0)

        IDCG@k = DCG of an ideal ranking (graded docs sorted by relevance, descending)

        NDCG@k = DCG@k / IDCG@k (or 0.0 if IDCG = 0)

    Notes:
        - Uses gain = relevance_grade directly (no 2^rel - 1 transform)
        - Uses log2(rank+1) discount (rank is 1-indexed)
        - Returns 0.0 if no relevant docs in judgments (IDCG = 0)
    """
    if not graded or k <= 0:
        return 0.0

    # Compute DCG@k for the retrieved ranking
    dcg = 0.0
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        gain = graded.get(doc_id, 0)
        if gain > 0:
            dcg += gain / math.log2(rank + 1)

    # Compute IDCG@k: ideal ranking (sorted by relevance descending)
    ideal_gains = sorted(graded.values(), reverse=True)
    idcg = 0.0
    for rank, gain in enumerate(ideal_gains[:k], start=1):
        if gain > 0:
            idcg += gain / math.log2(rank + 1)

    if idcg == 0.0:
        return 0.0

    return dcg / idcg


def map_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    """Compute MAP@k: Mean Average Precision at k for a single query.

    Args:
        retrieved: Ranked doc ids from the system (best-first)
        graded: Set of relevant doc ids (binary relevance)
        k: Cutoff depth

    Returns:
        Average Precision at k ∈ [0, 1]. Returns 0.0 if no relevant docs.

    Formula:
        AP@k = (1 / min(k, |relevant|)) × Σ(precision@i) for each relevant doc at rank i in top-k

        Where precision@i = (# relevant docs in top-i) / i

    Notes:
        - This is AP for a SINGLE query. The "mean" in MAP happens when aggregating
          across multiple queries.
        - The denominator is the RECALL BASE min(k, |relevant|) — NOT the number
          of relevant docs that happen to be retrieved. Normalizing by the count
          retrieved would collapse AP to "mean precision at the hits" and inflate
          it to 1.0 whenever every retrieved-relevant doc sits at the top, even if
          most relevant docs were missed. min(k, |relevant|) matches the @k
          truncation and this module's recall_at_k denominator convention.
        - Returns 0.0 if relevant is empty or no relevant docs appear in top-k
    """
    if not relevant or k <= 0:
        return 0.0

    num_relevant_seen = 0
    sum_precisions = 0.0

    for rank, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in relevant:
            num_relevant_seen += 1
            precision_at_rank = num_relevant_seen / rank
            sum_precisions += precision_at_rank

    if num_relevant_seen == 0:
        return 0.0

    # Normalize by the recall base (relevant docs reachable within k), not by
    # how many we actually retrieved — see Notes above.
    denom = min(k, len(relevant))
    return sum_precisions / denom


def score_run(
    run: RunResult,
    mode: Mode,
    reference_ranking: dict[str, list[str]] | None,
    qrels: Qrels | None,
    ks: tuple[int, ...] = (5, 10, 100),
) -> QualityScore:
    """Score a full run (all queries) against per-mode references.

    This is the main entry point for quality evaluation. It computes per-query
    metrics and aggregates them (mean across queries) into a single QualityScore.

    Scoring rules (see DESIGN.md §6):
    ----------------------------------
    1. If mode.is_approximate (DENSE_KNN, SPARSE_ANN) AND reference_ranking provided:
       → Compute Recall@k for each k (vs reference)
       → Set reference field to indicate the exact reference used

    2. If qrels provided (regardless of mode):
       → Compute NDCG@k and MAP@k for each k

    3. If mode is NOT approximate (e.g. SPARSE_RANK_FEATURES):
       → Do NOT emit Recall vs itself (trivially 1.0, misleading)
       → If reference_ranking provided (unpruned baseline), emit Recall@k but
         label reference="unpruned-baseline" (result overlap, not fidelity-to-exact)
       → Emit NDCG/MAP if qrels present

    Args:
        run: Complete run results (config + per_query ranked results)
        mode: The retrieval mode (determines scoring semantics)
        reference_ranking: Ground-truth ranking per query {query_id: [doc_ids]}
            - For approximate modes: exact search results (brute-force / exact-sparse)
            - For exact modes: unpruned baseline for result-overlap measurement
        qrels: Graded relevance judgments {query_id: {doc_id: grade}}
        ks: Cutoff depths to evaluate (default: 5, 10, 100)

    Returns:
        QualityScore with aggregated (mean) metrics across all queries.
        by_metric_k maps (Metric, k) → mean_value
        reference indicates the ground truth used (for report honesty)

    Notes:
        - Aggregation: Computes per-query metric, then takes mean across queries
        - Empty runs return an empty QualityScore
        - Queries missing from reference/qrels are skipped for that metric
    """
    if not run.per_query:
        return QualityScore()

    # Accumulators for per-query metrics
    # Structure: {(Metric, k): [values_per_query]}
    per_query_values: dict[tuple[Metric, int], list[float]] = {}

    for query_result in run.per_query:
        query_id = query_result.query_id
        retrieved = query_result.doc_ids

        # --- Recall@k (approximate modes only, vs reference) ---
        if mode.is_approximate and reference_ranking:
            if query_id in reference_ranking:
                ref_docs = reference_ranking[query_id]
                for k in ks:
                    recall = recall_at_k(retrieved, ref_docs, k)
                    per_query_values.setdefault((Metric.RECALL, k), []).append(recall)

        # --- Result overlap vs unpruned baseline (exact modes with reference) ---
        # SPARSE_RANK_FEATURES with a reference (unpruned) should measure overlap,
        # NOT fidelity-to-exact (it IS exact). Label reference appropriately.
        elif not mode.is_approximate and reference_ranking:
            if query_id in reference_ranking:
                ref_docs = reference_ranking[query_id]
                for k in ks:
                    recall = recall_at_k(retrieved, ref_docs, k)
                    per_query_values.setdefault((Metric.RECALL, k), []).append(recall)

        # --- NDCG@k and MAP@k (when qrels provided, any mode) ---
        # Skip queries with no relevant docs: NDCG/MAP are undefined (not 0) for
        # them, and averaging in a 0.0 would bias the aggregate mean downward.
        if qrels and query_id in qrels:
            graded = qrels[query_id]
            relevant_set = {doc for doc, grade in graded.items() if grade >= 1}
            if not relevant_set:
                continue

            for k in ks:
                # NDCG@k
                ndcg = ndcg_at_k(retrieved, graded, k)
                per_query_values.setdefault((Metric.NDCG, k), []).append(ndcg)

                # MAP@k
                map_score = map_at_k(retrieved, relevant_set, k)
                per_query_values.setdefault((Metric.MAP, k), []).append(map_score)

    # --- Aggregate: mean across queries ---
    by_metric_k: dict[tuple[Metric, int], float] = {}
    for key, values in per_query_values.items():
        by_metric_k[key] = sum(values) / len(values) if values else 0.0

    # --- Determine reference label ---
    reference_label = ""
    if mode.is_approximate and reference_ranking:
        # Approximate mode with exact reference
        reference_label = "exact"  # Could be refined: "fp32-brute-force", "exact-sparse"
    elif not mode.is_approximate and reference_ranking:
        # Exact mode with unpruned baseline
        reference_label = "unpruned-baseline"

    if qrels:
        # If qrels present, NDCG/MAP are also graded vs qrels
        if reference_label:
            reference_label += "+qrels"
        else:
            reference_label = "qrels"

    return QualityScore(by_metric_k=by_metric_k, reference=reference_label)


def aggregate(
    scores: list[QualityScore],
    ks: tuple[int, ...],
    metrics: Iterable[Metric],
) -> QualityScore:
    """Aggregate multiple QualityScores (e.g., from different runs or cross-validation).

    Args:
        scores: List of QualityScore objects to aggregate
        ks: Cutoff depths to aggregate over
        metrics: Metrics to aggregate

    Returns:
        QualityScore with mean values across input scores

    Notes:
        - This function is provided for completeness but may not be needed in the
          current design, since score_run already aggregates across queries.
        - Use this if you need to aggregate across multiple runs (e.g., CV folds).
    """
    if not scores:
        return QualityScore()

    # Accumulators
    aggregated: dict[tuple[Metric, int], list[float]] = {}

    for score in scores:
        for metric in metrics:
            for k in ks:
                value = score.get(metric, k)
                if value is not None:
                    aggregated.setdefault((metric, k), []).append(value)

    # Mean across scores
    by_metric_k: dict[tuple[Metric, int], float] = {}
    for key, values in aggregated.items():
        by_metric_k[key] = sum(values) / len(values) if values else 0.0

    # Take reference from first score (assumes homogeneous)
    reference_label = scores[0].reference if scores else ""

    return QualityScore(by_metric_k=by_metric_k, reference=reference_label)
