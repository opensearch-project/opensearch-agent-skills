#!/usr/bin/env python3
"""Local benchmark runner for opensearch-launchpad skill performance.

Runs the workflow eval cases, collects scores and token usage,
and outputs a results JSON file for comparison.

Usage:
    uv run --group evals python scripts/run_benchmark.py
    uv run --group evals python scripts/run_benchmark.py --tag my-experiment
    uv run --group evals python scripts/run_benchmark.py --runs 3
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

# Add project root to path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from tests.evals.conftest import (
    call_skill_with_usage,
    load_skill_md,
    _BEDROCK_MODEL_ID,
    _BEDROCK_REGION,
)


_FIXTURES = _PROJECT_ROOT / "tests" / "evals" / "fixtures" / "workflow_evals.json"
_RESULTS_DIR = _PROJECT_ROOT / "tests" / "evals" / "results"
_DIMENSIONS = ["correctness", "completeness", "turn_efficiency", "autonomy"]


def _get_bedrock_client():
    """Create a boto3 bedrock-runtime client."""
    try:
        import boto3
        return boto3.client("bedrock-runtime", region_name=_BEDROCK_REGION)
    except Exception as e:
        print(f"ERROR: Cannot create Bedrock client: {e}", file=sys.stderr)
        print("Ensure AWS credentials are configured.", file=sys.stderr)
        sys.exit(1)


def _judge_response(response: str, prompt: str, criteria: str, client) -> tuple[float, str]:
    """Use LLM-as-judge to score a response against criteria. Returns (score, reason)."""
    judge_prompt = f"""You are evaluating an AI assistant's response quality.

USER PROMPT: {prompt}

ASSISTANT RESPONSE: {response}

EVALUATION CRITERIA: {criteria}

Score the response from 0.0 to 1.0 based on how well it satisfies the criteria.
- 1.0 = perfectly satisfies all criteria
- 0.7 = mostly satisfies criteria with minor gaps
- 0.5 = partially satisfies criteria
- 0.3 = mostly fails to satisfy criteria
- 0.0 = completely fails

