"""Tests for the opensearch-vector-search skill assets."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_DIR = _REPO_ROOT / "skills" / "opensearch-skills" / "search" / "opensearch-vector-search"


def _load_script(name: str):
    path = _SKILL_DIR / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_vector_search_reference_files_are_bundled():
    expected = {
        "vector-search.md",
        "quantization-techniques.md",
        "cost-optimization.md",
        "cluster-tuning.md",
        "performance-benchmarks.md",
        "indexing-strategies.md",
        "query-optimization.md",
        "optimized-instances.md",
    }

    actual = {path.name for path in (_SKILL_DIR / "references").glob("*.md")}

    assert expected <= actual


def test_analyzer_help_does_not_require_cluster_or_opensearchpy():
    result = subprocess.run(
        [sys.executable, str(_SKILL_DIR / "scripts" / "analyze_cluster.py"), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "READ-ONLY" in result.stdout
    assert "--action" in result.stdout


def test_analyzer_normalizes_knn_and_doc_count_values():
    analyzer = _load_script("analyze_cluster.py")
    recommendations = []

    analyzer._analyze_index_config(
        {
            "index": "vectors",
            "settings": {"knn": True},
            "vector_fields": [
                {
                    "name": "embedding",
                    "data_type": "float",
                }
            ],
            "stats": {"docs_count": "10000001"},
        },
        recommendations,
    )

    assert not any(item["category"] == "knn_setting" for item in recommendations)
    assert any(item["category"] == "quantization" for item in recommendations)


def test_analyzer_uses_tls_verification_by_default():
    analyzer = _load_script("analyze_cluster.py")
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    analyzer.OpenSearch = FakeClient
    analyzer.RequestsHttpConnection = object
    analyzer.create_client("https://cluster.example")

    assert captured["verify_certs"] is True
    assert captured["ssl_show_warn"] is False


def test_pricing_help_does_not_require_boto3_or_aws_credentials():
    result = subprocess.run(
        [sys.executable, str(_SKILL_DIR / "scripts" / "get_opensearch_pricing.py"), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--region" in result.stdout
    assert "--instance-type" in result.stdout


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("r7g.xlarge", "r7g.xlarge.search"),
        ("r7g.xlarge.search", "r7g.xlarge.search"),
    ],
)
def test_pricing_normalizes_instance_type(value, expected):
    pricing = _load_script("get_opensearch_pricing.py")

    assert pricing.normalize_instance_type(value) == expected


def test_pricing_rejects_instance_type_without_size():
    pricing = _load_script("get_opensearch_pricing.py")

    with pytest.raises(ValueError, match="family and size"):
        pricing.normalize_instance_type("r7g")
