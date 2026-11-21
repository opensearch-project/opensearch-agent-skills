"""Gate 1 verdict precedence.

No running cluster: judgment operates on plain fact objects by design.

These tests exist to pin the rule that makes a pass mean something -- a pass is
an optimistic claim, valid only because a full pessimistic sweep ran and came
back empty. Weaken any part of that and one of these should go red.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "observability" / "unclosed" / "scripts"),
)

from premise_audit import (  # noqa: E402
    MIN_COMPOSITION_N,
    PROBES,
    Observation,
    Outcome,
    ProbeResult,
    Provenance,
    Verdict,
    audit,
    estimator_divergence,
    decide,
)


EVEN = {"/api/checkout": 0.25, "/api/search": 0.25, "/api/cart": 0.25, "/api/profile": 0.25}

WINDOW_START = "2026-08-01T14:20:00Z"
WINDOW_END = "2026-08-01T14:30:00Z"
AFTER_WINDOW = "2026-08-01T14:31:00Z"


def healthy(**overrides):
    base = dict(
        metric="latency_ms",
        focus_value=1800.0,
        baseline_value=330.0,
        # A second estimator over the same documents. Present in the healthy
        # fixture because a sweep that cannot ask "does the effect survive a
        # different ruler" is an incomplete sweep, and an incomplete sweep may
        # not substantiate anything.
        focus_value_alt=1755.0,
        baseline_value_alt=325.0,
        estimator="tdigest",
        estimator_alt="hdr",
        provenance=Provenance.EXTERNAL_REPORT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        reported_at=AFTER_WINDOW,
        focus_count=200,
        baseline_typical_count=200,
        focus_composition=EVEN,
        baseline_composition=EVEN,
        focus_ingest_lag_p50_s=2.2,
        baseline_ingest_lag_p50_s=2.3,
        second_clock_field="ingested_at",
        resolved_indices=["logs-000001"],
        metric_field_types={"logs-000001": "float"},
    )
    base.update(overrides)
    return Observation(**base)


# --- precedence -----------------------------------------------------------


def test_pass_requires_every_attempt_to_have_run_and_failed():
    assert audit(healthy()).verdict is Verdict.SUBSTANTIATED


def test_one_successful_refutation_is_decisive():
    """Finding the artifact does not require finishing the sweep."""
    report = audit(healthy(focus_count=3))
    assert report.verdict is Verdict.ARTIFACT


def test_unrunnable_probe_blocks_the_pass():
    """Not knocked down is not cleared when a line of attack was never available."""
    report = audit(healthy(second_clock_field=None, focus_ingest_lag_p50_s=None, baseline_ingest_lag_p50_s=None))
    assert report.verdict is Verdict.UNDECIDABLE
    assert any("second time field" in m for m in report.missing_inputs)


def test_refutation_outranks_an_unrunnable_probe():
    report = audit(healthy(focus_count=3, resolved_indices=None, metric_field_types=None))
    assert report.verdict is Verdict.ARTIFACT


# --- the third state cannot be an escape hatch ----------------------------


def test_undecidable_must_name_what_is_missing():
    with pytest.raises(ValueError):
        ProbeResult("p", "story", Outcome.COULD_NOT_RUN, "no idea", missing=None)


def test_every_undecidable_verdict_carries_at_least_one_named_gap():
    report = audit(healthy(focus_composition=None, baseline_composition=None))
    assert report.verdict is Verdict.UNDECIDABLE
    assert report.missing_inputs and all(m for m in report.missing_inputs)


# --- probe independence ---------------------------------------------------


def test_composition_probe_declines_instead_of_firing_on_small_samples():
    """The population check must not re-detect what the volume check found.

    Below a usable sample size the composition cannot match a large baseline no
    matter what the system did. If this probe fired there, ARTIFACT would rest
    on two lines of evidence that are really one -- and legitimately low-traffic
    windows would be judged artifacts.
    """
    skewed = {"/api/checkout": 1.0}
    report = audit(healthy(focus_count=3, focus_composition=skewed))
    population = next(p for p in report.probes if p.probe == "population_shift")
    assert population.outcome is Outcome.COULD_NOT_RUN
    assert str(MIN_COMPOSITION_N) in population.missing


def test_composition_probe_does_fire_when_the_sample_supports_it():
    """The guard must not neuter the probe -- it still catches real shifts."""
    skewed = {"/api/checkout": 0.95, "/api/search": 0.05}
    report = audit(healthy(focus_composition=skewed))
    population = next(p for p in report.probes if p.probe == "population_shift")
    assert population.outcome is Outcome.REFUTED
    assert report.verdict is Verdict.ARTIFACT


# --- the record is the basis of the pass, not decoration ------------------


def test_pass_reports_every_attempt_it_relied_on():
    report = audit(healthy())
    assert len(report.probes) == len(PROBES)
    assert all(p.evidence for p in report.probes)
    assert "rests on the record above" in report.to_text()


# --- provenance: the auditor must not author the premise ------------------


def test_a_report_that_names_no_moment_is_an_artifact_not_an_open_question():
    """Missing data sends you to the cluster. A missing claim sends you to the reporter.

    An unanchored report cannot be contradicted by any evidence, so it cannot be
    supported by any either. Grading it UNDECIDABLE would grant it a standing it
    never earned and would invite an agent to go pick a window itself.
    """
    report = audit(healthy(window_start=None, window_end=None))
    assert report.verdict is Verdict.ARTIFACT
    unanchored = next(p for p in report.probes if p.probe == "unanchored_report")
    assert unanchored.outcome is Outcome.REFUTED


def test_a_self_selected_window_can_never_be_substantiated():
    """Every dataset has a maximum. Confirming the one you picked proves nothing."""
    report = audit(healthy(provenance=Provenance.SELF_SELECTED))
    assert report.verdict is not Verdict.SUBSTANTIATED
    assert any("specified before the data was examined" in m for m in report.missing_inputs)


def test_a_self_selected_window_can_still_be_refuted():
    """The wall blocks passes, not findings.

    Discovering an artifact does not depend on the window having been named in
    advance, so scanning stays useful for exactly that.
    """
    report = audit(healthy(provenance=Provenance.SELF_SELECTED, focus_count=3))
    assert report.verdict is Verdict.ARTIFACT


def test_unknown_provenance_blocks_the_pass():
    report = audit(healthy(provenance=Provenance.UNKNOWN))
    assert report.verdict is Verdict.UNDECIDABLE


def test_external_report_without_a_report_time_is_an_unbacked_claim():
    """A provenance label anyone can type is not provenance.

    The timestamp is what makes "someone reported this" checkable rather than
    asserted, so a pass may not rest on the label alone.
    """
    report = audit(healthy(reported_at=None))
    assert report.verdict is Verdict.UNDECIDABLE
    assert any("report timestamp" in m or "moment the observation was made" in m
               for m in report.missing_inputs)


def test_a_window_judged_before_it_finished_is_an_artifact():
    """The alert saw n=40 in a two-minute-old bucket; the audit sees n=200.

    Same index, same window, same documents as the substantiated case -- only
    the moment of observation differs. If this passed, the auditor and the
    reporter would be silently looking at two different datasets.
    """
    partial = audit(healthy(reported_at="2026-08-01T14:22:00Z"))
    complete = audit(healthy(reported_at=AFTER_WINDOW))

    assert partial.verdict is Verdict.ARTIFACT
    assert complete.verdict is Verdict.SUBSTANTIATED

    moment = next(p for p in partial.probes if p.probe == "observation_moment")
    assert moment.outcome is Outcome.REFUTED
    assert "20% elapsed" in moment.evidence


# --- the ruler is part of the claim ---------------------------------------


def test_a_single_estimator_cannot_substantiate_its_own_reading():
    """A percentile is an estimate, and which estimator produced it is a choice
    nobody records. With one ruler the number cannot be separated from the method."""
    report = audit(healthy(focus_value_alt=None, baseline_value_alt=None, estimator_alt=None))
    assert report.verdict is Verdict.UNDECIDABLE
    assert any("second percentile estimator" in m for m in report.missing_inputs)


def test_an_effect_only_one_estimator_can_see_is_an_artifact():
    """5x in tdigest and nothing in hdr, over identical documents. The jump is a
    property of the ruler, and no investigation should start from it."""
    report = audit(healthy(focus_value_alt=340.0, baseline_value_alt=325.0))
    assert report.verdict is Verdict.ARTIFACT
    probe = next(p for p in report.probes if p.probe == "estimator_choice")
    assert probe.outcome is Outcome.REFUTED


def test_estimators_that_disagree_only_about_size_do_not_refute():
    """Both rulers see it; they size it differently. That is not grounds to throw
    the observation out -- it is grounds to stop claiming a precision nobody has."""
    report = audit(healthy(focus_value_alt=1450.0, baseline_value_alt=325.0))
    probe = next(p for p in report.probes if p.probe == "estimator_choice")
    assert probe.outcome is Outcome.NOT_REFUTED
    assert report.verdict is Verdict.SUBSTANTIATED
    assert "disagree about its size" in probe.evidence


def test_the_divergence_is_available_to_gate_3_as_a_number():
    obs = healthy(focus_value_alt=1450.0, baseline_value_alt=325.0)
    # tdigest 1800-330 = 1470; hdr 1450-325 = 1125
    assert estimator_divergence(obs) == pytest.approx((1470 - 1125) / 1470)


def test_divergence_is_absent_rather_than_zero_when_there_is_one_ruler():
    """Zero would say the rulers agree. Nothing was compared."""
    assert estimator_divergence(healthy(focus_value_alt=None, baseline_value_alt=None)) is None


def test_decide_rejects_a_pass_built_from_an_incomplete_sweep():
    probes = [
        ProbeResult("a", "s", Outcome.NOT_REFUTED, "ran"),
        ProbeResult("b", "s", Outcome.COULD_NOT_RUN, "did not run", missing="input b"),
    ]
    assert decide(probes) is Verdict.UNDECIDABLE
