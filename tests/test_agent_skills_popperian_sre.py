"""Tests for skills/opensearch-skills/observability/popperian-sre/scripts/lib/

Ported from the full development test suite at github.com/siteborne/popperian-sre
(66 tests, 100% line coverage, 18/18 mutation-tested). This file covers the
skill's deterministic core: the sufficiency gate, report guard, PPL validator,
redactor, evidence ledger, hypothesis registry, schema discovery, incident
retrieval, and context-bounded query execution. No live cluster required --
OpenSearch clients are mocked throughout.
"""

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "observability" / "popperian-sre" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from pydantic import ValidationError
from unittest.mock import MagicMock
import pytest

from popperian_lib.evidence_ledger import EvidenceLedger
from popperian_lib.hypothesis_registry import HypothesisRegistry
from popperian_lib.incident_retrieval import IncidentRetrieval
from popperian_lib.models import TestResult, HypothesisCard
from popperian_lib.ppl_validation import PPLValidator
from popperian_lib.query_executor import QueryExecutor
from popperian_lib.redaction import Redactor
from popperian_lib.report_guard import ReportGuard
from popperian_lib.schema_discovery import SchemaDiscovery
from popperian_lib.sufficiency_gate import SufficiencyGate


# ============================================================================
# from tests/unit/test_evidence_ledger.py
# ============================================================================

def test_record_test_result_against_unregistered_hypothesis_raises():
    # Silently dropping evidence would defeat the whole point of an auditable
    # ledger -- a hypothesis_id typo must fail loudly, not vanish quietly.
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))

    with pytest.raises(ValueError, match="unregistered hypothesis"):
        ledger.record_test_result(TestResult(
            test_id="t1", hypothesis_id="H_TYPO", signal="traces", query="...",
            classification="SUPPORTS", raw_result_hash="x", interpretation="..."
        ))


def test_record_test_result_against_registered_hypothesis_succeeds():
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.record_test_result(TestResult(
        test_id="t1", hypothesis_id="H_DB_LOCK", signal="traces", query="...",
        classification="SUPPORTS", raw_result_hash="x", interpretation="..."
    ))

    assert len(ledger.state.hypotheses["H_DB_LOCK"].tests) == 1


def test_get_ranked_hypotheses_orders_by_score_descending():
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_CONN_POOL"))
    ledger.record_test_result(TestResult(
        test_id="t1", hypothesis_id="H_CONN_POOL", signal="traces", query="...",
        classification="SUPPORTS", raw_result_hash="x", interpretation="..."
    ))

    ranked = ledger.get_ranked_hypotheses()
    assert ranked[0].id == "H_CONN_POOL"
    assert ranked[1].id == "H_DB_LOCK"


# ============================================================================
# from tests/unit/test_hypothesis_registry.py
# ============================================================================

def test_get_all_returns_every_taxonomy_entry():
    all_hyps = HypothesisRegistry.get_all()
    assert {h.id for h in all_hyps} == set(HypothesisRegistry.TAXONOMY.keys())


def test_get_hypothesis_unknown_id_raises():
    with pytest.raises(ValueError):
        HypothesisRegistry.get_hypothesis("H_DOES_NOT_EXIST")


@pytest.mark.parametrize("hyp_id", list(HypothesisRegistry.TAXONOMY.keys()))
def test_every_hypothesis_has_required_fields(hyp_id):
    hyp = HypothesisRegistry.get_hypothesis(hyp_id)
    assert hyp.statement
    assert len(hyp.required_observations) >= 1
    assert len(hyp.contradicting_observations) >= 1
    assert len(hyp.alternative_explanations) >= 1
    assert hyp.tests == []


# ============================================================================
# from tests/unit/test_models.py
# ============================================================================

def _test_result(**overrides):
    fields = dict(
        test_id="t1", hypothesis_id="H_X", signal="traces", query="...",
        classification="SUPPORTS", raw_result_hash="x", interpretation="..."
    )
    fields.update(overrides)
    return TestResult(**fields)


