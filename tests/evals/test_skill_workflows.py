"""Eval tests: end-to-end workflow quality — LLM-as-judge.

Tests that the opensearch-launchpad skill produces high-quality responses
across all 5 search strategies and cross-cutting scenarios. Evaluates on
5 dimensions: correctness, completeness, turn efficiency, autonomy, and
token usage.

Architecture:
  1. call_skill_with_usage() — runs the skill as system prompt, returns
     response + token counts (Haiku 4.5 via Bedrock)
  2. GEval judge — evaluates response on 4 semantic criteria (Haiku 4.5)
  3. Token tracking — records input/output tokens per case

Run:
    uv run --group evals pytest tests/evals/test_skill_workflows.py --run-eval -v
    uv run --group evals pytest tests/evals/test_skill_workflows.py --run-eval-analysis
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("deepeval", reason="evals group not installed — run with: uv run --group evals pytest tests/evals/")
pytest.importorskip("pytest_evals", reason="evals group not installed — run with: uv run --group evals pytest tests/evals/")
from deepeval.metrics import GEval
from deepeval.models import AmazonBedrockModel
from deepeval.test_case import LLMTestCase, SingleTurnParams
from pytest_evals import eval_bag  # noqa: F401 — fixture injected by plugin

from tests.evals.conftest import (
    call_skill_with_usage,
    load_skill_md,
    _BEDROCK_MODEL_ID,
    _BEDROCK_REGION,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "workflow_evals.json"
_CASES = json.loads(_FIXTURES.read_text())

# Minimum fraction of workflow cases that must pass (per dimension).
_PASS_THRESHOLD = 0.60

# GEval pass threshold: score >= 0.5 means the criterion is satisfied.
_GEVAL_THRESHOLD = 0.5

# Dimensions to evaluate
_DIMENSIONS = ["correctness", "completeness", "turn_efficiency", "autonomy"]


def _make_judge(
    model_id: str = _BEDROCK_MODEL_ID, region: str = _BEDROCK_REGION
) -> AmazonBedrockModel:
    return AmazonBedrockModel(model=model_id, region=region)


# ---------------------------------------------------------------------------
# Eval phase — one test per golden case
# ---------------------------------------------------------------------------

@pytest.mark.eval(name="skill_workflows")
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_skill_workflow(case, eval_bag, bedrock_client):  # noqa: F811
    """Load the launchpad skill, get a response, judge on 4 dimensions + track tokens."""
    if bedrock_client is None:
        pytest.skip("AWS Bedrock credentials not available")

    skill_md = load_skill_md("opensearch-launchpad")
    response, token_usage = call_skill_with_usage(
        skill_md, case["prompt"], bedrock_client
    )

    judge = _make_judge()
    scores = {}
    reasons = {}

    for dim in _DIMENSIONS:
        criteria_key = f"criteria_{dim}"
        criteria = case.get(criteria_key, "")
        if not criteria:
            continue

        metric = GEval(
            name=f"Workflow:{case['id']}:{dim}",
            criteria=criteria,
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
        scores[dim] = metric.score
        reasons[dim] = metric.reason

    # Determine overall pass: all dimensions must meet threshold
    all_passed = all(s >= _GEVAL_THRESHOLD for s in scores.values())

    # Store results in eval_bag
    eval_bag.case_id = case["id"]
    eval_bag.workflow = case["workflow"]
    eval_bag.prompt = case["prompt"]
    eval_bag.response = response
    eval_bag.scores = scores
    eval_bag.reasons = reasons
    eval_bag.passed = all_passed
    eval_bag.input_tokens = token_usage["input_tokens"]
    eval_bag.output_tokens = token_usage["output_tokens"]
    eval_bag.total_tokens = token_usage["total_tokens"]


# ---------------------------------------------------------------------------
# Analysis phase — aggregate results
# ---------------------------------------------------------------------------

@pytest.mark.eval_analysis(name="skill_workflows")
def test_workflow_quality(eval_results):
    """Enforce minimum quality across all workflow eval cases."""
    if not eval_results:
        pytest.skip("No eval results to analyze")

    ran = [r for r in eval_results if hasattr(r.result, "passed")]
    if not ran:
        pytest.skip("All eval cases were skipped (no AWS credentials available)")

    # Print header
    print(f"\n{'═' * 80}")
    print("WORKFLOW EVAL RESULTS")
    print(f"{'═' * 80}")

    # Per-dimension aggregate
    dim_scores: dict[str, list[float]] = {d: [] for d in _DIMENSIONS}
    for r in ran:
        for dim, score in r.result.scores.items():
            dim_scores[dim].append(score)

    print(f"\n{'─' * 60}")
    print("Aggregate Scores by Dimension")
    print(f"{'─' * 60}")
    for dim in _DIMENSIONS:
        scores_list = dim_scores[dim]
        if scores_list:
            mean = sum(scores_list) / len(scores_list)
            pass_count = sum(1 for s in scores_list if s >= _GEVAL_THRESHOLD)
            print(f"  {dim:20s}: mean={mean:.3f}  pass_rate={pass_count}/{len(scores_list)}")

    # Per-workflow breakdown
    by_workflow: dict[str, list] = {}
    for r in ran:
        by_workflow.setdefault(r.result.workflow, []).append(r)

    print(f"\n{'─' * 60}")
    print("Per-Workflow Breakdown")
    print(f"{'─' * 60}")
    for workflow, results in sorted(by_workflow.items()):
        workflow_passed = sum(1 for r in results if r.result.passed)
        print(f"\n  {workflow}: {workflow_passed}/{len(results)} fully passed")
        for r in results:
            status = "PASS" if r.result.passed else "FAIL"
            scores_str = " | ".join(
                f"{d[:4]}={s:.2f}" for d, s in r.result.scores.items()
            )
            print(f"    [{status}] {r.result.case_id}: {scores_str}")
            if not r.result.passed:
                for dim, reason in r.result.reasons.items():
                    if r.result.scores.get(dim, 1.0) < _GEVAL_THRESHOLD:
                        print(f"          {dim}: {reason}")

    # Token usage summary
    print(f"\n{'─' * 60}")
    print("Token Usage Summary")
    print(f"{'─' * 60}")
    total_input = sum(r.result.input_tokens for r in ran)
    total_output = sum(r.result.output_tokens for r in ran)
    avg_input = total_input / len(ran) if ran else 0
    avg_output = total_output / len(ran) if ran else 0
    print(f"  Total cases: {len(ran)}")
    print(f"  Avg input tokens:  {avg_input:.0f}")
    print(f"  Avg output tokens: {avg_output:.0f}")
    print(f"  Avg total tokens:  {avg_input + avg_output:.0f}")
    print(f"  Total tokens used: {total_input + total_output}")

    # Per-workflow token usage
    print(f"\n  By workflow:")
    for workflow, results in sorted(by_workflow.items()):
        wf_input = sum(r.result.input_tokens for r in results)
        wf_output = sum(r.result.output_tokens for r in results)
        wf_avg = (wf_input + wf_output) / len(results)
        print(f"    {workflow:20s}: avg={wf_avg:.0f} tokens/case ({len(results)} cases)")

    print(f"\n{'═' * 80}")

    # Enforce pass rates per dimension
    failures = []
    for dim in _DIMENSIONS:
        scores_list = dim_scores[dim]
        if not scores_list:
            continue
        pass_rate = sum(1 for s in scores_list if s >= _GEVAL_THRESHOLD) / len(scores_list)
        if pass_rate < _PASS_THRESHOLD:
            failures.append(f"{dim}: {pass_rate:.0%} < {_PASS_THRESHOLD:.0%}")

    if failures:
        assert False, (
            f"Workflow eval dimensions below {_PASS_THRESHOLD:.0%} threshold:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )
