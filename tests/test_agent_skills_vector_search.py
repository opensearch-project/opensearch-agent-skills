"""Tests for the opensearch-vector-search skill assets."""

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_DIR = _REPO_ROOT / "skills" / "opensearch-skills" / "search" / "opensearch-vector-search"


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
