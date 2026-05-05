"""Spec compliance tests for all SKILL.md files in the skills/ tree.

Validates every SKILL.md against the agentskills.io specification:
  https://agentskills.io/specification

Rules enforced:
  - Required fields: name, description
  - name: 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing
    or consecutive hyphens, must match the parent directory name
  - description: 1-1024 chars, non-empty
  - compatibility: if present, 1-500 chars
  - SKILL.md body: under 500 lines
  - File references ([text](path)): all relative paths must resolve

No cluster, no network, no LLM — pure filesystem checks.
"""

import re
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SKILLS_ROOT = _REPO_ROOT / "skills"

# Spec limits
_MAX_NAME_LEN = 64
_MAX_DESC_LEN = 1024
_MAX_COMPAT_LEN = 500
_MAX_BODY_LINES = 500

# Valid name pattern per spec: lowercase alphanumeric + hyphens,
# no leading/trailing hyphens, no consecutive hyphens.
_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")

# Markdown link pattern: [text](path) — captures the path portion.
# Excludes http/https URLs (those are external links, not file refs).
_MD_LINK_RE = re.compile(r"\[(?:[^\]]*)\]\((?!https?://)([^)#\s]+)")


def _collect_skill_mds() -> list[Path]:
    """Return all SKILL.md paths under skills/, sorted for stable ordering.

    Skills listed in _SKIP_SKILLS are excluded from compliance checks.
    """
    return sorted(
        p for p in _SKILLS_ROOT.rglob("SKILL.md")
        if p.parent.name not in _SKIP_SKILLS
    )


# Skills excluded from spec compliance checks.
# Add a skill's directory name here to skip it temporarily.
_SKIP_SKILLS: frozenset[str] = frozenset({
    "solr-opensearch-migration-advisor",
})


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter_dict, body_text).

    Returns ({}, body) if the file has no YAML frontmatter block.
    Raises yaml.YAMLError if the frontmatter is malformed.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text

    # Find the closing ---
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    fm = yaml.safe_load(fm_text) or {}
    return fm, body


# Parametrize over every SKILL.md found in the repo.
_ALL_SKILL_MDS = _collect_skill_mds()


# ---------------------------------------------------------------------------
# Frontmatter presence
# ---------------------------------------------------------------------------


class TestFrontmatterPresence:
    """Every SKILL.md must have a parseable YAML frontmatter block."""

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_has_frontmatter(self, skill_path):
        text = skill_path.read_text(encoding="utf-8")
        assert text.startswith("---"), (
            f"{skill_path.relative_to(_REPO_ROOT)}: SKILL.md must start with '---' "
            f"YAML frontmatter"
        )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_frontmatter_is_valid_yaml(self, skill_path):
        try:
            fm, _ = _parse_frontmatter(skill_path)
        except yaml.YAMLError as exc:
            pytest.fail(
                f"{skill_path.relative_to(_REPO_ROOT)}: frontmatter is not valid YAML: {exc}"
            )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_frontmatter_is_a_mapping(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        assert isinstance(fm, dict), (
            f"{skill_path.relative_to(_REPO_ROOT)}: frontmatter must be a YAML mapping, "
            f"got {type(fm).__name__}"
        )


# ---------------------------------------------------------------------------
# Required field: name
# ---------------------------------------------------------------------------


class TestNameField:
    """Validate the required 'name' field."""

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_name_present(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        assert "name" in fm, (
            f"{skill_path.relative_to(_REPO_ROOT)}: missing required 'name' field"
        )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_name_is_string(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        name = fm.get("name")
        assert isinstance(name, str) and name.strip(), (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'name' must be a non-empty string, "
            f"got {name!r}"
        )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_name_max_length(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        name = str(fm.get("name", ""))
        assert len(name) <= _MAX_NAME_LEN, (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'name' is {len(name)} chars, "
            f"max is {_MAX_NAME_LEN}"
        )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_name_character_set(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        name = str(fm.get("name", ""))
        if not name:
            pytest.skip("name absent — covered by test_name_present")
        assert _NAME_RE.match(name), (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'name' {name!r} contains invalid "
            f"characters. Must be lowercase alphanumeric + hyphens, no leading/trailing "
            f"or consecutive hyphens."
        )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_name_matches_directory(self, skill_path):
        """The name field must equal the parent directory name (spec requirement)."""
        fm, _ = _parse_frontmatter(skill_path)
        name = str(fm.get("name", ""))
        dir_name = skill_path.parent.name
        assert name == dir_name, (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'name' {name!r} does not match "
            f"parent directory {dir_name!r}"
        )


# ---------------------------------------------------------------------------
# Required field: description
# ---------------------------------------------------------------------------


class TestDescriptionField:
    """Validate the required 'description' field."""

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_description_present(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        assert "description" in fm, (
            f"{skill_path.relative_to(_REPO_ROOT)}: missing required 'description' field"
        )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_description_non_empty(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        desc = str(fm.get("description", "")).strip()
        assert desc, (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'description' must not be empty"
        )

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_description_max_length(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        desc = str(fm.get("description", ""))
        assert len(desc) <= _MAX_DESC_LEN, (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'description' is {len(desc)} chars, "
            f"max is {_MAX_DESC_LEN}"
        )


# ---------------------------------------------------------------------------
# Optional field: compatibility
# ---------------------------------------------------------------------------


class TestCompatibilityField:
    """If present, compatibility must be 1-500 chars."""

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_compatibility_max_length(self, skill_path):
        fm, _ = _parse_frontmatter(skill_path)
        compat = fm.get("compatibility")
        if compat is None:
            return  # field is optional
        compat_str = str(compat).strip()
        assert compat_str, (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'compatibility' is present but empty; "
            f"either remove it or provide a value"
        )
        assert len(compat_str) <= _MAX_COMPAT_LEN, (
            f"{skill_path.relative_to(_REPO_ROOT)}: 'compatibility' is {len(compat_str)} "
            f"chars, max is {_MAX_COMPAT_LEN}"
        )


# ---------------------------------------------------------------------------
# Body line count
# ---------------------------------------------------------------------------


class TestBodyLineCount:
    """SKILL.md body (after frontmatter) must be under 500 lines."""

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_body_under_500_lines(self, skill_path):
        _, body = _parse_frontmatter(skill_path)
        lines = body.splitlines()
        assert len(lines) <= _MAX_BODY_LINES, (
            f"{skill_path.relative_to(_REPO_ROOT)}: body is {len(lines)} lines, "
            f"max is {_MAX_BODY_LINES}. Move detailed content to reference files."
        )


# ---------------------------------------------------------------------------
# File references
# ---------------------------------------------------------------------------


class TestFileReferences:
    """All relative file references in SKILL.md must resolve to real files."""

    @pytest.mark.parametrize("skill_path", _ALL_SKILL_MDS, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
    def test_relative_file_references_resolve(self, skill_path):
        _, body = _parse_frontmatter(skill_path)
        skill_dir = skill_path.parent
        broken: list[str] = []

        for match in _MD_LINK_RE.finditer(body):
            ref = match.group(1)
            # Skip anchors-only and mailto links
            if ref.startswith("#") or ref.startswith("mailto:"):
                continue
            target = (skill_dir / ref).resolve()
            if not target.exists():
                broken.append(ref)

        assert not broken, (
            f"{skill_path.relative_to(_REPO_ROOT)}: broken file reference(s): "
            + ", ".join(broken)
        )
