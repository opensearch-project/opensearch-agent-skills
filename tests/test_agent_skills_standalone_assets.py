"""Tests that the agent skill is fully standalone — UI and sample data are
bundled inside skills/opensearch-skills/ and resolve without depending on
the repo-root opensearch_orchestrator/ tree."""

import sys
from pathlib import Path

import pytest

_SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills"
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"

sys.path.insert(0, str(_SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# UI static assets
# ---------------------------------------------------------------------------
class TestUIAssetsStandalone:
    """Verify the UI files exist inside the skill and that ui.py resolves them."""

    EXPECTED_UI_FILES = ["index.html", "styles.css", "app.jsx"]

    def test_ui_directory_exists(self):
        ui_dir = _SCRIPTS_DIR / "ui"
        assert ui_dir.is_dir(), f"UI directory missing: {ui_dir}"

    @pytest.mark.parametrize("filename", EXPECTED_UI_FILES)
    def test_ui_file_exists(self, filename):
        path = _SCRIPTS_DIR / "ui" / filename
        assert path.is_file(), f"UI file missing: {path}"

    @pytest.mark.parametrize("filename", EXPECTED_UI_FILES)
    def test_ui_file_not_empty(self, filename):
        path = _SCRIPTS_DIR / "ui" / filename
        assert path.stat().st_size > 0, f"UI file is empty: {path}"

    def test_ui_py_resolves_to_local_dir(self):
        from lib.ui import SEARCH_UI_STATIC_DIR

        assert SEARCH_UI_STATIC_DIR.exists(), (
            f"SEARCH_UI_STATIC_DIR does not exist: {SEARCH_UI_STATIC_DIR}"
        )
        # Must point inside the skill, not to opensearch_orchestrator/
        assert "opensearch_orchestrator" not in str(SEARCH_UI_STATIC_DIR), (
            f"SEARCH_UI_STATIC_DIR still points outside the skill: {SEARCH_UI_STATIC_DIR}"
        )

    def test_ui_py_static_dir_contains_all_files(self):
        from lib.ui import SEARCH_UI_STATIC_DIR

        for filename in self.EXPECTED_UI_FILES:
            assert (SEARCH_UI_STATIC_DIR / filename).is_file(), (
                f"SEARCH_UI_STATIC_DIR is missing {filename}"
            )


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------
class TestSampleDataStandalone:
    """Verify IMDB sample data is bundled and samples.py finds it locally."""

    IMDB_TSV = _SCRIPTS_DIR / "sample_data" / "imdb.title.basics.tsv"

    def test_sample_data_directory_exists(self):
        assert (_SCRIPTS_DIR / "sample_data").is_dir()

    def test_imdb_tsv_exists(self):
        assert self.IMDB_TSV.is_file(), f"IMDB TSV missing: {self.IMDB_TSV}"

    def test_imdb_tsv_not_empty(self):
        assert self.IMDB_TSV.stat().st_size > 0

    def test_imdb_tsv_has_header_row(self):
        with open(self.IMDB_TSV, "r") as f:
            header = f.readline().strip()
        assert "tconst" in header, f"Unexpected header: {header}"

    def test_load_sample_builtin_imdb_succeeds(self):
        import json
        from lib.samples import load_sample_builtin_imdb

        result = json.loads(load_sample_builtin_imdb())
        assert "error" not in result, f"load_sample_builtin_imdb failed: {result}"
        assert result["status"] == "loaded"
        assert result["record_count"] > 0

    def test_builtin_imdb_resolves_to_local_path(self):
        import json
        from lib.samples import load_sample_builtin_imdb

        result = json.loads(load_sample_builtin_imdb())
        source = result.get("source", "")
        # Must resolve inside the skill, not opensearch_orchestrator/
        assert "opensearch_orchestrator" not in source, (
            f"IMDB sample resolved outside the skill: {source}"
        )


# ---------------------------------------------------------------------------
# Simulated install location (mimics .claude/skills/)
# ---------------------------------------------------------------------------
class TestResolvedPathsAreRelative:
    """Ensure path resolution uses only relative traversal from __file__,
    not hardcoded repo-root assumptions."""

    def test_ui_static_dir_is_under_skill_root(self):
        from lib.ui import SEARCH_UI_STATIC_DIR

        resolved = SEARCH_UI_STATIC_DIR.resolve()
        assert str(resolved).startswith(str(_SCRIPTS_DIR)), (
            f"SEARCH_UI_STATIC_DIR escapes the scripts dir: {resolved}"
        )

    def test_samples_imdb_candidates_are_under_skill_root(self):
        """Check that the candidate paths in load_sample_builtin_imdb
        stay within the skill tree."""
        import inspect
        from lib.samples import load_sample_builtin_imdb

        source = inspect.getsource(load_sample_builtin_imdb)
        assert "opensearch_orchestrator" not in source, (
            "load_sample_builtin_imdb still references opensearch_orchestrator path"
        )
