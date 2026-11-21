"""Report rendering tests: per-mode metric display + backward compat.

Locks in the fix that each mode is displayed on the SAME metric it was ranked
by (dense→recall, sparse/hybrid→ndcg), that a plain Metric still works, and that
a flagged recommendation is explained rather than shown as a bare contradiction.
"""


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

from model import Mode, Metric, Measurement, QualityScore, Cost, Config
import report as report_mod


def _m(mode, label, metric, val, flags=None, footprint=1000):
    q = QualityScore(by_metric_k={(metric, 10): val}, reference="ref")
    return Measurement(
        config=Config.make(mode, label, {}),
        quality=q,
        latency_p50_ms=1.0, latency_p95_ms=1.0, latency_p99_ms=1.0,
        cost=Cost(index_size_bytes=footprint),
        flags=list(flags or []),
    )


def test_text_summary_backward_compat_plain_metric():
    dense = [_m(Mode.DENSE_KNN, "c1", Metric.RECALL, 0.9)]
    out = report_mod.text_summary(
        {Mode.DENSE_KNN: dense}, {Mode.DENSE_KNN: dense}, Metric.RECALL, 10
    )
    assert "recall@10" in out
    assert "c1" in out


def test_text_summary_per_mode_metric_dict():
    dense = [_m(Mode.DENSE_KNN, "d1", Metric.RECALL, 0.95)]
    hybrid = [_m(Mode.HYBRID, "h1", Metric.NDCG, 0.80)]
    mode_metric = {Mode.DENSE_KNN: Metric.RECALL, Mode.HYBRID: Metric.NDCG}
    out = report_mod.text_summary(
        {Mode.DENSE_KNN: dense, Mode.HYBRID: hybrid},
        {Mode.DENSE_KNN: dense, Mode.HYBRID: hybrid},
        mode_metric, 10,
    )
    # Dense shown on recall, hybrid on ndcg — no mixup.
    assert "recall@10" in out
    assert "ndcg@10" in out
    # The hybrid ndcg value must render (0.800), proving it read the right metric.
    assert "0.800" in out


def test_html_flagged_recommendation_is_explained():
    # Recommended config also flagged (constrained pick below global best).
    flagged = _m(Mode.DENSE_KNN, "efs100", Metric.RECALL, 0.90, flags=["silent-quality-drop"])
    html = report_mod.render_html(
        {Mode.DENSE_KNN: [flagged]}, {Mode.DENSE_KNN: [flagged]},
        {Mode.DENSE_KNN: Metric.RECALL}, 10,
    )
    assert "best within your constraints" in html  # explained, not contradictory


def test_html_exact_mode_shows_honesty_note():
    sparse = [_m(Mode.SPARSE_RANK_FEATURES, "s1", Metric.NDCG, 0.7)]
    html = report_mod.render_html(
        {Mode.SPARSE_RANK_FEATURES: sparse}, {Mode.SPARSE_RANK_FEATURES: sparse},
        {Mode.SPARSE_RANK_FEATURES: Metric.NDCG}, 10,
    )
    assert "exact Lucene scoring" in html
    assert "ndcg@10" in html
