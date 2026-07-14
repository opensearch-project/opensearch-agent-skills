"""Eval tests: skill instruction compliance (key rules) — LLM-as-judge.

Tests that each leaf skill's SKILL.md instructions cause the LLM to follow
the documented key rules. Uses DeepEval's GEval metric with AmazonBedrockModel
as the judge, which evaluates responses semantically rather than by keyword
matching.

Architecture:
  1. call_skill()  — runs the skill as a system prompt against a user prompt
                     (Haiku 4.5 via Bedrock, same model as routing tests)
  2. GEval judge   — a second Bedrock call evaluates whether the response
                     satisfies the rule criteria (Haiku 4.5 as judge)

Run:
    uv run --group evals pytest tests/evals/test_skill_rules.py --run-eval -v
    uv run --group evals pytest tests/evals/test_skill_rules.py --run-eval-analysis
"""

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("deepeval", reason="evals group not installed — run with: uv run --group evals pytest tests/evals/")
pytest.importorskip("pytest_evals", reason="evals group not installed — run with: uv run --group evals pytest tests/evals/")
from deepeval.metrics import GEval
from deepeval.models import AmazonBedrockModel
from deepeval.test_case import LLMTestCase, SingleTurnParams
from pytest_evals import eval_bag  # noqa: F401 — fixture injected by plugin

from tests.evals.conftest import call_skill, load_skill_md, load_skill_with_references, _BEDROCK_JUDGE_MODEL_ID, _BEDROCK_REGION

_FIXTURES = Path(__file__).parent / "fixtures" / "skill_rules.json"
_CASES = json.loads(_FIXTURES.read_text())

# Minimum fraction of rule-compliance cases that must pass.
_COMPLIANCE_THRESHOLD = 0.80

# GEval pass threshold: score ≥ 0.5 means the rule is satisfied.
_GEVAL_THRESHOLD = 0.5


def _make_judge(model_id: str = _BEDROCK_JUDGE_MODEL_ID, region: str = _BEDROCK_REGION) -> AmazonBedrockModel:
    """Return a DeepEval AmazonBedrockModel for use as a GEval judge.

    Falls back to the AWS default credentials chain (profile, env vars,
    instance metadata) — no explicit keys needed.
    """
    return AmazonBedrockModel(model=model_id, region=region)


# ---------------------------------------------------------------------------
# Eval phase — one test per golden case
# ---------------------------------------------------------------------------

@pytest.mark.eval(name="skill_rules")
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_skill_rule_compliance(case, eval_bag, bedrock_client):  # noqa: F811
    """Load the named skill, get a response, then judge it with GEval."""
    if bedrock_client is None:
        pytest.skip("AWS Bedrock credentials not available")
    skill_md = load_skill_with_references(case["skill"], case.get("references"))
    response = call_skill(skill_md, case["prompt"], bedrock_client)

    # Build a GEval metric with the rule's natural-language criteria.
    # The judge evaluates whether the response satisfies the criteria.
    judge = _make_judge()
    metric = GEval(
        name=f"RuleCompliance:{case['id']}",
        criteria=case["criteria"],
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        threshold=_GEVAL_THRESHOLD,
        model=judge,
        async_mode=False,
    )

    test_case = LLMTestCase(
        input=case["prompt"],
        actual_output=response,
    )
    metric.measure(test_case)

    passed = metric.score >= _GEVAL_THRESHOLD

    eval_bag.case_id = case["id"]
    eval_bag.skill = case["skill"]
    eval_bag.prompt = case["prompt"]
    eval_bag.rule = case["rule"]
    eval_bag.response = response
    eval_bag.geval_score = metric.score
    eval_bag.geval_reason = metric.reason
    eval_bag.passed = passed
    eval_bag.rationale = case["rationale"]


# ---------------------------------------------------------------------------
# Analysis phase — aggregate pass rate across all cases
# ---------------------------------------------------------------------------

@pytest.mark.eval_analysis(name="skill_rules")
def test_rule_compliance_rate(eval_results):
    """Enforce a minimum rule-compliance rate across all golden cases."""
    if not eval_results:
        pytest.skip("No eval results to analyze")

    # If all cases were skipped (no credentials), eval_bags will be empty.
    ran = [r for r in eval_results if hasattr(r.result, "passed")]
    if not ran:
        pytest.skip("All eval cases were skipped (no AWS credentials available)")

    passed = [r for r in ran if r.result.passed]
    rate = len(passed) / len(ran)

    print(f"\n{'─' * 60}")
    print(f"Rule compliance rate: {rate:.0%} ({len(passed)}/{len(eval_results)})")
    print(f"{'─' * 60}")

    by_skill: dict[str, list] = {}
    for r in ran:
        by_skill.setdefault(r.result.skill, []).append(r)

    for skill, results in sorted(by_skill.items()):
        skill_passed = sum(1 for r in results if r.result.passed)
        print(f"\n  {skill}: {skill_passed}/{len(results)}")
        for r in results:
            status = "✓" if r.result.passed else "✗"
            score_str = f"score={r.result.geval_score:.2f}"
            print(f"    {status} [{r.result.case_id}] {score_str}")
            print(f"       rule:   {r.result.rule}")
            print(f"       reason: {r.result.geval_reason}")

    assert rate >= _COMPLIANCE_THRESHOLD, (
        f"Rule compliance rate {rate:.0%} is below the {_COMPLIANCE_THRESHOLD:.0%} threshold. "
        f"Failed cases: {[r.result.case_id for r in ran if not r.result.passed]}"
    )
