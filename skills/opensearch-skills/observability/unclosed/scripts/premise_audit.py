#!/usr/bin/env python3
"""Gate 1 -- premise audit.

Before asking *why* an observation happened, ask whether the observation is
real. A percentile chart cannot tell a regression from an artifact of its own
measurement, and both look identical to a threshold.

Design
------
Each check is not an inspection. It is an **attempt to refute the observation**
by telling a specific alternative story in which nothing actually got worse.
An attempt returns one of three outcomes:

    REFUTED        the alternative story holds; the observation is an artifact
    NOT_REFUTED    the attempt ran in full and failed to knock the observation down
    COULD_NOT_RUN  the attempt needs an input that is absent, and names it

Verdict precedence
------------------
    ARTIFACT       any single attempt refuted the observation.
                   Finding the artifact is decisive and does not require
                   completing the sweep.

    SUBSTANTIATED  every attempt ran AND every attempt failed to refute.
                   A pass is an optimistic claim, and an optimistic claim is
                   only safe when something pessimistic verified it. This is
                   that verification: the observation stands because a full
                   adversarial sweep came back empty, not because nothing was
                   noticed.

    UNDECIDABLE    nothing refuted it, but at least one attempt could not run.
                   Failing to knock something down is not the same as clearing
                   it when one line of attack was never available.

This precedence is what keeps UNDECIDABLE from becoming an escape hatch: it is
unreachable by uncertainty. It requires a probe that needed a *nameable* input
which was absent. "I am not sure" cannot produce it.

Every verdict carries the full probe record. For SUBSTANTIATED that record is
not decoration -- it is the entire basis of the pass.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Outcome(str, Enum):
    REFUTED = "REFUTED"
    NOT_REFUTED = "NOT_REFUTED"
    COULD_NOT_RUN = "COULD_NOT_RUN"


class Verdict(str, Enum):
    ARTIFACT = "ARTIFACT"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNDECIDABLE = "UNDECIDABLE"


class Provenance(str, Enum):
    """Where the observation came from.

    This is not bookkeeping. An auditor that selects its own subject has merged
    the role of the one who claims with the role of the one who checks, and no
    amount of rigor downstream repairs that: the information "who chose this
    window, before or after seeing the data" does not exist in the data. It
    exists in the origin of the question.
    """

    EXTERNAL_REPORT = "EXTERNAL_REPORT"  # a human, an alert, or another agent named a window
    SELF_SELECTED = "SELF_SELECTED"      # this tool scanned and picked the worst bucket
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProbeResult:
    probe: str
    artifact_story: str
    outcome: Outcome
    evidence: str
    missing: Optional[str] = None

    def __post_init__(self):
        # A COULD_NOT_RUN without a named missing input would be exactly the
        # escape hatch this design exists to prevent. Fail loudly instead.
        if self.outcome is Outcome.COULD_NOT_RUN and not self.missing:
            raise ValueError(f"probe {self.probe!r}: COULD_NOT_RUN must name the missing input")
        if self.outcome is not Outcome.COULD_NOT_RUN and self.missing:
            raise ValueError(f"probe {self.probe!r}: only COULD_NOT_RUN may name a missing input")


@dataclass(frozen=True)
class Observation:
    """The facts a premise audit reasons over.

    Deliberately plain data. Retrieval lives elsewhere so that judgment can be
    tested without a running cluster, and so a probe can never quietly widen
    its own evidence by issuing another query mid-decision.

    `None` means "this input was not available", which is materially different
    from zero and is what drives COULD_NOT_RUN.
    """

    metric: str
    focus_value: float
    baseline_value: float

    # The same two numbers read by a second estimator. A percentile from an
    # aggregation is not a measurement of the data, it is an estimate computed
    # from it, and the estimator is a choice nobody records. Two of them applied
    # to the same documents make that choice visible.
    focus_value_alt: Optional[float] = None
    baseline_value_alt: Optional[float] = None
    estimator: str = "primary"
    estimator_alt: Optional[str] = None

    # --- provenance of the claim itself -----------------------------------
    # Answered before any question about the system, because these decide
    # whether there is a claim to examine at all.
    provenance: Provenance = Provenance.UNKNOWN
    window_start: Optional[str] = None  # the moment being claimed about
    window_end: Optional[str] = None
    reported_at: Optional[str] = None  # the moment the claim was made

    focus_count: Optional[int] = None
    baseline_typical_count: Optional[int] = None

    # The same statistic, over the documents an ingest clock says had landed by
    # `reported_at`. Present only when the index carries a second clock and a
    # report time was given. `None` is absent, not equal: the reconstruction was
    # not available, which is different from it having come back the same.
    #
    # This exists because refuting a report as early does not say whether the
    # reporter's *number* was wrong, and every narration wants to say so anyway.
    # Left to pick a statistic it picks one, and p99 and p50 over a part-filled
    # window support opposite sentences. So the reading is computed here, from
    # the statistic the claim is about, rather than chosen downstream.
    focus_value_as_reported: Optional[float] = None
    focus_count_as_reported: Optional[int] = None

    # Categorical composition, e.g. {"/api/checkout": 0.51, ...}. Absent when
    # the index carries no dimension to group by.
    focus_composition: Optional[dict] = None
    baseline_composition: Optional[dict] = None

    # Seconds between event time and ingest time. Absent when the index has
    # only one clock -- in which case the question cannot be asked at all.
    focus_ingest_lag_p50_s: Optional[float] = None
    baseline_ingest_lag_p50_s: Optional[float] = None
    second_clock_field: Optional[str] = None

    # Concrete indices the window resolved to, and the mapping type of the
    # measured field in each.
    resolved_indices: Optional[list] = None
    metric_field_types: Optional[dict] = None

    # --- provenance of the *scan*, one level out from the claim -------------
    # `window_start`/`window_end` say which window is being argued about.
    # These say which range was swept to find it, and -- the part that is
    # otherwise unrecoverable -- which clock fixed that range. A lookback taken
    # from the wall clock produces a different range on every run over the same
    # static index, and nothing in the output would show it. Recorded rather
    # than probed: no probe can refute a window on this, because by the time a
    # probe sees the observation the range has already been chosen.
    scan_window_start: Optional[str] = None
    scan_window_end: Optional[str] = None
    scan_anchor: Optional[str] = None
    scan_anchor_source: Optional[str] = None


@dataclass
class AuditReport:
    verdict: Verdict
    observation_summary: str
    probes: list = field(default_factory=list)
    #: Which range was swept and which clock fixed it. Printed because a reader
    #: cannot otherwise tell whether re-running this command would examine the
    #: same buckets.
    scan_summary: Optional[str] = None

    @property
    def missing_inputs(self):
        return [p.missing for p in self.probes if p.outcome is Outcome.COULD_NOT_RUN]

    def to_text(self) -> str:
        lines = [
            f"VERDICT: {self.verdict.value}",
            f"OBSERVATION: {self.observation_summary}",
        ]
        if self.scan_summary:
            lines.append(f"SCAN: {self.scan_summary}")
        lines += [
            "",
            "REFUTATION ATTEMPTS (what was actually checked):",
        ]
        for p in self.probes:
            lines.append(f"  [{p.outcome.value:<13}] {p.probe}")
            lines.append(f"       tried to show: {p.artifact_story}")
            lines.append(f"       {p.evidence}")
            if p.missing:
                lines.append(f"       MISSING: {p.missing}")
        lines.append("")
        if self.verdict is Verdict.ARTIFACT:
            killers = [p.probe for p in self.probes if p.outcome is Outcome.REFUTED]
            lines.append(f"The observation is explained by how it was measured: {', '.join(killers)}.")
            lines.append("No causal investigation should proceed from this premise.")
        elif self.verdict is Verdict.SUBSTANTIATED:
            lines.append("Every refutation attempt ran and every one failed. The observation stands.")
            lines.append("This pass rests on the record above, not on the absence of a complaint.")
        else:
            lines.append("Nothing refuted the observation, but the sweep is incomplete.")
            lines.append("Not knocked down is not the same as cleared. Missing:")
            for m in self.missing_inputs:
                lines.append(f"  - {m}")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Refutation attempts
# --------------------------------------------------------------------------

COLLAPSE_RATIO = 0.25  # focus volume below this fraction of baseline is a collapse
MIN_TRUSTWORTHY_N = 30
COMPOSITION_SHIFT = 0.25  # total variation distance above this is a different population
MIN_COMPOSITION_N = 30  # below this, composition is not estimable and the probe must decline
INGEST_LAG_MULTIPLE = 10.0  # focus lag this many times baseline suggests replay/backfill


MIN_WINDOW_ELAPSED = 0.9  # a window judged before this fraction had passed was judged incomplete


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def probe_unanchored_report(obs: Observation) -> ProbeResult:
    """Does the report name a moment at all?

    A report with no window is not a weak claim. It is not a claim. Nothing can
    contradict it, which means nothing can support it either, and every probe
    below would have nothing to bite on.

    This refutes rather than declining, and the distinction is operational:
    UNDECIDABLE sends you to collect more data, ARTIFACT sends you back to
    whoever filed the report. Here the data is not what is missing.
    """
    story = "there is no observation here -- the report never named a moment, so nothing about it could be wrong"
    start, end = _parse(obs.window_start), _parse(obs.window_end)
    if start is None or end is None:
        return ProbeResult(
            "unanchored_report", story, Outcome.REFUTED,
            f"window_start={obs.window_start!r} window_end={obs.window_end!r} "
            "-- an unfalsifiable report is not evidence of anything",
        )
    return ProbeResult("unanchored_report", story, Outcome.NOT_REFUTED,
                       f"window {obs.window_start} -> {obs.window_end} is a specific, checkable claim")


def _reconstruction(obs: Observation) -> str:
    """What the same statistic read over the documents that had landed by then.

    Carried as evidence, never as a verdict input. Whether the reporter's number
    matches the settled one does not change whether they were looking at the
    same data -- they were not, and that is what the probe refuted. What it
    changes is the sentence a reader is entitled to write next, and the point of
    computing it here is that the sentence stops depending on which percentile
    someone downstream reaches for.
    """
    if obs.focus_value_as_reported is None:
        if obs.focus_count_as_reported == 0:
            return (". No document had been ingested by then, so the reported number cannot be "
                    "reconstructed at all")
        return (". The reading the reporter had cannot be reconstructed: that needs an ingest "
                "clock to say which documents existed at the report time, and this index has none. "
                "How far the two differ is unquantified -- which is not the same as small")
    settled = obs.focus_value
    ev = (f". Same statistic over the {obs.focus_count_as_reported} document(s) an ingest clock "
          f"places before that moment: {obs.focus_value_as_reported} against {settled} once the "
          f"window filled")
    if settled:
        ev += f" ({obs.focus_value_as_reported / settled:.0%} of it)"
    return ev + (". Ingest order is the closest the index can come to what the reporter queried; "
                 "it is not that screen")


def probe_observation_moment(obs: Observation) -> ProbeResult:
    """When was this observed, and had the window finished by then?

    An alert evaluating a 10-minute bucket two minutes in is computing a
    percentile over a window that does not exist yet. By audit time the bucket
    is full and unremarkable -- so the auditor and the reporter are looking at
    two different datasets that share a name.

    Without a report time, that difference leaves no trace in the data at all.
    """
    story = "the reporter judged a window that had not finished; the incident existed only at evaluation time"
    reported = _parse(obs.reported_at)
    start, end = _parse(obs.window_start), _parse(obs.window_end)

    if reported is None:
        return ProbeResult(
            "observation_moment", story, Outcome.COULD_NOT_RUN,
            "the report does not say when it was made, so it cannot be compared to the window it describes",
            missing="the moment the observation was made (report/evaluation timestamp)",
        )
    if start is None or end is None:
        return ProbeResult(
            "observation_moment", story, Outcome.COULD_NOT_RUN,
            "no window to compare the report time against",
            missing="a specified observation window (start and end)",
        )

    span = (end - start).total_seconds()
    elapsed = (reported - start).total_seconds()
    fraction = elapsed / span if span else 0.0
    ev = (f"reported at {obs.reported_at}, window {obs.window_start} -> {obs.window_end} "
          f"({fraction:.0%} elapsed at report time)")
    if fraction < MIN_WINDOW_ELAPSED:
        return ProbeResult("observation_moment", story, Outcome.REFUTED,
                           ev + f" -- below {MIN_WINDOW_ELAPSED:.0%}; the reporter saw a partial window, "
                                "and the data audited here is not the data that triggered the report"
                           + _reconstruction(obs))
    return ProbeResult("observation_moment", story, Outcome.NOT_REFUTED,
                       ev + " -- the window was complete when it was judged")


def probe_who_chose_the_window(obs: Observation) -> ProbeResult:
    """Was the target drawn before or after the arrows landed?

    Any dataset has a maximum. A scan that selects its own worst bucket will
    always find one, and can never return "there is nothing here". Auditing that
    self-selected maximum and reporting that it is not an artifact is the
    sharpshooter drawing the bullseye around the holes.

    An EXTERNAL_REPORT claim with no report timestamp is just a word someone
    typed. The timestamp is what makes the provenance checkable rather than
    asserted, so it is required here too.
    """
    story = "the window was chosen after seeing the data, so finding something there proves nothing"
    if obs.provenance is Provenance.SELF_SELECTED:
        return ProbeResult(
            "window_provenance", story, Outcome.COULD_NOT_RUN,
            "this window was picked by scanning for the worst bucket, not reported by anyone",
            missing="an observation window specified before the data was examined (external report)",
        )
    if obs.provenance is Provenance.UNKNOWN:
        return ProbeResult(
            "window_provenance", story, Outcome.COULD_NOT_RUN,
            "the origin of this window was not recorded",
            missing="who reported this window (external report vs self-selected scan)",
        )
    if not obs.reported_at:
        return ProbeResult(
            "window_provenance", story, Outcome.COULD_NOT_RUN,
            "claims to be an external report but carries no report time, so the claim itself is unverifiable",
            missing="a report timestamp backing the EXTERNAL_REPORT claim",
        )
    return ProbeResult("window_provenance", story, Outcome.NOT_REFUTED,
                       f"externally reported at {obs.reported_at}; the window was named before this audit ran")


def probe_sample_size(obs: Observation) -> ProbeResult:
    story = "the change is arithmetic noise because almost no data landed in the window"
    if obs.focus_count is None or obs.baseline_typical_count is None:
        return ProbeResult(
            "sample_size_collapse", story, Outcome.COULD_NOT_RUN,
            "document counts per window were not retrieved",
            missing="per-window document counts (focus and baseline)",
        )
    ratio = obs.focus_count / obs.baseline_typical_count if obs.baseline_typical_count else 0.0
    ev = f"focus n={obs.focus_count} vs baseline typical n={obs.baseline_typical_count} (ratio {ratio:.3f})"
    if obs.focus_count < MIN_TRUSTWORTHY_N or ratio < COLLAPSE_RATIO:
        return ProbeResult("sample_size_collapse", story, Outcome.REFUTED,
                           ev + f" -- below n={MIN_TRUSTWORTHY_N} or {COLLAPSE_RATIO:.0%} of baseline")
    return ProbeResult("sample_size_collapse", story, Outcome.NOT_REFUTED,
                       ev + " -- volume held; the change is not a small-sample effect")


def probe_population_shift(obs: Observation) -> ProbeResult:
    story = "nothing got worse; a different mix of things is being measured"
    if not obs.focus_composition or not obs.baseline_composition:
        return ProbeResult(
            "population_shift", story, Outcome.COULD_NOT_RUN,
            "no categorical breakdown was retrieved for either window",
            missing="a grouping dimension (e.g. endpoint, region, client) broken down per window",
        )

    # Independence guard. Below a usable sample size the observed composition
    # cannot match a large baseline no matter what the system did, so this probe
    # would fire on volume alone -- re-detecting what probe_sample_size already
    # found, while looking like a second, independent line of attack. That
    # inflates confidence in ARTIFACT and, worse, manufactures ARTIFACT verdicts
    # for legitimately low-traffic windows (off-peak hours, small regions).
    #
    # The verdict rule "every attempt ran and failed" is only as strong as the
    # attempts being independent. So this one declines to answer instead.
    if obs.focus_count is not None and obs.focus_count < MIN_COMPOSITION_N:
        return ProbeResult(
            "population_shift", story, Outcome.COULD_NOT_RUN,
            f"focus window holds {obs.focus_count} documents; composition is not estimable at that size",
            missing=(f"at least {MIN_COMPOSITION_N} documents in the focus window to compare composition "
                     f"(have {obs.focus_count})"),
        )

    keys = set(obs.focus_composition) | set(obs.baseline_composition)
    tvd = 0.5 * sum(abs(obs.focus_composition.get(k, 0.0) - obs.baseline_composition.get(k, 0.0)) for k in keys)
    ev = f"composition distance {tvd:.3f} across {len(keys)} categories"
    if tvd > COMPOSITION_SHIFT:
        return ProbeResult("population_shift", story, Outcome.REFUTED,
                           ev + f" -- exceeds {COMPOSITION_SHIFT}; the two windows are not comparable")
    return ProbeResult("population_shift", story, Outcome.NOT_REFUTED,
                       ev + " -- same population; the comparison is like-for-like")


def probe_clock_semantics(obs: Observation) -> ProbeResult:
    story = "the window is an ingest artifact -- a replay or backfill, not live traffic"
    if obs.second_clock_field is None or obs.focus_ingest_lag_p50_s is None or obs.baseline_ingest_lag_p50_s is None:
        return ProbeResult(
            "clock_semantics", story, Outcome.COULD_NOT_RUN,
            "the index exposes a single time field, so event time and ingest time cannot be compared",
            missing="a second time field (ingest/observed time) alongside the event timestamp",
        )
    base = obs.baseline_ingest_lag_p50_s or 0.001
    multiple = obs.focus_ingest_lag_p50_s / base
    ev = (f"ingest lag p50: focus {obs.focus_ingest_lag_p50_s:.1f}s vs baseline "
          f"{obs.baseline_ingest_lag_p50_s:.1f}s ({multiple:.1f}x), second clock `{obs.second_clock_field}`")
    if multiple >= INGEST_LAG_MULTIPLE:
        return ProbeResult("clock_semantics", story, Outcome.REFUTED,
                           ev + " -- these events were written long after they occurred")
    return ProbeResult("clock_semantics", story, Outcome.NOT_REFUTED,
                       ev + " -- both clocks agree; the window reflects when things happened")


def probe_measurement_continuity(obs: Observation) -> ProbeResult:
    story = "the ruler changed mid-window, so the two numbers are not the same measurement"
    if obs.resolved_indices is None or obs.metric_field_types is None:
        return ProbeResult(
            "measurement_continuity", story, Outcome.COULD_NOT_RUN,
            "index resolution and field mappings were not retrieved",
            missing=f"the concrete indices the window resolved to and the mapping of `{obs.metric}` in each",
        )
    types = {obs.metric_field_types.get(i) for i in obs.resolved_indices}
    ev = f"window spans {len(obs.resolved_indices)} index(es); `{obs.metric}` mapped as {sorted(str(t) for t in types)}"
    if len(types) > 1 or None in types:
        return ProbeResult("measurement_continuity", story, Outcome.REFUTED,
                           ev + " -- the field is not the same measurement across the window")
    return ProbeResult("measurement_continuity", story, Outcome.NOT_REFUTED,
                       ev + " -- one consistent mapping; the ruler did not change")


#: Below this share of the primary reading, the second ruler does not see the
#: effect at all and the spike is a property of the estimator rather than the
#: system. Above it both rulers see something, and how much they disagree about
#: its size is carried forward rather than judged here.
ESTIMATOR_AGREEMENT = 0.50


def estimator_divergence(obs: Observation) -> Optional[float]:
    """How much of the effect's size depends on which estimator measured it.

    Returned as a fraction of the primary reading. `None` when there is no
    second estimator to compare against -- absent, not zero.

    Gate 3 reads this. An explanation accounting for 80% of an effect whose size
    is only known to within 30% has not fallen 20% short of anything; claiming
    it did would be precision the measurement cannot support.
    """
    if obs.focus_value_alt is None or obs.baseline_value_alt is None:
        return None
    primary = obs.focus_value - obs.baseline_value
    if not primary:
        return None
    alt = obs.focus_value_alt - obs.baseline_value_alt
    return abs(primary - alt) / abs(primary)


def probe_estimator_choice(obs: Observation) -> ProbeResult:
    """Does the effect survive being measured with a different ruler?

    A percentile aggregation is an estimator with error, and the error is not
    small at the sizes an incident window has. Measured on this project's own
    fixtures, the default estimator reads between +0.14% and +21.75% above the
    true value at n=200 -- and on the negative control that error decides *which
    bucket gets selected as the incident*, picking one whose true p99 is lower
    than another's.

    Two estimators of the same quantity, over the same documents, is the cheapest
    way to make that visible: one extra sub-aggregation in the same request, both
    built into every OpenSearch distribution.

    Disagreement about *size* does not refute anything -- it is recorded and
    handed to Gate 3, which cannot claim a residual finer than the ruler.
    Disagreement about *existence* is a refutation: if one ruler sees a 5x jump
    and the other sees nothing, the jump belongs to the ruler.
    """
    story = "the jump is a property of the estimator, not the system -- a different ruler does not see it"
    if obs.estimator_alt is None or obs.focus_value_alt is None or obs.baseline_value_alt is None:
        return ProbeResult(
            "estimator_choice", story, Outcome.COULD_NOT_RUN,
            f"only `{obs.estimator}` read this window, so the reading cannot be separated "
            "from the method that produced it",
            missing="the same window measured by a second percentile estimator (e.g. hdr alongside tdigest)",
        )

    primary = obs.focus_value - obs.baseline_value
    alt = obs.focus_value_alt - obs.baseline_value_alt
    if not primary:
        return ProbeResult("estimator_choice", story, Outcome.COULD_NOT_RUN,
                           "the primary reading shows no effect, so there is nothing to corroborate",
                           missing="a non-zero observed effect to compare across estimators")

    ratio = alt / primary
    ev = (f"`{obs.estimator}` sees {primary:+.2f}, `{obs.estimator_alt}` sees {alt:+.2f} "
          f"over the same documents ({ratio:.0%} as large)")
    if ratio < ESTIMATOR_AGREEMENT:
        return ProbeResult("estimator_choice", story, Outcome.REFUTED,
                           ev + f" -- below {ESTIMATOR_AGREEMENT:.0%}; the effect is substantially "
                                "an artifact of which estimator was asked")
    divergence = estimator_divergence(obs)
    return ProbeResult("estimator_choice", story, Outcome.NOT_REFUTED,
                       ev + f" -- both rulers see it; they disagree about its size by {divergence:.0%}, "
                            "which is carried forward rather than absorbed")


PROBES = (
    # Provenance first. These decide whether there is a claim to examine before
    # anything asks a question about the system.
    probe_unanchored_report,
    probe_observation_moment,
    probe_who_chose_the_window,
    # Then the measurement itself. The ruler comes before what it read: a
    # number whose size depends on which estimator produced it is not yet a
    # quantity the later probes can reason about.
    probe_estimator_choice,
    probe_sample_size,
    probe_population_shift,
    probe_clock_semantics,
    probe_measurement_continuity,
)


def decide(probes) -> Verdict:
    """Verdict precedence. See module docstring."""
    if any(p.outcome is Outcome.REFUTED for p in probes):
        return Verdict.ARTIFACT
    if all(p.outcome is Outcome.NOT_REFUTED for p in probes):
        return Verdict.SUBSTANTIATED
    return Verdict.UNDECIDABLE


def _scan_summary(obs: Observation) -> Optional[str]:
    if not obs.scan_window_start or not obs.scan_window_end:
        return None
    anchor = f" anchored on {obs.scan_anchor_source}" if obs.scan_anchor_source else ""
    at = f" at {obs.scan_anchor}" if obs.scan_anchor else ""
    return f"{obs.scan_window_start} -> {obs.scan_window_end},{anchor}{at}"


def audit(obs: Observation) -> AuditReport:
    results = [probe(obs) for probe in PROBES]
    summary = (f"{obs.metric} in focus window = {obs.focus_value} vs baseline {obs.baseline_value} "
               f"({obs.focus_value / obs.baseline_value:.1f}x)" if obs.baseline_value else obs.metric)
    return AuditReport(verdict=decide(results), observation_summary=summary, probes=results,
                       scan_summary=_scan_summary(obs))
