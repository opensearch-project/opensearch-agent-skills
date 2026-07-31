#!/usr/bin/env python3
"""Run the bundled RAG Integrity Sentinel adversarial regression benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import rag_integrity


DEFAULT_CORPUS = (
    Path(__file__).resolve().parent.parent / "assets" / "benchmark-corpus.jsonl"
)
CLASSIFICATION_THRESHOLD = "medium"


def load_corpus(path: Path) -> Iterable[Mapping[str, Any]]:
    """Yield validated benchmark records from JSONL."""
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            required = {
                "_id",
                "expected",
                "content",
                "source_uri",
                "ingested_at",
                "hash_mode",
            }
            missing = sorted(required - record.keys())
            if missing:
                raise ValueError(
                    f"{path}:{line_number} missing required fields: "
                    + ", ".join(missing)
                )
            if record["expected"] not in {"clean", "malicious"}:
                raise ValueError(
                    f"{path}:{line_number} expected must be clean or malicious"
                )
            if record["hash_mode"] not in {"valid", "mismatch"}:
                raise ValueError(
                    f"{path}:{line_number} hash_mode must be valid or mismatch"
                )
            yield record


def source_for_record(record: Mapping[str, Any]) -> dict[str, str]:
    """Build the indexed source and its recorded integrity hash."""
    content = str(record["content"])
    expected_hash = rag_integrity.content_sha256(content)
    if record["hash_mode"] == "mismatch":
        expected_hash = "0" * 64
    return {
        "content": content,
        "source_uri": str(record["source_uri"]),
        "ingested_at": str(record["ingested_at"]),
        "content_sha256": expected_hash,
    }


def safe_ratio(numerator: int, denominator: int) -> float:
    """Return a bounded ratio for a possibly empty denominator."""
    return numerator / denominator if denominator else 0.0


def run_benchmark(corpus_path: Path = DEFAULT_CORPUS) -> dict[str, Any]:
    """Evaluate deterministic classification on the bundled labeled corpus."""
    started = time.perf_counter()
    records = list(load_corpus(corpus_path))
    findings = []
    rows = []
    confusion = Counter()
    signal_coverage: Counter[str] = Counter()
    threshold = rag_integrity.SEVERITY_ORDER[CLASSIFICATION_THRESHOLD]

    for record in records:
        finding = rag_integrity.analyze_document(
            index="rag-integrity-benchmark",
            document_id=str(record["_id"]),
            source=source_for_record(record),
        )
        predicted = (
            "malicious"
            if rag_integrity.SEVERITY_ORDER[finding["severity"]] >= threshold
            else "clean"
        )
        expected = str(record["expected"])
        confusion[
            {
                ("malicious", "malicious"): "true_positive",
                ("clean", "malicious"): "false_positive",
                ("clean", "clean"): "true_negative",
                ("malicious", "clean"): "false_negative",
            }[(expected, predicted)]
        ] += 1
        if expected == "malicious":
            signal_coverage.update(item["id"] for item in finding["signals"])
        rows.append(
            {
                "id": str(record["_id"]),
                "expected": expected,
                "predicted": predicted,
                "severity": finding["severity"],
                "risk_score": finding["risk_score"],
                "signal_ids": [item["id"] for item in finding["signals"]],
            }
        )
        findings.append(finding)

    elapsed = time.perf_counter() - started
    tp = confusion["true_positive"]
    fp = confusion["false_positive"]
    tn = confusion["true_negative"]
    fn = confusion["false_negative"]
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    f1 = safe_ratio(2 * precision * recall, precision + recall)
    accuracy = safe_ratio(tp + tn, len(records))
    report = rag_integrity.make_report(
        findings,
        near_duplicate_distance=3,
        source=f"bundled-regression-corpus:{corpus_path.name}",
    )

    return {
        "benchmark": {
            "name": "rag-integrity-sentinel-bundled-adversarial-regression",
            "version": "1.0",
            "classification_threshold": CLASSIFICATION_THRESHOLD,
            "corpus_file": corpus_path.name,
            "corpus_size": len(records),
            "clean_documents": sum(
                record["expected"] == "clean" for record in records
            ),
            "malicious_documents": sum(
                record["expected"] == "malicious" for record in records
            ),
            "disclosure": (
                "Bundled deterministic regression corpus; not an independent "
                "or real-world prevalence evaluation."
            ),
        },
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "true_negative": tn,
            "false_negative": fn,
        },
        "metrics": {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "accuracy": round(accuracy, 6),
            "elapsed_ms": round(elapsed * 1000, 3),
            "documents_per_second": (
                round(len(records) / elapsed, 3) if elapsed else None
            ),
        },
        "signal_coverage": dict(sorted(signal_coverage.items())),
        "safety": report["safety"],
        "results": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    """Create the benchmark CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help="Labeled JSONL corpus (default: bundled regression corpus)",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output JSON path, or - for stdout (default: -)",
    )
    parser.add_argument(
        "--minimum-precision",
        type=float,
        default=0.95,
        help="Exit 2 if precision is below this value (default: 0.95)",
    )
    parser.add_argument(
        "--minimum-recall",
        type=float,
        default=0.95,
        help="Exit 2 if recall is below this value (default: 0.95)",
    )
    parser.add_argument(
        "--minimum-f1",
        type=float,
        default=0.95,
        help="Exit 2 if F1 is below this value (default: 0.95)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark and enforce caller-selected quality gates."""
    args = build_parser().parse_args(argv)
    result = run_benchmark(args.corpus)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output == "-":
        sys.stdout.write(rendered)
    else:
        Path(args.output).write_text(rendered, encoding="utf-8")

    metrics = result["metrics"]
    if (
        metrics["precision"] < args.minimum_precision
        or metrics["recall"] < args.minimum_recall
        or metrics["f1"] < args.minimum_f1
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