def test_valid_classifications_are_accepted():
    for classification in ["SUPPORTS", "CONTRADICTS", "MISSING", "NONDISCRIMINATING", "QUERY_FAILED", "SCHEMA_MISMATCH"]:
        _test_result(classification=classification)  # must not raise


@pytest.mark.parametrize("bad_value", ["SUPPORT", "supports", "Supports", "SUPPORTS ", "UNKNOWN"])
def test_invalid_classification_is_rejected_not_silently_scored_as_zero(bad_value):
    # Before this was a Literal type, a typo like "SUPPORT" would construct
    # fine and just silently contribute 0 to score() forever -- no error,
    # no signal, nothing. It must fail at construction instead.
    with pytest.raises(ValidationError):
        _test_result(classification=bad_value)


def test_score_sums_weights_across_mixed_classifications():
    hyp = HypothesisCard(
        id="H_X", statement="...", required_observations=["a"],
        contradicting_observations=["b"], alternative_explanations=["c"],
        tests=[
            _test_result(test_id="t1", classification="SUPPORTS"),
            _test_result(test_id="t2", classification="SUPPORTS"),
            _test_result(test_id="t3", classification="CONTRADICTS"),
        ]
    )
    assert hyp.score() == 10 + 10 - 20


def test_nondiscriminating_and_schema_mismatch_score_zero():
    hyp = HypothesisCard(
        id="H_X", statement="...", required_observations=["a"],
        contradicting_observations=["b"], alternative_explanations=["c"],
        tests=[
            _test_result(test_id="t1", classification="NONDISCRIMINATING"),
            _test_result(test_id="t2", classification="SCHEMA_MISMATCH"),
        ]
    )
    assert hyp.score() == 0


# ============================================================================
# from tests/unit/test_sufficiency_gate.py
# ============================================================================

def _result(hyp_id, test_id, classification):
    return TestResult(
        test_id=test_id, hypothesis_id=hyp_id, signal="traces", query="...",
        classification=classification, raw_result_hash="x", interpretation="..."
    )


def _supports(hyp_id, test_id):
    return _result(hyp_id, test_id, "SUPPORTS")


def test_refuses_a_single_confirming_look():
    # A leading hypothesis backed by exactly one SUPPORTS query, alongside an
    # alternative that was registered but never actually queried, is confirmation
    # bias -- not a falsification-driven investigation -- and must be refused.
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_CONN_POOL"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t1"))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert "only tested once" in reason


def test_refuses_an_untested_alternative():
    # The leading hypothesis was genuinely tested twice, but the "alternative" was
    # only ever registered, never queried -- SKILL.md requires it be checked, not
    # just declared.
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_CONN_POOL"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t1"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t2"))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert "never" in reason


def test_passes_with_a_genuinely_tested_alternative():
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_CONN_POOL"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t1"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t2"))
    ledger.record_test_result(TestResult(
        test_id="t3", hypothesis_id="H_CONN_POOL", signal="logs", query="...",
        classification="MISSING", raw_result_hash="x", interpretation="..."
    ))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is True
    assert reason == "Sufficiency gates passed."


# The six tests below were added after a mutation-testing pass (scripts/mutation_test.py)
# found these exact branches had zero coverage -- disabling any of them still let the
# full suite pass. Each test isolates one branch so a future regression on that specific
# check gets caught, not just the gate's overall behavior.

def test_refuses_when_no_hypotheses_were_generated():
    ledger = EvidenceLedger()
    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert reason == "No hypotheses were generated."


def test_refuses_when_leading_hypothesis_has_no_supporting_evidence():
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.record_test_result(_result("H_DB_LOCK", "t1", "NONDISCRIMINATING"))
    ledger.record_test_result(_result("H_DB_LOCK", "t2", "MISSING"))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert "lacks supporting evidence" in reason


def test_refuses_when_leading_hypothesis_has_an_unresolved_contradiction():
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t1"))
    ledger.record_test_result(_result("H_DB_LOCK", "t2", "CONTRADICTS"))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert "unresolved contradicting evidence" in reason


