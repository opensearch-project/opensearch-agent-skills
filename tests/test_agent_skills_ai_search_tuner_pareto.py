"""Tests for pareto.py: dominance, frontier, flagging, and recommendations."""

from __future__ import annotations


import sys as _sys
from pathlib import Path as _Path

# ai-search-tuner uses a flat-import layout; put its skill script dirs and the
# test fixtures dir on sys.path so `from model import ...`, `from dense_knn
# import ...`, `from fake_client import ...` resolve (no running cluster needed).
_REPO_ROOT = _Path(__file__).resolve().parents[1]
_SKILL = _REPO_ROOT / "skills" / "opensearch-skills" / "search" / "ai-search-tuner" / "scripts"
for _p in (_SKILL, _SKILL / "harness", _SKILL / "modes"):
    _sp = str(_p)
    if _sp not in _sys.path:
        _sys.path.insert(0, _sp)

import pytest

from model import Config, Cost, Measurement, Metric, Mode, QualityScore
from pareto import flag_regressions, is_dominated, pareto_frontier, recommend


def _make_measurement(
    label: str,
    quality: float,
    latency_p95: float,
    footprint: int | None = None,
) -> Measurement:
    """Helper to construct a Measurement with known quality/latency/footprint."""
    config = Config.make(Mode.DENSE_KNN, label, {})
    quality_score = QualityScore(reference="test")
    quality_score.by_metric_k[(Metric.RECALL, 10)] = quality
    cost = Cost(graph_memory_bytes=footprint)
    return Measurement(
        config=config,
        quality=quality_score,
        latency_p50_ms=latency_p95 * 0.8,  # arbitrary
        latency_p95_ms=latency_p95,
        latency_p99_ms=latency_p95 * 1.1,  # arbitrary
        cost=cost,
        flags=[],
    )


# --- Tests for is_dominated ---


def test_is_dominated_b_better_on_all_axes():
    """b has higher quality, lower latency, lower footprint → dominates a."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=1500)
    assert is_dominated(a, b, Metric.RECALL, 10) is True


def test_is_dominated_b_equal_on_all_axes():
    """b is equal on all axes → does NOT dominate (no strict improvement)."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.90, latency_p95=50.0, footprint=2000)
    assert is_dominated(a, b, Metric.RECALL, 10) is False


def test_is_dominated_b_worse_on_quality():
    """b has lower quality → does NOT dominate, even if better on other axes."""
    a = _make_measurement("a", quality=0.95, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.90, latency_p95=40.0, footprint=1500)
    assert is_dominated(a, b, Metric.RECALL, 10) is False


def test_is_dominated_b_worse_on_latency():
    """b has higher latency → does NOT dominate."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=60.0, footprint=1500)
    assert is_dominated(a, b, Metric.RECALL, 10) is False


def test_is_dominated_b_worse_on_footprint():
    """b has higher footprint → does NOT dominate."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=1500)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=2000)
    assert is_dominated(a, b, Metric.RECALL, 10) is False


def test_is_dominated_b_better_on_one_axis_only():
    """b is strictly better on quality, equal on latency/footprint → dominates."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=50.0, footprint=2000)
    assert is_dominated(a, b, Metric.RECALL, 10) is True


def test_is_dominated_missing_footprint():
    """If footprint is None for either, compare only quality and latency."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=None)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=None)
    # b is better on quality and latency → dominates.
    assert is_dominated(a, b, Metric.RECALL, 10) is True


