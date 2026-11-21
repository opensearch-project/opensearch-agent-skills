"""Tests for capability detection (probe.py).

Uses FakeOSClient to verify probe logic without a real cluster.
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

import sys
from pathlib import Path

# Add paths for flat import style
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "harness"))
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from probe import detect_capabilities, capability_summary, _version_gte
from model import Capabilities, Mode
from fake_client import FakeOSClient


def test_default_fake_capabilities():
    """Default FakeOSClient (knn + neural-search, version 2.17.1) detection."""
    # Default fake has opensearch-knn, opensearch-neural-search, opensearch-ml
    # version 2.17.1, ml_model_ids=["sparse-doc-v3"]
    client = FakeOSClient()
    cap = detect_capabilities(client)

    assert cap.version == "2.17.1"
    assert cap.dense_knn is True
    assert cap.sparse_rank_features is True
    assert cap.hybrid is True
    # sparse_ann requires neural-search + version >= 3.3; 2.17.1 < 3.3 → False
    assert cap.sparse_ann is False
    assert cap.knn_engines == ("lucene", "faiss", "nmslib")
    # version 2.17.1 >= 2.13 → fp32 + fp16
    assert "fp32" in cap.quantization
    assert "fp16" in cap.quantization
    # sparse models
    assert "sparse-doc-v3" in cap.sparse_models
    # notes should mention quantization is engine/version dependent
    assert any("Quantization availability" in n for n in cap.notes)


def test_sparse_ann_available_with_3_3():
    """sparse_ann (SEISMIC) lights up when version >= 3.3 and neural-search present."""
    client = FakeOSClient(
        version="3.3.0",
        plugins=["opensearch-knn", "opensearch-neural-search", "opensearch-ml"],
    )
    cap = detect_capabilities(client)

    assert cap.version == "3.3.0"
    assert cap.dense_knn is True
    assert cap.sparse_rank_features is True
    assert cap.hybrid is True
    assert cap.sparse_ann is True  # 3.3.0 >= 3.3 → SEISMIC available


def test_only_knn_plugin():
    """Only opensearch-knn → dense True, sparse/hybrid False."""
    client = FakeOSClient(
        version="2.17.1",
        plugins=["opensearch-knn"],
        ml_model_ids=[],
    )
    cap = detect_capabilities(client)

    assert cap.dense_knn is True
    assert cap.sparse_rank_features is False
    assert cap.sparse_ann is False
    assert cap.hybrid is False
    assert cap.knn_engines == ("lucene", "faiss", "nmslib")
    assert "fp32" in cap.quantization
    assert "fp16" in cap.quantization
    assert len(cap.sparse_models) == 0


def test_no_plugins():
    """No plugins → all capabilities False, notes non-empty."""
    client = FakeOSClient(
        version="2.17.1",
        plugins=[],
        ml_model_ids=[],
    )
    cap = detect_capabilities(client)

    assert cap.dense_knn is False
    assert cap.sparse_rank_features is False
    assert cap.sparse_ann is False
    assert cap.hybrid is False
    assert cap.knn_engines == ()
    assert cap.quantization == ()
    assert len(cap.sparse_models) == 0
    assert len(cap.notes) > 0
    assert any("No plugins detected" in n for n in cap.notes)


def test_old_version_no_fp16():
    """Version < 2.13 → only fp32 quantization."""
    client = FakeOSClient(
        version="2.10.0",
        plugins=["opensearch-knn"],
        ml_model_ids=[],
    )
    cap = detect_capabilities(client)

    assert cap.dense_knn is True
    assert cap.quantization == ("fp32",)
    assert "fp16" not in cap.quantization
    assert any("Quantization detection conservative" in n for n in cap.notes)


def test_version_gte():
    """Semver component-wise comparison."""
    # Equal
    assert _version_gte("3.3.0", "3.3") is True
    assert _version_gte("2.13.0", "2.13") is True

    # Greater major
    assert _version_gte("3.0.0", "2.99") is True

    # Greater minor (IMPORTANT: 3.10 > 3.3 numerically, not string-wise)
    assert _version_gte("3.10.0", "3.3") is True
    assert _version_gte("2.19.1", "2.13") is True

    # Less than
    assert _version_gte("2.19.1", "3.3") is False
    assert _version_gte("2.12.0", "2.13") is False
    assert _version_gte("3.2.0", "3.3") is False

    # Edge cases
    assert _version_gte("3.3", "3.3.0") is True
    assert _version_gte("3.3.0", "3.3.0") is True
    assert _version_gte("10.0.0", "9.99.99") is True

    # Parse failures / edge cases
    assert _version_gte("unknown", "3.3") is False
    assert _version_gte("", "3.3") is False
    # Real OpenSearch versions are numeric; non-digit prefixes are gracefully rejected
    assert _version_gte("3.3.0-SNAPSHOT", "3.3") is True  # digits extracted


def test_supports_method():
    """Capabilities.supports(mode) routing."""
    cap = Capabilities(
        version="3.3.0",
        dense_knn=True,
        sparse_rank_features=True,
        sparse_ann=True,
        hybrid=True,
    )
    assert cap.supports(Mode.DENSE_KNN) is True
    assert cap.supports(Mode.SPARSE_RANK_FEATURES) is True
    assert cap.supports(Mode.SPARSE_ANN) is True
    assert cap.supports(Mode.HYBRID) is True

    cap_dense_only = Capabilities(
        version="2.10.0",
        dense_knn=True,
        sparse_rank_features=False,
        sparse_ann=False,
        hybrid=False,
    )
    assert cap_dense_only.supports(Mode.DENSE_KNN) is True
    assert cap_dense_only.supports(Mode.SPARSE_RANK_FEATURES) is False
    assert cap_dense_only.supports(Mode.SPARSE_ANN) is False
    assert cap_dense_only.supports(Mode.HYBRID) is False


def test_capability_summary_output():
    """capability_summary produces skimmable output."""
    cap = Capabilities(
        version="3.3.0",
        dense_knn=True,
        sparse_rank_features=True,
        sparse_ann=True,
        hybrid=True,
        knn_engines=("lucene", "faiss"),
        quantization=("fp32", "fp16"),
        sparse_models=("sparse-doc-v3", "sparse-bi-v2"),
        notes=("This is a test note.",),
    )
    summary = capability_summary(cap)

    assert "3.3.0" in summary
    assert "Dense k-NN" in summary
    assert "lucene, faiss" in summary
    assert "fp32, fp16" in summary
    assert "Sparse (rank_features, exact)" in summary
    assert "Sparse ANN (sparse_vector/SEISMIC, approximate)" in summary
    assert "Hybrid" in summary
    assert "sparse-doc-v3" in summary
    assert "sparse-bi-v2" in summary
    assert "This is a test note." in summary


def test_capability_summary_no_features():
    """capability_summary with no features shows clean ✗ messages."""
    cap = Capabilities(
        version="2.0.0",
        dense_knn=False,
        sparse_rank_features=False,
        sparse_ann=False,
        hybrid=False,
        notes=("No plugins detected; cluster may not support k-NN or neural search.",),
    )
    summary = capability_summary(cap)

    assert "✗ Dense k-NN" in summary
    assert "✗ Sparse (rank_features)" in summary
    assert "✗ Sparse ANN (SEISMIC)" in summary
    assert "✗ Hybrid" in summary
    assert "No plugins detected" in summary
