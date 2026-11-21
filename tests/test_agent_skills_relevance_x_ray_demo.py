"""Offline contract tests for the Relevance X-Ray Docker demo."""

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import yaml
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_DIR = (
    _REPO_ROOT
    / "skills"
    / "opensearch-skills"
    / "search"
    / "relevance-x-ray"
)
_EXAMPLES = _SKILL_DIR / "examples"
_FIXTURES = _EXAMPLES / "fixtures"
_DOCKER = _EXAMPLES / "docker"
_SCRIPTS_DIR = _SKILL_DIR / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from relevance_xray_lib.synonym_suggester import mine_candidate_synonyms


def _documents() -> dict[str, dict]:
    lines = [
        json.loads(line)
        for line in (_FIXTURES / "documents.ndjson").read_text().splitlines()
        if line.strip()
    ]
    assert len(lines) % 2 == 0
    documents = {}
    for action, document in zip(lines[0::2], lines[1::2]):
        doc_id = str(action["index"]["_id"])
        assert action["index"]["_index"] == "relevance-x-ray-demo"
        assert doc_id not in documents
        documents[doc_id] = document
    return documents


def _simple_terms(document: dict) -> list[str]:
    text = " ".join(
        str(document.get(field, ""))
        for field in ("title", "description", "stemmed_text", "brand")
    )
    return re.findall(r"[a-z0-9]+", text.lower())


def test_demo_image_is_pinned_to_opensearch_3_8_0():
    dockerfile = (_DOCKER / "Dockerfile").read_text()
    assert "FROM opensearchproject/opensearch:3.8.0" in dockerfile
    assert ":latest" not in dockerfile


def test_compose_builds_one_seeded_service_on_nondefault_port():
    compose = yaml.safe_load((_DOCKER / "docker-compose.yml").read_text())
    service = compose["services"]["opensearch"]
    assert service["image"] == "relevance-x-ray-demo:3.8.0"
    assert service["build"]["context"] == ".."
    assert service["ports"] == ["127.0.0.1:${OPENSEARCH_PORT:-19200}:9200"]
    assert "relevance-x-ray-demo/_doc/1" in " ".join(
        service["healthcheck"]["test"]
    )


def test_fixture_mapping_and_vectors_are_consistent():
    index = json.loads((_FIXTURES / "index.json").read_text())
    properties = index["mappings"]["properties"]
    assert index["settings"]["index"]["knn"] is True
    assert properties["embedding"]["type"] == "knn_vector"
    assert properties["embedding"]["dimension"] == 3
    assert properties["stemmed_text"]["analyzer"] == "english"
    assert properties["stemmed_text"]["search_analyzer"] == "standard"
    assert properties["brand"]["type"] == "text"
    assert "fields" not in properties["brand"]
    assert properties["popularity"]["index"] is False
    assert properties["popularity"].get("doc_values", True) is True

    documents = _documents()
    assert len(documents) == 10
    assert all(len(document["embedding"]) == 3 for document in documents.values())


def test_fixture_corpus_supports_trainers_synonym_by_distinct_documents():
    documents = _documents()
    corpus = [_simple_terms(document) for document in documents.values()]
    candidates = mine_candidate_synonyms(
        query_term="sneakers",
        target_doc_terms=_simple_terms(documents["1"]),
        corpus_term_lists=corpus,
        min_support=2,
    )
    assert candidates
    assert candidates[0].candidate == "trainers"
    assert candidates[0].support == 2


def test_demo_scripts_are_executable_and_use_current_cli_flags():
    for path in (
        _EXAMPLES / "seed-demo.sh",
        _EXAMPLES / "demo_index_setup.sh",
        _DOCKER / "demo-entrypoint.sh",
        _DOCKER / "run-demo.sh",
    ):
        if os.name != "nt":
            assert path.stat().st_mode & stat.S_IXUSR, f"{path} is not executable"

    runner = (_DOCKER / "run-demo.sh").read_text()
    assert "--exact-fields" not in runner
    for command in (
        "abstention",
        "analyzer",
        "mapping",
        "scoring",
        "doc-values",
        "synonym",
        "knn",
        "hybrid",
    ):
        assert f"{command})" in runner


def test_playbook_documents_automated_test_and_cleanup():
    playbook = (_SKILL_DIR / "demo-playbook.md").read_text()
    assert "run-demo.sh test" in playbook
    assert "run-demo.sh down" in playbook
    assert "OpenSearch 3.8.0" in playbook


def test_fixture_loader_refuses_remote_reset_without_explicit_override():
    loader = (_EXAMPLES / "seed-demo.sh").read_text()
    assert "ALLOW_REMOTE_DEMO_RESET" in loader
    assert "Refusing to reset demo resources on non-loopback endpoint" in loader


@pytest.mark.skipif(os.name == "nt", reason="Bash is not part of Windows CI")
def test_demo_wrapper_rejects_malformed_host_before_building_url():
    env = {
        **os.environ,
        "ALLOW_REMOTE_DEMO_RESET": "true",
        "DEMO_WAIT_SECONDS": "0",
    }

    result = subprocess.run(
        ["bash", str(_EXAMPLES / "demo_index_setup.sh"), "127.0.0.1/path", "9200"],
        capture_output=True,
        check=False,
        env=env,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert "Invalid OpenSearch host" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Bash is not part of Windows CI")
def test_fixture_loader_exits_before_contacting_remote_endpoint():
    result = subprocess.run(
        ["bash", str(_EXAMPLES / "seed-demo.sh")],
        env={
            **os.environ,
            "OPENSEARCH_URL": "https://search.example.com:9200",
            "DEMO_WAIT_SECONDS": "1",
        },
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert "Refusing to reset demo resources" in result.stderr


def test_leaf_skill_bundles_its_cli_and_runtime_modules():
    cli = _SKILL_DIR / "scripts" / "relevance_x_ray.py"
    runtime = _SKILL_DIR / "scripts" / "relevance_xray_lib"

    assert cli.is_file()
    assert (runtime / "client.py").is_file()
    assert (runtime / "explain_parser.py").is_file()
    assert (runtime / "rules_engine.py").is_file()
