"""Asset contracts for the permission-aware-search skill.

The skill folder holds only markdown (SKILL.md + references/); its Python lives in
the shared ``skills/opensearch-skills/scripts/`` tree alongside the other CLIs, per
the DEVELOPER_GUIDE structure.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILL_DIR = (
    _REPO_ROOT
    / "skills"
    / "opensearch-skills"
    / "search"
    / "permission-aware-search"
)
_SCRIPTS_DIR = _REPO_ROOT / "skills" / "opensearch-skills" / "scripts"
_CLI = _SCRIPTS_DIR / "permission_search.py"
_FIXTURES = _REPO_ROOT / "tests" / "evals" / "fixtures"

# Markdown lives in the skill folder; Python lives in the shared scripts tree.
_REQUIRED_SKILL_ASSETS = {
    "SKILL.md",
    "references/cli-reference.md",
    "references/dls-model.md",
    "references/embedding-options.md",
    "references/index-mapping.md",
}
_REQUIRED_SCRIPT_ASSETS = {
    "permission_search.py",
    "lib/chunker.py",
    "lib/dls_manager.py",
    "lib/group_resolver.py",
    "lib/index_writer.py",
    "lib/os_client.py",
    "lib/search_runner.py",
}
_PERMISSION_RULE_IDS = {
    "permission-aware-security-preflight-first",
    "permission-aware-never-query-as-admin",
    "permission-aware-preserve-caller-identity",
    "permission-aware-authoritative-acl-membership",
    "permission-aware-one-question-at-a-time",
}
_PERMISSION_ROUTING_IDS = {
    "routing-permission-01",
    "routing-permission-02",
    "routing-permission-03",
}


def test_permission_skill_bundles_required_nonempty_assets():
    assert not (_SKILL_DIR / "reference").exists()
    # The skill folder is markdown-only; no bundled scripts remain.
    assert not (_SKILL_DIR / "scripts").exists()
    for relative_path in _REQUIRED_SKILL_ASSETS:
        path = _SKILL_DIR / relative_path
        assert path.is_file(), f"Missing skill asset: {relative_path}"
        assert path.stat().st_size > 0, f"Empty skill asset: {relative_path}"
    for relative_path in _REQUIRED_SCRIPT_ASSETS:
        path = _SCRIPTS_DIR / relative_path
        assert path.is_file(), f"Missing shared script asset: {relative_path}"
        assert path.stat().st_size > 0, f"Empty shared script asset: {relative_path}"


def test_permission_skill_python_assets_compile_without_writing_bytecode():
    for relative_path in _REQUIRED_SCRIPT_ASSETS:
        path = _SCRIPTS_DIR / relative_path
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_permission_skill_source_and_markdown_are_ascii():
    for path in _SKILL_DIR.rglob("*"):
        if path.suffix in {".md", ".py"}:
            path.read_text(encoding="ascii")
    for relative_path in _REQUIRED_SCRIPT_ASSETS:
        (_SCRIPTS_DIR / relative_path).read_text(encoding="ascii")


def test_permission_skill_requires_docker_only_for_local_features():
    skill = (_SKILL_DIR / "SKILL.md").read_text(encoding="ascii")
    normalized_skill = " ".join(skill.split())
    assert "Requires uv and an OpenSearch cluster with the security plugin." in normalized_skill
    assert "Local OpenSearch requires Docker." in normalized_skill
    assert "Local OpenSearch only: Docker installed and running" in skill
    assert "- Docker installed and running" not in skill


def test_root_readme_does_not_list_removed_permission_profile():
    readme = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "profiles/" not in readme


def test_top_level_feedback_policy_includes_permission_skill():
    top_level_skill = (
        _REPO_ROOT / "skills" / "opensearch-skills" / "SKILL.md"
    ).read_text(encoding="utf-8")
    feedback_policy = top_level_skill.split(
        "## Feedback Collection", 1
    )[1].split("## Shared Resources", 1)[0]
    assert "skills in this collection" in feedback_policy
    assert "permission-aware-search" in feedback_policy


def test_permission_cli_declares_only_core_runtime_dependency():
    source = _CLI.read_text(encoding="utf-8")
    metadata = source.split("# ///", 2)[1]
    assert '# dependencies = ["opensearch-py>=2.4"]' in metadata
    for dependency in ("docling", "boto3"):
        assert dependency not in metadata


def test_permission_docs_explain_optional_dependency_invocations():
    docs = "\n".join(
        (_SKILL_DIR / path).read_text(encoding="utf-8")
        for path in ("SKILL.md", "references/cli-reference.md")
    )
    # Optional features install via dependency groups in pyproject.toml.
    assert "--group ingestion" in docs  # Docling PDF/Office ingestion and Bedrock RAG


def test_permission_cli_builds_configuration_from_environment(monkeypatch):
    original_sys_path = sys.path[:]
    sys.path.insert(0, str(_SCRIPTS_DIR))
    try:
        import permission_search

        monkeypatch.setenv("OPENSEARCH_URL", "https://search.example:9200")
        monkeypatch.setenv("OPENSEARCH_INDEX", "documents")
        config = permission_search._runtime_config(SimpleNamespace(command="setup"))
    finally:
        sys.path[:] = original_sys_path

    assert config["opensearch"]["url"] == "https://search.example:9200"
    assert config["opensearch"]["index"] == "documents"


def test_permission_eval_fixtures_are_complete_without_running_cloud_evals():
    rules = json.loads((_FIXTURES / "skill_rules.json").read_text(encoding="utf-8"))
    routes = json.loads((_FIXTURES / "routing.json").read_text(encoding="utf-8"))

    assert len({case["id"] for case in rules}) == len(rules)
    assert len({case["id"] for case in routes}) == len(routes)
    permission_rules = {
        case["id"]: case
        for case in rules
        if case["skill"] == "permission-aware-search"
    }
    permission_routes = {
        case["id"]: case
        for case in routes
        if case["expected_skill"] == "permission-aware-search"
    }
    assert set(permission_rules) == _PERMISSION_RULE_IDS
    assert set(permission_routes) >= _PERMISSION_ROUTING_IDS

    for case in permission_rules.values():
        assert all(case.get(field) for field in ("prompt", "rule", "criteria", "rationale"))
        for reference in case.get("references", []):
            assert (_SKILL_DIR / reference).is_file(), reference

    for case in permission_routes.values():
        assert all(case.get(field) for field in ("prompt", "rationale"))