def test_is_dominated_one_missing_footprint():
    """If only one has footprint, they are not comparable on that axis."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=None)
    # b is better on quality and latency, but footprint is not comparable.
    # We treat this as: b dominates a on the axes we can compare (quality, latency).
    assert is_dominated(a, b, Metric.RECALL, 10) is True


def test_is_dominated_missing_quality():
    """If quality is missing for either, cannot compare → return False."""
    config_a = Config.make(Mode.DENSE_KNN, "a", {})
    config_b = Config.make(Mode.DENSE_KNN, "b", {})
    quality_a = QualityScore(reference="test")
    # quality_a has no entry for (RECALL, 10).
    quality_b = QualityScore(reference="test")
    quality_b.by_metric_k[(Metric.RECALL, 10)] = 0.95

    a = Measurement(
        config=config_a,
        quality=quality_a,
        latency_p50_ms=40.0,
        latency_p95_ms=50.0,
        latency_p99_ms=55.0,
        cost=Cost(graph_memory_bytes=2000),
        flags=[],
    )
    b = Measurement(
        config=config_b,
        quality=quality_b,
        latency_p50_ms=32.0,
        latency_p95_ms=40.0,
        latency_p99_ms=44.0,
        cost=Cost(graph_memory_bytes=1500),
        flags=[],
    )

    assert is_dominated(a, b, Metric.RECALL, 10) is False


# --- Tests for pareto_frontier ---


def test_pareto_frontier_single_measurement():
    """Single measurement → frontier is itself."""
    m = _make_measurement("only", quality=0.90, latency_p95=50.0, footprint=2000)
    frontier = pareto_frontier([m], Metric.RECALL, 10)
    assert frontier == [m]


def test_pareto_frontier_all_dominated_by_one():
    """One clearly best config dominates all others."""
    # a: quality 0.95, latency 40, footprint 1500 (best on all axes)
    # b: quality 0.90, latency 50, footprint 2000 (worse on all)
    # c: quality 0.85, latency 60, footprint 2500 (worse on all)
    a = _make_measurement("a", quality=0.95, latency_p95=40.0, footprint=1500)
    b = _make_measurement("b", quality=0.90, latency_p95=50.0, footprint=2000)
    c = _make_measurement("c", quality=0.85, latency_p95=60.0, footprint=2500)

    frontier = pareto_frontier([a, b, c], Metric.RECALL, 10)
    assert frontier == [a]


def test_pareto_frontier_multiple_non_dominated():
    """Multiple Pareto-optimal configs (tradeoff space).

    Reasoning:
    - a: quality 0.90, latency 40, footprint 1500
    - b: quality 0.95, latency 60, footprint 1800
    - c: quality 0.85, latency 30, footprint 1200

    a vs b: a has lower quality but lower latency → neither dominates.
    a vs c: a has higher quality but higher latency and footprint → neither dominates.
    b vs c: b has higher quality but higher latency and footprint → neither dominates.

    All three are Pareto-optimal.
    """
    a = _make_measurement("a", quality=0.90, latency_p95=40.0, footprint=1500)
    b = _make_measurement("b", quality=0.95, latency_p95=60.0, footprint=1800)
    c = _make_measurement("c", quality=0.85, latency_p95=30.0, footprint=1200)

    frontier = pareto_frontier([a, b, c], Metric.RECALL, 10)
    assert set(m.config.label for m in frontier) == {"a", "b", "c"}


def test_pareto_frontier_one_dominated():
    """One config is strictly dominated and is excluded from the frontier.

    Reasoning:
    - a: quality 0.90, latency 50, footprint 2000
    - b: quality 0.95, latency 40, footprint 1500 (dominates a on all axes)
    - c: quality 0.95, latency 40, footprint 1600 (not dominated by b — equal on quality/latency, worse on footprint, so c is dominated by b)

    Actually, c is dominated by b (b has equal quality, equal latency, lower footprint).
    So only b is on the frontier.
    """
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=1500)
    c = _make_measurement("c", quality=0.95, latency_p95=40.0, footprint=1600)

    frontier = pareto_frontier([a, b, c], Metric.RECALL, 10)
    # b dominates both a and c.
    assert frontier == [b]


# --- Tests for flag_regressions ---


def test_flag_regressions_none_flagged():
    """All measurements meet threshold → no flags added."""
    m1 = _make_measurement("m1", quality=0.96, latency_p95=50.0, footprint=2000)
    m2 = _make_measurement("m2", quality=0.98, latency_p95=40.0, footprint=1500)

    flag_regressions([m1, m2], Metric.RECALL, 10, ref_quality=0.95, drop_threshold=0.05)

    assert m1.flags == []
    assert m2.flags == []


def test_flag_regressions_one_flagged():
    """One measurement below threshold → flagged."""
    m1 = _make_measurement("m1", quality=0.89, latency_p95=50.0, footprint=2000)
    m2 = _make_measurement("m2", quality=0.96, latency_p95=40.0, footprint=1500)

    # ref_quality=0.95, drop_threshold=0.05 → threshold = 0.95 * 0.95 = 0.9025
    # m1 quality 0.89 < 0.9025 → flagged.
    flag_regressions([m1, m2], Metric.RECALL, 10, ref_quality=0.95, drop_threshold=0.05)

    assert "silent-quality-drop" in m1.flags
    assert m2.flags == []


def test_flag_regressions_exact_threshold_not_flagged():
    """Measurement exactly at threshold → NOT flagged."""
    m = _make_measurement("m", quality=0.9025, latency_p95=50.0, footprint=2000)

    flag_regressions([m], Metric.RECALL, 10, ref_quality=0.95, drop_threshold=0.05)

    assert m.flags == []


def test_flag_regressions_duplicate_flag_not_added():
    """If flag is already present, don't add it again."""
    m = _make_measurement("m", quality=0.80, latency_p95=50.0, footprint=2000)
    m.flags.append("silent-quality-drop")

    flag_regressions([m], Metric.RECALL, 10, ref_quality=0.95, drop_threshold=0.05)

    # Should have exactly one occurrence.
    assert m.flags.count("silent-quality-drop") == 1


# --- Tests for recommend ---


