"""What the reporter's number was, computed instead of improvised.

`observation_moment` refutes a report filed before its window finished, and
that refutation is about *comparability*: the auditor and the reporter are not
holding the same documents. It says nothing about whether the reporter's number
was wrong.

A narration does not stop there. In the agent A/B, two runs of this skill
rebuilt the same 46-document slice by hand and read different statistics off it
-- p99, 77% above the settled value, "the report was untrustworthy"; p50, equal
to it, "the report was not misleading". Both numbers were real, both runs had
read SKILL.md, and nothing in it said which reading answers the question.

So the reading is computed: the statistic the claim is about, over the documents
an ingest clock places before the report time. The load-bearing test in this
file is not that the number is right. It is that the number **cannot change the
verdict** -- a reconstruction that agrees with the settled value must not become
a way for an early report to be cleared.
"""

import pytest

import audit_window as aw
from premise_audit import Observation, Outcome, probe_observation_moment

FOCUS_START = "2026-08-03T01:30:00Z"
FOCUS_END = "2026-08-03T01:40:00Z"
EARLY = "2026-08-03T01:32:00Z"   # 20% elapsed
COMPLETE = "2026-08-03T01:40:00Z"


class FakeCluster:
    def __init__(self, total=46, value=3418.66):
        self.total, self.value = total, value
        self.bodies = []

    def __call__(self, endpoint, path, body=None):
        self.bodies.append(body)
        return {
            "hits": {"total": {"value": self.total, "relation": "eq"}},
            "aggregations": {
                "tdigest": {"values": {"99.0": self.value}},
                "hdr": {"values": {"99.0": self.value}},
            },
        }


def _observation(**overrides):
    base = dict(
        metric="latency_ms", focus_value=1934.0, baseline_value=312.0,
        window_start=FOCUS_START, window_end=FOCUS_END, reported_at=EARLY,
        focus_count=200, baseline_typical_count=200,
    )
    base.update(overrides)
    return Observation(**base)


# --------------------------------------------------------------------------
# Reading it
# --------------------------------------------------------------------------

def test_the_reconstruction_asks_the_ingest_clock_which_documents_existed(monkeypatch):
    fake = FakeCluster()
    monkeypatch.setattr(aw, "_get", fake)

    value, n = aw.value_as_reported("e", "logs-*", "@timestamp", "latency_ms",
                                    "ingested_at", FOCUS_START, FOCUS_END, EARLY)

    assert (value, n) == (3418.66, 46)
    filters = fake.bodies[-1]["query"]["bool"]["filter"]
    assert {"range": {"@timestamp": {"gte": FOCUS_START, "lt": FOCUS_END}}} in filters
    assert {"range": {"ingested_at": {"lt": EARLY}}} in filters


def test_it_reads_the_statistic_the_claim_is_about_not_a_second_one(monkeypatch):
    """One percentile, the same one the rest of the audit argues over."""
    fake = FakeCluster()
    monkeypatch.setattr(aw, "_get", fake)
    aw.value_as_reported("e", "i", "@timestamp", "latency_ms", "ingested_at",
                         FOCUS_START, FOCUS_END, EARLY)

    percents = fake.bodies[-1]["aggs"]["tdigest"]["percentiles"]["percents"]
    assert percents == [99]


def test_an_index_with_one_clock_cannot_reconstruct_and_does_not_pretend_to(monkeypatch):
    monkeypatch.setattr(aw, "_get", FakeCluster())
    assert aw.value_as_reported("e", "i", "@timestamp", "latency_ms", None,
                                FOCUS_START, FOCUS_END, EARLY) == (None, None)


def test_a_report_with_no_time_has_nothing_to_reconstruct_against(monkeypatch):
    monkeypatch.setattr(aw, "_get", FakeCluster())
    assert aw.value_as_reported("e", "i", "@timestamp", "latency_ms", "ingested_at",
                                FOCUS_START, FOCUS_END, None) == (None, None)


def test_nothing_ingested_by_then_is_reported_as_zero_documents(monkeypatch):
    monkeypatch.setattr(aw, "_get", FakeCluster(total=0))
    assert aw.value_as_reported("e", "i", "@timestamp", "latency_ms", "ingested_at",
                                FOCUS_START, FOCUS_END, EARLY) == (None, 0)


# --------------------------------------------------------------------------
# It may not decide anything
# --------------------------------------------------------------------------

@pytest.mark.parametrize("as_reported", [3418.66, 1934.0, 509.99, None])
def test_the_reconstruction_never_changes_the_verdict(as_reported):
    """Agreeing with the settled value must not clear an early report.

    The probe refuted comparability. A number that happens to match does not
    make the reporter and the auditor have been looking at the same documents,
    and if it could clear the probe it would be an escape hatch reachable by
    luck.
    """
    result = probe_observation_moment(_observation(
        focus_value_as_reported=as_reported,
        focus_count_as_reported=46 if as_reported is not None else None,
        second_clock_field="ingested_at",
    ))
    assert result.outcome is Outcome.REFUTED


def test_a_window_that_finished_is_not_refuted_and_carries_no_reconstruction():
    result = probe_observation_moment(_observation(
        reported_at=COMPLETE, focus_value_as_reported=1934.0, focus_count_as_reported=200))
    assert result.outcome is Outcome.NOT_REFUTED
    assert "ingest clock" not in result.evidence


# --------------------------------------------------------------------------
# Saying it
# --------------------------------------------------------------------------

def test_the_evidence_carries_both_readings_and_the_count_behind_the_early_one():
    ev = probe_observation_moment(_observation(
        focus_value_as_reported=3418.66, focus_count_as_reported=46)).evidence

    assert "46 document(s)" in ev
    assert "3418.66" in ev
    assert "1934.0" in ev


def test_the_evidence_refuses_to_call_the_reconstruction_the_reporters_screen():
    ev = probe_observation_moment(_observation(
        focus_value_as_reported=3418.66, focus_count_as_reported=46)).evidence
    assert "it is not that screen" in ev


def test_an_unreconstructable_gap_is_named_as_unquantified_not_as_small():
    ev = probe_observation_moment(_observation()).evidence

    assert "unquantified" in ev
    assert "not the same as small" in ev


def test_no_documents_ingested_by_then_says_so_rather_than_reading_zero():
    ev = probe_observation_moment(_observation(focus_count_as_reported=0)).evidence
    assert "No document had been ingested by then" in ev
