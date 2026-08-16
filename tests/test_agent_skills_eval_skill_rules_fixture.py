"""Tests for tests/evals/fixtures/skill_rules.json — the case shape.

Dependency-free: no deepeval, no Bedrock, no LLM. This exists because the
eval harness reads most of a case's keys only *after* both model calls have
been paid for, so a typo in a fixture is billed before it is noticed. Every
check here is one the harness would otherwise make at spend time.
"""

import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = _REPO_ROOT / "tests" / "evals" / "fixtures" / "skill_rules.json"
_SKILLS_ROOT = _REPO_ROOT / "skills"

# Read by unconditional subscript in tests/evals/test_skill_rules.py:
# id at collection, skill/prompt/criteria at call time, rule/rationale only
# after the judge has run.
_REQUIRED_KEYS = ("id", "skill", "prompt", "rule", "criteria", "rationale")

_CASES = json.loads(_FIXTURE.read_text())
# Built defensively so a malformed entry reaches its assertion instead of
# raising at import and taking the whole module's collection with it.
_IDS = [
    c.get("id", f"<no-id-{i}>") if isinstance(c, dict) else f"<not-an-object-{i}>"
    for i, c in enumerate(_CASES)
]


def _skill_dirs() -> set[str]:
    """Directory names the harness's _find_skill_dir can resolve."""
    return {p.parent.name for p in _SKILLS_ROOT.rglob("SKILL.md")}


def test_fixture_is_a_list_of_objects():
    assert isinstance(_CASES, list) and _CASES
    assert all(isinstance(c, dict) for c in _CASES)


def test_case_ids_are_unique():
    # pytest silently disambiguates duplicate param ids, so nothing else
    # would catch a copy-paste.
    duplicates = {i for i in _IDS if _IDS.count(i) > 1}
    assert not duplicates, f"duplicate case ids: {sorted(duplicates)}"


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_case_carries_every_required_key(case):
    missing = [k for k in _REQUIRED_KEYS if not case.get(k)]
    assert not missing, f"missing or empty: {missing}"
    assert all(isinstance(case[k], str) for k in _REQUIRED_KEYS)


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_case_names_a_real_skill(case):
    # load_skill_md matches on the directory holding SKILL.md, so
    # "search/ubi" raises FileNotFoundError where "ubi" resolves.
    assert case["skill"] in _skill_dirs()


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_case_references_resolve(case):
    # A reference that resolves to nothing used to load nothing, silently, and
    # the case was billed anyway while measuring the skill without the guide
    # it names. Names must be unique across the tree, since that is all the
    # harness has to go on.
    for ref in case.get("references", []):
        matches = sorted(_SKILLS_ROOT.rglob(ref))
        assert matches, f"reference '{ref}' is not anywhere under {_SKILLS_ROOT}"
        assert len(matches) == 1, (
            f"reference '{ref}' is ambiguous: "
            + ", ".join(str(m.relative_to(_SKILLS_ROOT)) for m in matches)
        )
