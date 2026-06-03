#!/usr/bin/env python3
"""Compare benchmark results against a stored baseline.

Used in CI to detect regressions. Exits with code 1 if any dimension
drops more than the allowed threshold from baseline.

Usage:
    uv run --group evals python scripts/compare_baseline.py
    uv run --group evals python scripts/compare_baseline.py --baseline path/to/baseline.json --current path/to/current.json
    uv run --group evals python scripts/compare_baseline.py --threshold 0.10
"""

import argparse
import json
import sys
from pathlib import Path

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "tests" / "evals" / "results"
_DIMENSIONS = ["correctness", "completeness", "turn_efficiency", "autonomy"]
_DEFAULT_THRESHOLD = 0.10  # 10% regression threshold


def load_latest_result(results_dir: Path, exclude_baseline: bool = True) -> Path | None:
    """Find the most recent results file (by timestamp in content)."""
    candidates = []
    for f in results_dir.glob("*.json"):
        if exclude_baseline and f.name == "baseline.json":
            continue
        try:
            data = json.loads(f.read_text())
            candidates.append((data.get("timestamp", ""), f))
        except (json.JSONDecodeError, KeyError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def compare(baseline: dict, current: dict, threshold: float) -> tuple[bool, list[str], str]:
    """Compare current against baseline. Returns (passed, failures, report_table)."""
    failures = []
    rows = []

    baseline_agg = baseline.get("aggregate", {})
    current_agg = current.get("aggregate", {})

    for dim in _DIMENSIONS:
        b_data = baseline_agg.get(dim, {})
        c_data = current_agg.get(dim, {})

        b_mean = b_data.get("mean", 0)
        c_mean = c_data.get("mean", 0)

        if b_mean > 0:
            delta = (c_mean - b_mean) / b_mean
        else:
            delta = 0.0 if c_mean == 0 else 1.0

        status = "PASS"
        if delta < -threshold:
            status = "FAIL"
            failures.append(
                f"{dim}: {c_mean:.3f} vs baseline {b_mean:.3f} (delta: {delta:+.1%}, threshold: -{threshold:.0%})"
            )
        elif delta > 0:
            status = "IMPROVED"

        rows.append({
            "dimension": dim,
            "baseline": b_mean,
            "current": c_mean,
            "delta": delta,
            "status": status,
        })

    # Token comparison (informational, no threshold)
    b_tokens = baseline_agg.get("tokens", {}).get("mean", 0)
    c_tokens = current_agg.get("tokens", {}).get("mean", 0)
    token_delta = ((c_tokens - b_tokens) / b_tokens) if b_tokens > 0 else 0.0
    rows.append({
        "dimension": "tokens (avg)",
        "baseline": b_tokens,
        "current": c_tokens,
        "delta": token_delta,
        "status": "INFO",
    })

    # Format table
    table_lines = [
        f"| {'Dimension':<20} | {'Baseline':>10} | {'Current':>10} | {'Delta':>10} | {'Status':<10} |",
        f"|{'-' * 22}|{'-' * 12}|{'-' * 12}|{'-' * 12}|{'-' * 12}|",
    ]
    for row in rows:
        dim_name = row["dimension"]
        if row["dimension"] == "tokens (avg)":
            b_str = f"{row['baseline']:.0f}"
            c_str = f"{row['current']:.0f}"
        else:
            b_str = f"{row['baseline']:.3f}"
            c_str = f"{row['current']:.3f}"
        delta_str = f"{row['delta']:+.1%}"
        table_lines.append(
            f"| {dim_name:<20} | {b_str:>10} | {c_str:>10} | {delta_str:>10} | {row['status']:<10} |"
        )

    report = "\n".join(table_lines)
    passed = len(failures) == 0
    return passed, failures, report


def main():
    parser = argparse.ArgumentParser(description="Compare benchmark results against baseline")
    parser.add_argument("--baseline", type=str, default="", help="Path to baseline JSON")
    parser.add_argument("--current", type=str, default="", help="Path to current results JSON")
    parser.add_argument("--threshold", type=float, default=_DEFAULT_THRESHOLD, help="Regression threshold (default: 0.10)")
    args = parser.parse_args()

    # Load baseline
    baseline_path = Path(args.baseline) if args.baseline else _RESULTS_DIR / "baseline.json"
    if not baseline_path.exists():
        print(f"No baseline found at {baseline_path}")
        print("Run the benchmark first and save as baseline:")
        print(f"  uv run --group evals python scripts/run_benchmark.py --tag baseline")
        print(f"  cp {_RESULTS_DIR}/baseline.json {baseline_path}")
        sys.exit(0)  # Don't fail CI if no baseline exists yet

    # Load current
    if args.current:
        current_path = Path(args.current)
    else:
        current_path = load_latest_result(_RESULTS_DIR)
        if not current_path:
            print("No current results found. Run the benchmark first:")
            print("  uv run --group evals python scripts/run_benchmark.py")
            sys.exit(1)

    baseline = json.loads(baseline_path.read_text())
    current = json.loads(current_path.read_text())

    print(f"Baseline: {baseline_path.name} (tag: {baseline.get('tag', 'unknown')})")
    print(f"Current:  {current_path.name} (tag: {current.get('tag', 'unknown')})")
    print(f"Threshold: -{args.threshold:.0%} regression allowed")
    print()

    passed, failures, report = compare(baseline, current, args.threshold)

    print(report)
    print()

    if passed:
        print("RESULT: PASS — No regressions detected.")
    else:
        print("RESULT: FAIL — Regressions detected:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