def test_refuses_a_genuinely_tested_hypothesis_with_no_registered_alternative():
    # Distinct from test_refuses_a_single_confirming_look: the leading hypothesis
    # clears the has_discriminating bar (tested twice) so this isolates the
    # separate "at least one alternative" check rather than tripping on both at once.
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t1"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t2"))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert reason == "At least one plausible alternative must be tested."


def test_refuses_when_hypotheses_are_tied():
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_CONN_POOL"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t1"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t2"))
    ledger.record_test_result(_supports("H_CONN_POOL", "t3"))
    ledger.record_test_result(_supports("H_CONN_POOL", "t4"))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert reason == "Competing hypotheses remain observationally equivalent."


def test_refuses_when_query_failure_rate_exceeds_threshold():
    ledger = EvidenceLedger()
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_DB_LOCK"))
    ledger.add_hypothesis(HypothesisRegistry.get_hypothesis("H_CONN_POOL"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t1"))
    ledger.record_test_result(_supports("H_DB_LOCK", "t2"))
    ledger.record_test_result(_result("H_DB_LOCK", "t3", "QUERY_FAILED"))
    ledger.record_test_result(_result("H_DB_LOCK", "t4", "QUERY_FAILED"))
    ledger.record_test_result(_result("H_CONN_POOL", "t5", "MISSING"))

    passed, reason = SufficiencyGate.evaluate(ledger)
    assert passed is False
    assert reason == "Query failure rate exceeds threshold."


# ============================================================================
# from tests/unit/test_report_guard.py
# ============================================================================

def test_clean_report_passes():
    report = (
        "H_DB_LOCK ranks first with a score of 20, ahead of H_CONN_POOL at 0. "
        "Two discriminating queries support it: elevated average duration and "
        "elevated db_span_duration_ms during the incident window. Sufficiency "
        "gates passed."
    )
    valid, violations = ReportGuard.validate(report, gate_passed=True)
    assert valid is True
    assert violations == []


@pytest.mark.parametrize("phrase", [
    "The root cause is database lock contention.",
    "Checkout latency was caused by connection pool exhaustion.",
    "The database is responsible for the regression.",
    "We have confirmed the root cause.",
])
def test_proof_claim_language_is_always_flagged(phrase):
    valid, violations = ReportGuard.validate(phrase, gate_passed=True)
    assert valid is False
    assert any("proof" in v.lower() for v in violations)


def test_proof_claim_flagged_even_when_gate_refused():
    # Especially dangerous: asserting a cause when the gate said there wasn't
    # enough evidence to do so.
    valid, violations = ReportGuard.validate("The cause was CPU saturation.", gate_passed=False)
    assert valid is False


def test_bayesian_probability_claim_is_flagged():
    valid, violations = ReportGuard.validate(
        "There is an 85% probability this is a database lock.", gate_passed=True
    )
    assert valid is False
    assert any("bayesian" in v.lower() for v in violations)


def test_recommendation_after_refusal_is_flagged():
    report = "Evidence was insufficient to distinguish hypotheses. We recommend restarting the service."
    valid, violations = ReportGuard.validate(report, gate_passed=False)
    assert valid is False
    assert any("still recommends" in v for v in violations)


def test_recommendation_language_is_fine_when_gate_passed():
    report = "H_DB_LOCK passed the sufficiency gate. We recommend investigating lock contention in checkout-service."
    valid, violations = ReportGuard.validate(report, gate_passed=True)
    assert valid is True


def test_refusal_report_with_no_recommendation_is_fine():
    report = "Sufficiency gate refused: leading hypothesis lacks supporting evidence. No remediation is recommended."
    # "recommended" appears but not in the "recommended (fix|action|remediation)" or
    # "we recommend" form -- this phrasing explicitly says nothing was recommended.
    valid, violations = ReportGuard.validate(report, gate_passed=False)
    assert valid is True


# ============================================================================
# from tests/security/test_prompt_injection_in_logs.py
# ============================================================================

def test_ppl_injection_blocked():
    # A user might try to craft a malicious log that, if naively interpolated into a PPL query,
    # drops a table. PPLValidator must catch banned tokens even if they come from logs.
    malicious_query = "search source=logs-* | where message = 'error' | delete"
    is_valid, _ = PPLValidator.validate(malicious_query)
    assert is_valid is False

def test_valid_query_allowed():
    valid_query = "search source=logs-* | where message = 'error'"
    is_valid, result = PPLValidator.validate(valid_query)
    assert is_valid is True
    assert "head 500" in result

def test_empty_query_rejected():
    is_valid, reason = PPLValidator.validate("   ")
    assert is_valid is False
    assert reason == "Query is empty."


# ============================================================================
# from tests/security/test_sensitive_field_redaction.py
# ============================================================================

def test_password_redaction():
    log = 'User login failed. password="SuperSecretPassword123" attempt=4'
    redacted = Redactor.redact_string(log)
    assert 'SuperSecretPassword123' not in redacted
    assert 'password="[REDACTED]"' in redacted

def test_dict_redaction():
    data = {
        "user": "test_user",
        "email": "test@example.com",
        "meta": {
            "api_key": "sk-1234567890abcdef"
        }
    }
    redacted = Redactor.redact_dict(data)
    assert redacted["email"] != "test@example.com"
    assert redacted["meta"]["api_key"] == '"[REDACTED]"'

def test_redact_string_does_not_raise_on_non_matching_input():
    # Regression: the email pattern has no capture groups, so applying a
    # \1-referencing replacement template to it used to raise
    # re.PatternError on every call, matching or not.
    assert Redactor.redact_string("no secrets in this line") == "no secrets in this line"

def test_redact_dict_recurses_into_nested_lists():
    data = {"datarows": [["checkout-service", 'password="hunter2"']]}
    redacted = Redactor.redact_dict(data)
    assert redacted["datarows"][0][0] == "checkout-service"
    assert "hunter2" not in redacted["datarows"][0][1]

def test_redact_dict_passes_through_non_string_values_unchanged():
    # Numbers, booleans, and None (e.g. duration_ms, cpu_usage_percent) aren't
    # strings and have nothing to redact -- they must survive untouched.
    data = {"duration_ms": 5123, "healthy": True, "note": None}
    redacted = Redactor.redact_dict(data)
    assert redacted == {"duration_ms": 5123, "healthy": True, "note": None}


# ============================================================================
# from tests/security/test_endpoint_allowlist.py
# ============================================================================

def test_endpoint_allowlist():
    # Ensure QueryExecutor only hits /_plugins/_ppl and nothing else
    client_mock = MagicMock()
    client_mock.transport.perform_request.return_value = {"hits": []}
    
    executor = QueryExecutor(client_mock)
    executor.execute_ppl("search source=logs-*")
    
    # Verify the exact endpoint called
    client_mock.transport.perform_request.assert_called_once()
    args, kwargs = client_mock.transport.perform_request.call_args
    assert args[0] == "POST"
    assert args[1] == "/_plugins/_ppl"

def test_banned_token_never_reaches_the_client():
    # An invalid query must short-circuit before any request is made.
    client_mock = MagicMock()
    executor = QueryExecutor(client_mock)

    result = executor.execute_ppl("search source=logs-* | delete")

    assert result["status"] == "QUERY_FAILED"
    client_mock.transport.perform_request.assert_not_called()

def test_transport_exception_is_caught_and_reported_as_query_failed():
    client_mock = MagicMock()
    client_mock.transport.perform_request.side_effect = ConnectionError("cluster unreachable")
    executor = QueryExecutor(client_mock)

    result = executor.execute_ppl("search source=logs-*")

    assert result["status"] == "QUERY_FAILED"
    assert "cluster unreachable" in result["error"]


# ============================================================================
# from tests/unit/test_schema_discovery.py
# ============================================================================

def test_discover_indexes_filters_out_hidden_system_indexes():
    client = MagicMock()
    client.cat.indices.return_value = [
        {"index": "traces-2026.08"},
        {"index": ".opendistro_security"},
        {"index": "logs-2026.08"},
    ]

    discovery = SchemaDiscovery(client)
    result = discovery.discover_indexes()

    assert result == ["traces-2026.08", "logs-2026.08"]


def test_discover_indexes_returns_empty_list_on_failure():
    client = MagicMock()
    client.cat.indices.side_effect = Exception("connection refused")

    discovery = SchemaDiscovery(client)
    assert discovery.discover_indexes() == []


def test_get_mappings_returns_raw_mapping():
    client = MagicMock()
    client.indices.get_mapping.return_value = {"traces-2026.08": {"mappings": {"properties": {}}}}

    discovery = SchemaDiscovery(client)
    result = discovery.get_mappings("traces-2026.08")

    assert result == {"traces-2026.08": {"mappings": {"properties": {}}}}


def test_get_mappings_returns_empty_dict_on_failure():
    client = MagicMock()
    client.indices.get_mapping.side_effect = Exception("index not found")

    discovery = SchemaDiscovery(client)
    assert discovery.get_mappings("nonexistent") == {}


def test_get_available_signals_detects_each_signal_type():
    client = MagicMock()
    client.cat.indices.return_value = [
        {"index": "logs-2026.08"},
        {"index": "traces-2026.08"},
        {"index": "metrics-2026.08"},
        {"index": "deployments-2026.08"},
    ]

    discovery = SchemaDiscovery(client)
    signals = discovery.get_available_signals()

    assert signals == {"logs": True, "traces": True, "metrics": True, "deployments": True}


def test_get_available_signals_all_false_when_cluster_is_empty():
    client = MagicMock()
    client.cat.indices.return_value = []

    discovery = SchemaDiscovery(client)
    signals = discovery.get_available_signals()

    assert signals == {"logs": False, "traces": False, "metrics": False, "deployments": False}


def test_get_available_signals_recognizes_otel_trace_indexes():
    # Real OTel deployments commonly name trace indexes otel-v1-apm-span-* rather
    # than containing the literal substring "trace".
    client = MagicMock()
    client.cat.indices.return_value = [{"index": "otel-v1-apm-span-000001"}]

    discovery = SchemaDiscovery(client)
    signals = discovery.get_available_signals()

    assert signals["traces"] is True


# ============================================================================
# from tests/unit/test_incident_retrieval.py
# ============================================================================

def test_returns_empty_list_when_index_does_not_exist():
    client = MagicMock()
    client.indices.exists.return_value = False

    retrieval = IncidentRetrieval(client)
    result = retrieval.retrieve_analogues(query_vector=[0.1, 0.2, 0.3])

    assert result == []
    client.search.assert_not_called()


def test_returns_source_documents_from_knn_hits():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.search.return_value = {
        "hits": {
            "hits": [
                {"_id": "1", "_score": 0.98, "_source": {"service": "checkout-service", "cause": "db_lock"}},
                {"_id": "2", "_score": 0.91, "_source": {"service": "checkout-service", "cause": "cpu_saturation"}},
            ]
        }
    }

    retrieval = IncidentRetrieval(client)
    result = retrieval.retrieve_analogues(query_vector=[0.1, 0.2, 0.3], k=2)

    assert result == [
        {"service": "checkout-service", "cause": "db_lock"},
        {"service": "checkout-service", "cause": "cpu_saturation"},
    ]


def test_knn_query_uses_the_requested_vector_and_k():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.search.return_value = {"hits": {"hits": []}}

    retrieval = IncidentRetrieval(client, index_name="historical-incidents")
    retrieval.retrieve_analogues(query_vector=[1.0, 2.0, 3.0], k=5)

    _, kwargs = client.search.call_args
    assert kwargs["index"] == "historical-incidents"
    knn = kwargs["body"]["query"]["knn"]["incident_vector"]
    assert knn["vector"] == [1.0, 2.0, 3.0]
    assert knn["k"] == 5
    assert "filter" not in knn


def test_service_filter_is_applied_when_provided():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.search.return_value = {"hits": {"hits": []}}

    retrieval = IncidentRetrieval(client)
    retrieval.retrieve_analogues(query_vector=[0.1, 0.2, 0.3], service="payment-service")

    _, kwargs = client.search.call_args
    knn_filter = kwargs["body"]["query"]["knn"]["incident_vector"]["filter"]
    assert knn_filter == {"term": {"service": "payment-service"}}


def test_returns_empty_list_on_search_failure_rather_than_raising():
    client = MagicMock()
    client.indices.exists.return_value = True
    client.search.side_effect = Exception("cluster unreachable")

    retrieval = IncidentRetrieval(client)
    result = retrieval.retrieve_analogues(query_vector=[0.1, 0.2, 0.3])

    assert result == []


# ============================================================================
# from tests/unit/test_query_executor_context_bounding.py
# ============================================================================

def _response_with_rows(n):
    return {
        "schema": [{"name": "duration_ms", "type": "double"}],
        "datarows": [[100 + i] for i in range(n)],
        "total": n,
        "size": n,
    }


def test_result_within_the_default_bound_is_returned_untouched():
    client = MagicMock()
    client.transport.perform_request.return_value = _response_with_rows(5)
    executor = QueryExecutor(client)

    result = executor.execute_ppl("source=traces-*")

    assert len(result["data"]["datarows"]) == 5
    assert "rows_shown" not in result["data"]
    assert "rows_truncated_for_context" not in result["data"]


def test_result_beyond_the_default_bound_is_truncated_for_context():
    client = MagicMock()
    client.transport.perform_request.return_value = _response_with_rows(500)
    executor = QueryExecutor(client)

    result = executor.execute_ppl("source=traces-*")

    assert len(result["data"]["datarows"]) == QueryExecutor.DEFAULT_MAX_ROWS_IN_CONTEXT == 20
    assert result["data"]["rows_shown"] == 20
    assert result["data"]["rows_truncated_for_context"] == 480
    # The true count from OpenSearch's own response is preserved, not overwritten.
    assert result["data"]["total"] == 500


def test_max_rows_in_context_is_configurable():
    client = MagicMock()
    client.transport.perform_request.return_value = _response_with_rows(500)
    executor = QueryExecutor(client)

    result = executor.execute_ppl("source=traces-*", max_rows_in_context=3)

    assert len(result["data"]["datarows"]) == 3
    assert result["data"]["rows_truncated_for_context"] == 497


def test_max_rows_in_context_none_disables_truncation():
    client = MagicMock()
    client.transport.perform_request.return_value = _response_with_rows(500)
    executor = QueryExecutor(client)

    result = executor.execute_ppl("source=traces-*", max_rows_in_context=None)

    assert len(result["data"]["datarows"]) == 500
    assert "rows_shown" not in result["data"]


def test_result_hash_covers_the_full_untruncated_response_not_just_the_sample():
    # Auditability shouldn't degrade because the agent only saw a sample --
    # the hash must be a fingerprint of everything OpenSearch actually
    # returned, so it stays independently reproducible/verifiable.
    client = MagicMock()
    client.transport.perform_request.return_value = _response_with_rows(500)
    executor = QueryExecutor(client)

    truncated = executor.execute_ppl("source=traces-*", max_rows_in_context=5)
    full = executor.execute_ppl("source=traces-*", max_rows_in_context=None)

    assert truncated["result_hash"] == full["result_hash"]
    assert len(truncated["data"]["datarows"]) == 5
    assert len(full["data"]["datarows"]) == 500


def test_response_with_no_datarows_is_unaffected():
    client = MagicMock()
    client.transport.perform_request.return_value = {"acknowledged": True}
    executor = QueryExecutor(client)

    result = executor.execute_ppl("source=traces-*")

    assert result["data"] == {"acknowledged": True}
