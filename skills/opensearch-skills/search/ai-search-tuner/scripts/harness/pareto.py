"""Pareto frontier computation and recommendation engine.

This module ranks Measurements (quality + latency + footprint) to identify the
Pareto-optimal frontier and recommend the best config(s) given user constraints.

Dominance definition (three-dimensional)
----------------------------------------
A measurement `a` is DOMINATED by `b` (i.e., `b` is strictly better) when:
    - b.quality >= a.quality   (higher or equal is better)
    - b.latency_p95 <= a.latency_p95   (lower or equal is better)
    - b.footprint <= a.footprint   (lower or equal is better, where footprint is
      cost.primary_bytes())
AND
    - b is strictly better on at least one axis.

If either measurement has None for footprint (cost.primary_bytes()), they are
not comparable on that axis — we compare only on quality and latency in that
case. This handles modes where cost is not applicable (e.g., hybrid, which has
no inherent footprint distinct from its sub-indices).

Scalarization for ranking within the frontier
----------------------------------------------
When multiple Pareto-optimal configs exist, we need to pick a single
recommendation. The scalarization used is:
    1. Maximize quality (primary objective).
    2. Tie-break by minimizing footprint (cost.primary_bytes()).
    3. Tie-break by minimizing latency_p95.

This reflects a typical production preference: quality is paramount; if two
configs achieve the same quality, prefer the one that uses less memory/disk;
if still tied, prefer the faster one.

Constraint filtering
--------------------
`recommend` filters Measurements to those meeting `quality_floor` and
`latency_budget_ms` BEFORE ranking. If nothing meets constraints, it returns
the best-effort frontier (top configs on quality) with a flag
"constraint-unmet" and documents this in the Measurement.flags.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from model import Measurement, Metric

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def is_dominated(a: Measurement, b: Measurement, metric: Metric, k: int) -> bool:
    """Return True if `a` is dominated by `b` (i.e., `b` is strictly better).

    Parameters
    ----------
    a, b : Measurement
        The two configs to compare.
    metric : Metric
        Quality metric to use (RECALL, NDCG, or MAP).
    k : int
        The k value for quality@k.

    Returns
    -------
    bool
        True when `b` dominates `a` (b is >= on quality, <= on latency/footprint,
        and strictly better on at least one axis).

    Notes
    -----
    If either measurement has None for footprint (cost.primary_bytes()), we
    compare only on quality and latency. This handles modes where cost is not
    distinct (e.g., hybrid).
    """
    qa = a.primary_quality(metric, k)
    qb = b.primary_quality(metric, k)

    # If quality is missing for either, cannot compare.
    if qa is None or qb is None:
        return False

    la = a.latency_p95_ms
    lb = b.latency_p95_ms

    fa = a.cost.primary_bytes()
    fb = b.cost.primary_bytes()

    # Determine whether footprint is comparable.
    footprint_comparable = fa is not None and fb is not None

    # b dominates a if:
    # - b.quality >= a.quality
    # - b.latency <= a.latency
    # - b.footprint <= a.footprint (if both present)
    # - AND b is strictly better on at least one axis.

    if qb < qa:
        return False  # b has lower quality
    if lb > la:
        return False  # b has higher latency

    if footprint_comparable:
        if fb > fa:
            return False  # b has higher footprint

    # Now b is >= on all axes. Check if strictly better on at least one.
    strictly_better = False
    if qb > qa:
        strictly_better = True
    if lb < la:
        strictly_better = True
    if footprint_comparable and fb < fa:
        strictly_better = True

    return strictly_better


def pareto_frontier(
    ms: list[Measurement], metric: Metric, k: int
) -> list[Measurement]:
    """Return the non-dominated set (Pareto frontier).

    A Measurement is on the frontier if no other Measurement dominates it.

    Parameters
    ----------
    ms : list[Measurement]
        All measurements to consider.
    metric : Metric
        Quality metric to use.
    k : int
        The k value for quality@k.

    Returns
    -------
    list[Measurement]
        The Pareto-optimal subset (order is arbitrary).
    """
    frontier: list[Measurement] = []
    for candidate in ms:
        # Check if any existing frontier member dominates candidate.
        dominated = False
        for member in frontier:
            if is_dominated(candidate, member, metric, k):
                dominated = True
                break
        if dominated:
            continue

        # Candidate is not dominated by frontier. Remove any frontier members
        # it dominates, then add candidate.
        frontier = [m for m in frontier if not is_dominated(m, candidate, metric, k)]
        frontier.append(candidate)

    return frontier


def flag_regressions(
    ms: list[Measurement],
    metric: Metric,
    k: int,
    ref_quality: float,
    drop_threshold: float = 0.05,
) -> None:
    """Mutate each Measurement.flags: append "silent-quality-drop" when quality drops.

    This is the detector for issues like k-NN #21 (0.91 → 0.79 silent recall
    drop on quantization toggle). Any config whose quality@k is below
    ref_quality * (1 - drop_threshold) gets flagged.

    Parameters
    ----------
    ms : list[Measurement]
        Measurements to inspect (mutated in place).
    metric : Metric
        Quality metric to use.
    k : int
        The k value for quality@k.
    ref_quality : float
        The reference quality (e.g., the exact/unpruned baseline).
    drop_threshold : float, default 0.05
        Fraction below which to flag (e.g., 0.05 = flag if quality < 95% of ref).

    Returns
    -------
    None
        Mutates Measurement.flags in place.
    """
    threshold = ref_quality * (1.0 - drop_threshold)
    for m in ms:
        q = m.primary_quality(metric, k)
        if q is not None and q < threshold:
            if "silent-quality-drop" not in m.flags:
                m.flags.append("silent-quality-drop")
                logger.warning(
                    f"Config {m.config.label}: {metric.value}@{k} = {q:.3f} "
                    f"< {threshold:.3f} (ref {ref_quality:.3f}) — flagged as silent quality drop"
                )


def recommend(
    ms: list[Measurement],
    metric: Metric,
    k: int,
    quality_floor: float | None = None,
    latency_budget_ms: float | None = None,
    top_n: int = 3,
) -> list[Measurement]:
    """Return the top_n recommended configs from the Pareto frontier.

    Scalarization (ranking order)
    ------------------------------
    1. Maximize quality (primary objective).
    2. Tie-break by minimizing footprint (cost.primary_bytes()).
    3. Tie-break by minimizing latency_p95.

    Constraint handling
    -------------------
    Only configs meeting both `quality_floor` and `latency_budget_ms` (if
    provided) are considered. If nothing meets constraints, return the
    best-effort frontier (top configs on quality alone) with a
    "constraint-unmet" flag appended to each returned Measurement.

    Parameters
    ----------
    ms : list[Measurement]
        All measurements to consider.
    metric : Metric
        Quality metric to use.
    k : int
        The k value for quality@k.
    quality_floor : float | None
        Minimum quality required (if provided).
    latency_budget_ms : float | None
        Maximum latency_p95 allowed (if provided).
    top_n : int, default 3
        Number of recommendations to return.

    Returns
    -------
    list[Measurement]
        Top_n Pareto-optimal configs, ranked by the scalarization.
        If no configs meet constraints, returns best-effort frontier with
        "constraint-unmet" flag.
    """
    if not ms:
        return []

    # Filter to configs meeting constraints.
    feasible = []
    for m in ms:
        q = m.primary_quality(metric, k)
        if q is None:
            continue
        if quality_floor is not None and q < quality_floor:
            continue
        if latency_budget_ms is not None and m.latency_p95_ms > latency_budget_ms:
            continue
        feasible.append(m)

    if not feasible:
        # No configs meet constraints — best-effort fallback.
        logger.warning(
            f"No configs meet quality_floor={quality_floor}, "
            f"latency_budget_ms={latency_budget_ms}. "
            "Returning best-effort frontier with constraint-unmet flag."
        )
        # Rank by quality alone, return top_n.
        ranked = sorted(
            [m for m in ms if m.primary_quality(metric, k) is not None],
            key=lambda m: -m.primary_quality(metric, k),
        )
        best_effort = ranked[:top_n]
        for m in best_effort:
            if "constraint-unmet" not in m.flags:
                m.flags.append("constraint-unmet")
        return best_effort

    # Compute Pareto frontier on feasible configs.
    frontier = pareto_frontier(feasible, metric, k)

    # Rank the frontier by scalarization.
    def rank_key(m: Measurement) -> tuple:
        q = m.primary_quality(metric, k) or 0.0
        footprint = m.cost.primary_bytes() or 0
        latency = m.latency_p95_ms
        # We want to maximize quality, minimize footprint and latency.
        # Sort order: descending quality, ascending footprint, ascending latency.
        return (-q, footprint, latency)

    ranked = sorted(frontier, key=rank_key)
    return ranked[:top_n]
