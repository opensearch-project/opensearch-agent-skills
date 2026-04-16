"""Tests that the agent skill is fully standalone — UI and sample data are
bundled inside skills/opensearch-skills/ and resolve without depending on
the repo-root opensearch_orchestrator/ tree."""

import re
import sys
from pathlib import Path

import pytest

_SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills"
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"
_UI_DIR = _SCRIPTS_DIR / "ui"

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


# ---------------------------------------------------------------------------
# Frontend — agentic fallback warning condition
# ---------------------------------------------------------------------------
_APP_JSX = _UI_DIR / "app.jsx"


@pytest.fixture(scope="module")
def app_jsx_content():
    assert _APP_JSX.exists(), f"app.jsx not found at {_APP_JSX}"
    return _APP_JSX.read_text()


class TestAgenticFallbackWarningCondition:
    def test_fallback_warning_requires_no_dsl_query(self, app_jsx_content):
        """The agentic fallback warning must check !dslQuery so it is hidden
        when the flow agent successfully returns a translated DSL query."""
        lines = app_jsx_content.splitlines()
        fallback_line = None
        for i, line in enumerate(lines):
            if "agentic-fallback-warning" in line or "AI agent unavailable" in line:
                for j in range(max(0, i - 3), i + 1):
                    if "activeTemplate" in lines[j] and "agent" in lines[j]:
                        fallback_line = lines[j]
                        break
                if fallback_line:
                    break

        assert fallback_line is not None, "Could not find agentic fallback warning condition"
        assert "!dslQuery" in fallback_line, (
            "Fallback warning condition must include !dslQuery to hide when "
            "flow agent returns a DSL query"
        )

    def test_fallback_warning_checks_rag_answer(self, app_jsx_content):
        lines = app_jsx_content.splitlines()
        for i, line in enumerate(lines):
            if "agentic-fallback-warning" in line:
                context = "\n".join(lines[max(0, i - 5):i + 1])
                assert "!ragAnswer" in context
                return
        pytest.fail("Could not find agentic-fallback-warning in app.jsx")

    def test_fallback_warning_checks_agent_steps_summary(self, app_jsx_content):
        lines = app_jsx_content.splitlines()
        for i, line in enumerate(lines):
            if "agentic-fallback-warning" in line:
                context = "\n".join(lines[max(0, i - 5):i + 1])
                assert "!agentStepsSummary" in context
                return
        pytest.fail("Could not find agentic-fallback-warning in app.jsx")


# ---------------------------------------------------------------------------
# Frontend — DSL query display
# ---------------------------------------------------------------------------
class TestDslQueryDisplay:
    def test_dsl_query_shown_in_agent_search_results(self, app_jsx_content):
        assert "dslQuery" in app_jsx_content, "dslQuery state variable should exist"
        assert "chat-reasoning-pre" in app_jsx_content, "DSL query should render in a pre block"

    def test_dsl_query_state_initialized(self, app_jsx_content):
        assert 'useState("")' in app_jsx_content or "useState('')" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — agentic mode toggle
# ---------------------------------------------------------------------------
class TestAgenticModeToggle:
    def test_agentic_mode_state_exists(self, app_jsx_content):
        assert "agenticMode" in app_jsx_content

    def test_agentic_mode_default_is_search(self, app_jsx_content):
        agentic_mode_lines = [
            line for line in app_jsx_content.splitlines()
            if "agenticMode" in line and "useState" in line
        ]
        assert len(agentic_mode_lines) > 0
        assert any("search" in line for line in agentic_mode_lines)

    def test_chat_mode_available(self, app_jsx_content):
        assert '"chat"' in app_jsx_content or "'chat'" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — agent template routing
# ---------------------------------------------------------------------------
class TestAgentTemplateRouting:
    def test_agent_template_triggers_agentic_search(self, app_jsx_content):
        agent_lines = [
            line for line in app_jsx_content.splitlines()
            if 'activeTemplate === "agent"' in line or "activeTemplate === 'agent'" in line
        ]
        assert len(agent_lines) > 0, "UI should check for agent template"

    def test_agent_chat_mode_runs_agent_search(self, app_jsx_content):
        assert "runAgentSearch" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — API response field mapping
# ---------------------------------------------------------------------------
class TestApiResponseFieldMapping:
    def test_dsl_query_read_from_response(self, app_jsx_content):
        assert "data.dsl_query" in app_jsx_content or 'data["dsl_query"]' in app_jsx_content

    def test_agentic_agent_type_read_from_schema(self, app_jsx_content):
        assert "agentic_agent_type" in app_jsx_content


# ---------------------------------------------------------------------------
# Frontend — CSS classes
# ---------------------------------------------------------------------------
class TestAgenticCssClasses:
    @pytest.fixture(scope="class")
    def styles_css(self):
        css_path = _UI_DIR / "styles.css"
        assert css_path.exists(), f"styles.css not found at {css_path}"
        return css_path.read_text()

    def test_agentic_fallback_warning_styled(self, styles_css):
        assert ".agentic-fallback-warning" in styles_css

    def test_agentic_mode_toggle_styled(self, styles_css):
        assert ".agentic-mode-toggle" in styles_css

    def test_agentic_mode_btn_styled(self, styles_css):
        assert ".agentic-mode-btn" in styles_css

    def test_agentic_capability_pill_styled(self, styles_css):
        assert ".cap-agentic" in styles_css
