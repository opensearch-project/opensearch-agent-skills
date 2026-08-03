"""Opt-in live integration test for security-analytics-detection-engineering.

Skipped unless OPENSEARCH_URL is set. Runs the full verified detection loop
against a real cluster:

    clean unique index -> rule -> detector -> BOTH fixtures indexed AFTER
    detector creation -> positive finding attributed -> negative fixture clean
    -> normal cleanup

Cleanup runs in teardown even when assertions fail.

    OPENSEARCH_URL=http://127.0.0.1:9200 uv run pytest \
        tests/test_agent_skills_security_analytics_integration.py -v
"""

import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills" / "opensearch-skills" / "security"
    / "security-analytics-detection-engineering" / "scripts"
)
sys.path.insert(0, str(_SCRIPTS_DIR))

import security_analytics as sa  # noqa: E402

FIXTURES = _SCRIPTS_DIR.parent / "assets" / "fixtures"

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENSEARCH_URL"),
    reason="live integration test; set OPENSEARCH_URL to run",
)


def test_full_verified_detection_loop(tmp_path):
    config = sa.resolve_config(SimpleNamespace(url=None))
    manifest_path = str(tmp_path / "manifest.json")
    index = f"{sa.TEST_PREFIX}-{uuid.uuid4().hex[:10]}"

    code, preflight = sa.cmd_preflight(config, SimpleNamespace())
    assert code == 0, f"preflight failed: {preflight}"
    assert preflight["security_analytics_available"] is True

    manifest = sa.new_manifest(config, index)
    try:
        code, created = sa.cmd_create_index(
            config,
            SimpleNamespace(index=index,
                            mapping_file=str(FIXTURES / "test-index-mapping.json")),
            manifest, manifest_path,
        )
        assert code == 0 and created["created"]

        code, rule = sa.cmd_create_rule(
            config,
            SimpleNamespace(sigma_file=str(FIXTURES / "sigma-encoded-powershell.yml"),
                            category="windows", apply=True),
            manifest, manifest_path,
        )
        assert code == 0 and rule["rule_id"]

        code, detector = sa.cmd_create_detector(
            config,
            SimpleNamespace(index=index, log_type="windows", name=None,
                            schedule_minutes=1),
            manifest, manifest_path,
        )
        assert code == 0 and detector["ready"], f"detector not ready: {detector}"

        code, verify = sa.cmd_verify(
            config,
            SimpleNamespace(
                positive_fixture=str(FIXTURES / "positive-event.json"),
                negative_fixture=str(FIXTURES / "negative-event.json"),
                timeout=180, poll_interval=10, schedule_minutes=1,
            ),
            manifest, manifest_path,
        )
        print(json.dumps(verify, indent=2))
        assert verify["eligibility"]["both_indexed_after_detector_creation"] is True
        assert code == 0, f"verification failed: {verify}"
        assert verify["verified"] is True
        assert manifest["rule_id"] in verify["positive"]["rule_ids_in_finding"]
        assert verify["positive"]["detector_id"] == manifest["detector_id"]
        assert verify["negative"]["findings_attributed"] == 0
    finally:
        code, cleanup = sa.cmd_cleanup(
            config, SimpleNamespace(force=False), manifest, manifest_path
        )
        print(json.dumps(cleanup, indent=2))

    assert code == 0, f"cleanup failed: {cleanup}"
    assert cleanup["status"] == "complete"

    status, _ = sa.http_request(config, "GET", f"/{index}/_mapping")
    assert status == 404, "test index should be gone after cleanup"