Respond in this exact JSON format:
{{"score": <float>, "reason": "<brief explanation>"}}"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": judge_prompt}],
    })
    response_raw = client.invoke_model(
        modelId=_BEDROCK_MODEL_ID,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    response_body = json.loads(response_raw["body"].read())
    text = response_body["content"][0]["text"]
    stop_reason = response_body.get("stop_reason", "")

    # Detect truncation — if the model hit max_tokens, the response is incomplete
    if stop_reason == "max_tokens":
        return 0.0, f"Judge response truncated (hit max_tokens). Raw: {text[:200]}"

    try:
        # Parse JSON from response (handle markdown code blocks)
        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(clean)
        return float(result.get("score", 0.0)), str(result.get("reason", ""))
    except (json.JSONDecodeError, ValueError):
        return 0.0, f"Failed to parse judge response: {text[:200]}"


def run_single(cases: list[dict], skill_md: str, client) -> list[dict]:
    """Run all cases once and return per-case results."""
    results = []
    for case in cases:
        print(f"  Running: {case['id']}...", end=" ", flush=True)

        response, token_usage = call_skill_with_usage(
            skill_md, case["prompt"], client
        )

        scores = {}
        reasons = {}
        for dim in _DIMENSIONS:
            criteria = case.get(f"criteria_{dim}", "")
            if not criteria:
                continue
            score, reason = _judge_response(response, case["prompt"], criteria, client)
            scores[dim] = score
            reasons[dim] = reason

        result = {
            "case_id": case["id"],
            "workflow": case["workflow"],
            "scores": scores,
            "tokens": token_usage,
            "response_length": len(response),
        }
        results.append(result)

        scores_str = " | ".join(f"{d[:4]}={s:.2f}" for d, s in scores.items())
        print(f"{scores_str} | tokens={token_usage['total_tokens']}")

    return results


def aggregate_results(all_runs: list[list[dict]]) -> dict:
    """Aggregate multiple runs into mean/stdev per dimension and per case."""
    # Collect per-dimension scores across all runs
    dim_all: dict[str, list[float]] = {d: [] for d in _DIMENSIONS}
    token_all: list[int] = []

    for run in all_runs:
        for case_result in run:
            for dim, score in case_result["scores"].items():
                dim_all[dim].append(score)
            token_all.append(case_result["tokens"]["total_tokens"])

    aggregate = {}
    for dim in _DIMENSIONS:
        values = dim_all[dim]
        if values:
            aggregate[dim] = {
                "mean": statistics.mean(values),
                "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
                "pass_rate": sum(1 for v in values if v >= 0.5) / len(values),
            }

    aggregate["tokens"] = {
        "mean": statistics.mean(token_all) if token_all else 0,
        "stdev": statistics.stdev(token_all) if len(token_all) > 1 else 0.0,
        "total": sum(token_all),
    }

    # Per-case aggregation
    case_ids = [r["case_id"] for r in all_runs[0]] if all_runs else []
    per_case = {}
    for case_id in case_ids:
        case_scores: dict[str, list[float]] = {d: [] for d in _DIMENSIONS}
        case_tokens: list[int] = []
        for run in all_runs:
            for r in run:
                if r["case_id"] == case_id:
                    for dim, score in r["scores"].items():
                        case_scores[dim].append(score)
                    case_tokens.append(r["tokens"]["total_tokens"])
        per_case[case_id] = {
            "scores": {
                dim: {"mean": statistics.mean(vals), "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0}
                for dim, vals in case_scores.items() if vals
            },
            "tokens": {
                "mean": statistics.mean(case_tokens) if case_tokens else 0,
                "stdev": statistics.stdev(case_tokens) if len(case_tokens) > 1 else 0.0,
            },
        }

    return {"aggregate": aggregate, "per_case": per_case}


def main():
    parser = argparse.ArgumentParser(description="Run opensearch-launchpad skill benchmark")
    parser.add_argument("--tag", default="", help="Tag for this benchmark run (e.g., branch name)")
    parser.add_argument("--runs", type=int, default=1, help="Number of runs for statistical stability (default: 1)")
    parser.add_argument("--output", type=str, default="", help="Output file path (default: auto-generated)")
    args = parser.parse_args()

    cases = json.loads(_FIXTURES.read_text())
    print(f"Loaded {len(cases)} workflow eval cases")
    print(f"Running {args.runs} run(s)...")

    client = _get_bedrock_client()
    skill_md = load_skill_md("opensearch-launchpad")

    all_runs = []
    for run_idx in range(args.runs):
        if args.runs > 1:
            print(f"\n--- Run {run_idx + 1}/{args.runs} ---")
        run_results = run_single(cases, skill_md, client)
        all_runs.append(run_results)

    # Aggregate
    aggregated = aggregate_results(all_runs)

    # Build output
    tag = args.tag or f"benchmark-{int(time.time())}"
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output = {
        "tag": tag,
        "timestamp": timestamp,
        "model_id": _BEDROCK_MODEL_ID,
        "num_runs": args.runs,
        "num_cases": len(cases),
        **aggregated,
        "raw_runs": all_runs,
    }

    # Write results
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = _RESULTS_DIR / f"{tag}.json"

    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n{'═' * 60}")
    print(f"Results saved to: {output_path}")
    print(f"{'═' * 60}")

    # Print summary
    print(f"\nSUMMARY ({tag}, {args.runs} run(s), {len(cases)} cases)")
    print(f"{'─' * 60}")
    for dim in _DIMENSIONS:
        if dim in aggregated["aggregate"]:
            d = aggregated["aggregate"][dim]
            print(f"  {dim:20s}: mean={d['mean']:.3f} stdev={d['stdev']:.3f} pass_rate={d['pass_rate']:.0%}")
    tokens = aggregated["aggregate"]["tokens"]
    print(f"  {'tokens':20s}: mean={tokens['mean']:.0f} stdev={tokens['stdev']:.0f} total={tokens['total']}")


if __name__ == "__main__":
    main()
