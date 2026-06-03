#!/usr/bin/env python3
"""Update baseline.json only if ALL dimensions improved (or stayed equal).

This prevents downward drift — the baseline only ratchets up.
If any dimension regressed, the baseline is NOT updated.

Usage:
    uv run --group evals python scripts/update_baseline.py \
        --baseline tests/evals/results/baseline.json \
        --current tests/evals/results/ci-run.json
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

_DIMENSIONS = ["correctness", "completeness", "turn_efficiency", "autonomy"]


def main():
    parser = argparse.ArgumentParser(description="Update baseline if all dimensions improved")
    parser.add_argument("--baseline", required=True, help="Path to current baseline JSON")
    parser.add_argument("--current", required=True, help="Path to current run JSON")
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    current_path = Path(args.current)

    if not baseline_path.exists():
        # No baseline yet — adopt current as baseline
        print(f"No baseline found. Adopting current as baseline.")
        shutil.copy(current_path, baseline_path)
        return

    if not current_path.exists():
        print(f"No current results found at {current_path}")
        sys.exit(1)

    baseline = json.loads(baseline_path.read_text())
    current = json.loads(current_path.read_text())

    baseline_agg = baseline.get("aggregate", {})
    current_agg = current.get("aggregate", {})

    # Check if ALL dimensions improved (or stayed equal)
    improvements = []
    regressions = []

    for dim in _DIMENSIONS:
        b_mean = baseline_agg.get(dim, {}).get("mean", 0)
        c_mean = current_agg.get(dim, {}).get("mean", 0)
        delta = c_mean - b_mean

        if delta >= 0:
            improvements.append((dim, b_mean, c_mean, delta))
        else:
            regressions.append((dim, b_mean, c_mean, delta))

    print(f"Baseline vs Current:")
    for dim in _DIMENSIONS:
        b_mean = baseline_agg.get(dim, {}).get("mean", 0)
        c_mean = current_agg.get(dim, {}).get("mean", 0)
        delta = c_mean - b_mean
        status = "UP" if delta > 0 else ("=" if delta == 0 else "DOWN")
        print(f"  {dim:20s}: {b_mean:.3f} -> {c_mean:.3f} ({delta:+.3f}) [{status}]")

    if regressions:
        print(f"\nBaseline NOT updated — {len(regressions)} dimension(s) regressed:")
        for dim, b, c, d in regressions:
            print(f"  {dim}: {b:.3f} -> {c:.3f} ({d:+.3f})")
    else:
        print(f"\nAll dimensions improved or held. Updating baseline.")
        shutil.copy(current_path, baseline_path)


if __name__ == "__main__":
    main()
