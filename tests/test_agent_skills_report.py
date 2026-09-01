"""Tests for the bundled Relevance X-Ray report formatter."""

import sys
from pathlib import Path

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "search"
    / "relevance-x-ray"
    / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

from relevance_xray_lib.explain_parser import parse_explain
from relevance_xray_lib.report import build_diagnosis_report, build_findings_table
from relevance_xray_lib.rules_engine import Finding


def test_build_diagnosis_report_no_findings_matched():
    node = {
        "value": 0.9,
        "description": "sum of:",
        "details": [
            {
                "value": 0.9,
                "description": "weight(title:wireless in 0) [PerFieldSimilarity], result of:",
                "details": [],
            }
        ],
    }
    summary = parse_explain(node)
    report = build_diagnosis_report("products", "wireless charger", "42", summary, findings=[])
    assert "SUPPORTED CONCLUSION" in report
    assert "No supported root cause" in report
    assert "wireless" in report
    assert "No automatic fix is justified" in report


def test_build_diagnosis_report_unmatched_document():
    summary = parse_explain({"value": 0.0, "description": "no match", "details": []})
    report = build_diagnosis_report("products", "wireless charger", "42", summary, findings=[])
    assert "did not match the query at all" in report


def test_build_diagnosis_report_includes_findings_sorted_by_severity():
    node = {"value": 0.1, "description": "sum of:", "details": []}
    summary = parse_explain(node)
    findings = [
        Finding(rule="r1", tag="[QUERY_TUNING]", severity="LOW", message="low issue", fix="fix low"),
        Finding(rule="r2", tag="[INDEX_MAPPING]", severity="HIGH", message="high issue", fix="fix high"),
    ]
    report = build_diagnosis_report("products", "q", "42", summary, findings=findings)
    # HIGH severity finding should be the reported root cause
    assert "high issue" in report.split("EVIDENCE")[0]
    assert "fix high" in report
    assert "fix low" in report


def test_report_prefers_higher_confidence_when_severity_matches():
    summary = parse_explain({"value": 0.1, "description": "sum of:", "details": []})
    findings = [
        Finding(
            rule="medium-confidence",
            tag="[QUERY_TUNING]",
            severity="MEDIUM",
            confidence="medium",
            message="medium confidence issue",
            fix="fix medium",
        ),
        Finding(
            rule="high-confidence",
            tag="[INDEX_MAPPING]",
            severity="MEDIUM",
            confidence="high",
            message="high confidence issue",
            fix="fix high",
        ),
    ]
    report = build_diagnosis_report("products", "q", "42", summary, findings=findings)
    assert "high confidence issue" in report.split("EVIDENCE")[0]


def test_build_diagnosis_report_includes_hybrid_breakdown():
    node = {
        "value": 1.5,
        "description": "sum of:",
        "details": [
            {
                "value": 0.9,
                "description": "weight(title:wireless in 0) [PerFieldSimilarity], result of:",
                "details": [],
            },
            {"value": 0.6, "description": "KnnScoreDocQuery [0]", "details": []},
        ],
    }
    summary = parse_explain(node)
    report = build_diagnosis_report("products", "q", "42", summary, findings=[])
    assert "wireless" in report
    assert "0.900" in report
    assert "0.600" in report


def test_build_diagnosis_report_includes_validation_section():
    node = {"value": 0.1, "description": "sum of:", "details": []}
    summary = parse_explain(node)
    validation = {
        "query_term": "sneakers",
        "candidate": "trainers",
        "before_rank": None,
        "after_rank": 2,
        "improved": True,
    }
    report = build_diagnosis_report("products", "q", "42", summary, findings=[], validation=validation)
    assert "VALIDATED IMPACT" in report
    assert "trainers" in report
    assert "improved" in report


def test_build_findings_table_empty():
    assert build_findings_table([]) == "No findings."


def test_build_findings_table_renders_rows():
    findings = [
        Finding(rule="r1", tag="[QUERY_TUNING]", severity="MEDIUM", message="m", fix="do X"),
    ]
    table = build_findings_table(findings)
    assert "MEDIUM" in table
    assert "[QUERY_TUNING]" in table
    assert "do X" in table


def test_report_distinguishes_evaluated_rules_and_limitations():
    summary = parse_explain({"value": 0.1, "description": "sum of:", "details": []})
    report = build_diagnosis_report(
        "products",
        "q",
        "42",
        summary,
        findings=[],
        evaluated_rules=["analyzer_mismatch"],
        skipped_rules={"weak_knn_recall": "no controlled counterfactual"},
        limitations=["hybrid normalization unavailable"],
    )
    assert "Evaluated rules: analyzer_mismatch" in report
    assert "Skipped rule: weak_knn_recall (no controlled counterfactual)." in report
    assert "Limitation: hybrid normalization unavailable" in report