def test_recommend_all_meet_constraints():
    """All configs meet constraints; top_n returned from Pareto frontier."""
    # a: quality 0.90, latency 50, footprint 2000
    # b: quality 0.95, latency 40, footprint 1500
    # c: quality 0.92, latency 45, footprint 1800
    # Pareto frontier: a vs b → b dominates a. b vs c → b dominates c.
    # Frontier is [b].
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=1500)
    c = _make_measurement("c", quality=0.92, latency_p95=45.0, footprint=1800)

    result = recommend(
        [a, b, c],
        Metric.RECALL,
        10,
        quality_floor=0.85,
        latency_budget_ms=60.0,
        top_n=3,
    )

    # Only b is on the frontier.
    assert len(result) == 1
    assert result[0].config.label == "b"


def test_recommend_no_constraints():
    """No constraints → all feasible, return top_n from frontier."""
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=60.0, footprint=1800)
    c = _make_measurement("c", quality=0.85, latency_p95=30.0, footprint=1200)

    # Frontier is {a, b, c} (none dominate). Scalarization: max quality, then min footprint, then min latency.
    # Ranking: b (0.95), a (0.90), c (0.85).
    result = recommend([a, b, c], Metric.RECALL, 10, top_n=2)

    assert len(result) == 2
    assert result[0].config.label == "b"
    assert result[1].config.label == "a"


def test_recommend_quality_floor_excludes_some():
    """quality_floor excludes one config."""
    a = _make_measurement("a", quality=0.80, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=1500)

    result = recommend(
        [a, b],
        Metric.RECALL,
        10,
        quality_floor=0.85,
        top_n=3,
    )

    # a is excluded; only b is feasible.
    assert len(result) == 1
    assert result[0].config.label == "b"


def test_recommend_latency_budget_excludes_some():
    """latency_budget_ms excludes one config."""
    a = _make_measurement("a", quality=0.90, latency_p95=60.0, footprint=2000)
    b = _make_measurement("b", quality=0.95, latency_p95=40.0, footprint=1500)

    result = recommend(
        [a, b],
        Metric.RECALL,
        10,
        latency_budget_ms=50.0,
        top_n=3,
    )

    # a is excluded (latency 60 > 50); only b is feasible.
    assert len(result) == 1
    assert result[0].config.label == "b"


def test_recommend_nothing_meets_constraints():
    """Nothing meets constraints → best-effort fallback with constraint-unmet flag."""
    a = _make_measurement("a", quality=0.80, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.85, latency_p95=40.0, footprint=1500)

    result = recommend(
        [a, b],
        Metric.RECALL,
        10,
        quality_floor=0.90,  # both below threshold
        top_n=2,
    )

    # Best-effort: rank by quality, return top_n.
    assert len(result) == 2
    assert result[0].config.label == "b"  # 0.85 > 0.80
    assert result[1].config.label == "a"
    # Both should have constraint-unmet flag.
    assert "constraint-unmet" in result[0].flags
    assert "constraint-unmet" in result[1].flags


def test_recommend_scalarization_quality_first():
    """Scalarization: maximize quality (primary objective)."""
    # a: quality 0.90, latency 40, footprint 1500
    # b: quality 0.95, latency 50, footprint 2000
    # Neither dominates; rank by quality.
    a = _make_measurement("a", quality=0.90, latency_p95=40.0, footprint=1500)
    b = _make_measurement("b", quality=0.95, latency_p95=50.0, footprint=2000)

    result = recommend([a, b], Metric.RECALL, 10, top_n=2)

    # b has higher quality → ranked first.
    assert result[0].config.label == "b"
    assert result[1].config.label == "a"


def test_recommend_scalarization_footprint_tiebreak():
    """Scalarization: tie on quality, break by footprint."""
    # a: quality 0.90, latency 50, footprint 2000
    # b: quality 0.90, latency 50, footprint 1500
    # Neither dominates (b is strictly better on footprint only → dominates a).
    # Frontier is [b].
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.90, latency_p95=50.0, footprint=1500)

    result = recommend([a, b], Metric.RECALL, 10, top_n=2)

    # b has lower footprint → ranked first (and is the only one on the frontier).
    assert len(result) == 1
    assert result[0].config.label == "b"


def test_recommend_scalarization_latency_tiebreak():
    """Scalarization: tie on quality and footprint, break by latency."""
    # a: quality 0.90, latency 50, footprint 2000
    # b: quality 0.90, latency 40, footprint 2000
    # Frontier is [b] (dominates a on latency).
    a = _make_measurement("a", quality=0.90, latency_p95=50.0, footprint=2000)
    b = _make_measurement("b", quality=0.90, latency_p95=40.0, footprint=2000)

    result = recommend([a, b], Metric.RECALL, 10, top_n=2)

    # b has lower latency → ranked first (and is the only one on the frontier).
    assert len(result) == 1
    assert result[0].config.label == "b"
