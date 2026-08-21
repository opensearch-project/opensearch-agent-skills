"""The narration guard: what an agent may say about a run it did not compute.

Every rule in `provenance_guard.py` is exercised in both directions here -- a
narration that obeys it and one that breaks it -- because a guard that only ever
sees clean input is indistinguishable from a guard that always passes.
"""

import provenance_guard as pg

REPORT = """\
VERDICT: SUBSTANTIATED
OBSERVATION: latency_ms in focus window = 451.37 vs baseline 92.10 (4.9x)

REFUTATION ATTEMPTS (what was actually checked):
  [NOT_REFUTED  ] sample_size_collapse
       focus n=200 vs baseline typical n=198 (ratio 1.010)
  [NOT_REFUTED  ] estimator_choice
       `tdigest` sees +359.27, `hdr` sees +341.00 over the same documents (95% as
       large) -- both rulers see it; they disagree about its size by 5%

TRAVERSAL:
  [CONFIRMED   ] latency_ms rose +359.27 in 2026-08-02T14:20:00.000Z
       accounts for: 312.40

MAGNITUDE: UNDER_ACCOUNTED
  observed effect     +359.27
  accounted for       +312.40
  unexplained          +46.87 (+13.0% of the effect)
  tolerance           20%

GATE 2: NOT CLOSED
"""

CLOSED_REPORT = REPORT.replace("GATE 2: NOT CLOSED", pg.CLOSED_MARKER)


def test_a_narration_using_only_reported_figures_is_grounded():
    narration = ("p99 went from 92.10 to 451.37 in the window starting "
                 "2026-08-02T14:20:00.000Z. One branch accounts for 312.40 of the "
                 "359.27 rise, leaving 46.87 unexplained.")
    assert pg.check(REPORT, narration).verdict is pg.Verdict.GROUNDED


def test_a_number_the_gates_never_computed_is_named():
    # 87% is a plausible-looking share of the effect. Nothing produced it.
    narration = "One branch accounts for 87% of the rise."
    result = pg.check(REPORT, narration)
    assert result.verdict is pg.Verdict.UNSOURCED
    # Reported as written, percent sign kept: 87 and 87% are not the same claim,
    # and the reader has to be shown the one that was actually made.
    assert "87%" in result.unsourced_numbers


def test_rounding_to_fewer_decimals_is_allowed():
    # Precision lost, none invented.
    assert pg.check(REPORT, "p99 reached 451 ms.").verdict is pg.Verdict.GROUNDED


def test_gaining_precision_is_refused():
    # The report says 92.10. A narration saying 92.104 has stated the number
    # more finely than anything measured it.
    result = pg.check(REPORT, "The baseline was 92.104 ms.")
    assert result.verdict is pg.Verdict.UNSOURCED
    assert "92.104" in result.unsourced_numbers


def test_a_percentage_may_be_rendered_as_a_fraction_and_the_reverse():
    # 13.0% in the report, 0.13 in the narration: same number, other rendering.
    assert pg.check(REPORT, "The residual is 0.13 of the effect.").verdict is pg.Verdict.GROUNDED


def test_a_moment_the_run_never_mentioned_is_caught():
    result = pg.check(REPORT, "The spike began at 2026-08-02T15:40:00.000Z.")
    assert result.verdict is pg.Verdict.UNSOURCED
    assert result.unsourced_timestamps == ["2026-08-02T15:40:00.000Z"]


def test_a_timestamp_is_not_taken_apart_into_integers():
    # Decomposing the window into 2026, 08, 02, 14, 20 would demand the report
    # contain five integers it has no reason to contain, and would then report
    # five fabrications where there are none.
    result = pg.check(REPORT, "The window starting 2026-08-02T14:20:00.000Z is the one audited.")
    assert result.verdict is pg.Verdict.GROUNDED
    assert result.unsourced_numbers == []


def test_list_markers_are_formatting_not_claims():
    narration = "1. p99 reached 451.37\n2. the residual is 46.87\n3. nothing closed"
    assert pg.check(REPORT, narration).verdict is pg.Verdict.GROUNDED


def test_naming_a_cause_is_refused_however_grounded_the_numbers_are():
    narration = "The root cause is the checkout path; it accounts for 312.40."
    result = pg.check(REPORT, narration)
    assert result.verdict is pg.Verdict.CONTRACT_VIOLATION
    assert any(kind == "names a cause" for kind, _ in result.contract_violations)


def test_asserting_closure_is_refused_when_the_report_denies_it():
    result = pg.check(REPORT, "That fully explains the regression.")
    assert result.verdict is pg.Verdict.CONTRACT_VIOLATION
    assert any("closure" in kind for kind, _ in result.contract_violations)


def test_the_same_phrase_is_allowed_when_the_report_did_close():
    # A report that closed is entitled to be narrated as one. The guard checks
    # the narration against the run, not against a vocabulary.
    result = pg.check(CLOSED_REPORT, "That fully explains the regression.")
    assert result.verdict is pg.Verdict.GROUNDED


def test_calling_the_divergence_a_confidence_interval_is_always_refused():
    # SKILL.md says in as many words that two estimators are not one.
    result = pg.check(CLOSED_REPORT, "The two estimators give a 5% confidence interval.")
    assert result.verdict is pg.Verdict.CONTRACT_VIOLATION
    assert any("precision" in kind for kind, _ in result.contract_violations)


def test_contract_violations_outrank_unsourced_numbers():
    # Both are wrong; the reader is told about the worse one first rather than
    # being handed a list of digits while a causal claim sits above it.
    result = pg.check(REPORT, "The root cause is deploy 4471, which explains 87%.")
    assert result.verdict is pg.Verdict.CONTRACT_VIOLATION
    assert result.unsourced_numbers  # still recorded, not discarded


def test_an_empty_narration_is_vacuously_grounded_and_says_how_many_it_checked():
    result = pg.check(REPORT, "Nothing to add.")
    assert result.verdict is pg.Verdict.GROUNDED
    assert result.checked_numbers == 0


def test_closure_detection_reads_the_marker_the_runner_actually_prints():
    assert pg.report_says_closed(CLOSED_REPORT)
    assert not pg.report_says_closed(REPORT)
