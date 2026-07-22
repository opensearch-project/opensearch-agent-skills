"""Eval tests: skill routing accuracy.

Tests that the top-level opensearch-skills router correctly identifies
which leaf skill to activate for a given user prompt.

The router skill's SKILL.md is used as the system prompt. The LLM response
is checked for the expected skill name. Results are aggregated across all
cases and a minimum accuracy threshold is enforced.

Run:
    uv run --group evals pytest tests/evals/test_skill_routing.py --run-eval -v
    uv run --group evals pytest tests/evals/test_skill_routing.py --run-eval-analysis
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("pytest_evals", reason="evals group not installed — run with: uv run --group evals pytest tests/evals/")
from pytest_evals import eval_bag  # noqa: F401 — fixture injected by plugin

from tests.evals.conftest import call_skill, load_skill_md, _BEDROCK_JUDGE_MODEL_ID

_FIXTURES = Path(__file__).parent / "fixtures" / "routing.json"
_CASES = json.loads(_FIXTURES.read_text())

# Minimum fraction of routing cases that must pass.
_ACCURACY_THRESHOLD = 0.80


# ---------------------------------------------------------------------------
# Eval phase — one test per golden case
# ---------------------------------------------------------------------------

@pytest.mark.eval(name="skill_routing")
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_skill_routing(case, eval_bag, bedrock_client):  # noqa: F811
    """Ask the router skill which sub-skill to use, check it names the right one."""
    if bedrock_client is None:
        pytest.skip("AWS Bedrock credentials not available")
    router_skill = load_skill_md("opensearch-skills")

    # Ask the router to identify the right skill for this prompt.
    # Wrap the prompt so the model is forced to name a skill explicitly.
    wrapped_prompt = (
        f"{case['prompt']}\n\n"
        "Which skill should handle this request? "
        "Reply with the skill name (e.g. opensearch-launchpad, log-analytics, "
        "trace-analytics, aws-setup, managed-ingestion-service, document-processing) and a brief explanation."
    )
    # STOPGAP: use Haiku, not the default Sonnet — eval CI role only
    # allowlists Haiku for now. Revert once IAM allows Sonnet too.
    response = call_skill(router_skill, wrapped_prompt, bedrock_client, model_id=_BEDROCK_JUDGE_MODEL_ID)

    routed_correctly = case["expected_skill"] in response.lower().replace("-", "-")

    # Store everything in eval_bag for the analysis phase.
    eval_bag.case_id = case["id"]
    eval_bag.prompt = case["prompt"]
    eval_bag.expected_skill = case["expected_skill"]
    eval_bag.response = response
    eval_bag.routed_correctly = routed_correctly
    eval_bag.rationale = case["rationale"]


# ---------------------------------------------------------------------------
# Analysis phase — aggregate pass rate across all cases
# ---------------------------------------------------------------------------

@pytest.mark.eval_analysis(name="skill_routing")
def test_routing_accuracy(eval_results):
    """Enforce a minimum routing accuracy across all golden cases."""
    if not eval_results:
        pytest.skip("No eval results to analyze")

    # If all cases were skipped (no credentials), eval_bags will be empty.
    ran = [r for r in eval_results if hasattr(r.result, "routed_correctly")]
    if not ran:
        pytest.skip("All eval cases were skipped (no AWS credentials available)")

    correct = [r for r in ran if r.result.routed_correctly]
    accuracy = len(correct) / len(ran)

    # Print a per-case breakdown for easy debugging.
    print(f"\n{'─' * 60}")
    print(f"Skill routing accuracy: {accuracy:.0%} ({len(correct)}/{len(eval_results)})")
    print(f"{'─' * 60}")
    for r in ran:
        status = "✓" if r.result.routed_correctly else "✗"
        print(f"  {status} [{r.result.case_id}] expected={r.result.expected_skill}")
        if not r.result.routed_correctly:
            snippet = r.result.response[:200].replace("\n", " ")
            print(f"      response: {snippet}...")

    assert accuracy >= _ACCURACY_THRESHOLD, (
        f"Routing accuracy {accuracy:.0%} is below the {_ACCURACY_THRESHOLD:.0%} threshold. "
        f"Failed cases: {[r.result.case_id for r in ran if not r.result.routed_correctly]}"
    )
