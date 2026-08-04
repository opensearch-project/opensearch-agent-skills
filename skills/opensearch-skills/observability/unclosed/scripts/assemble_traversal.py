#!/usr/bin/env python3
"""Build a Gate 2 traversal from a real index, then run Gates 2 and 3 over it.

Gates 2 and 3 judge a tree. This is where the tree comes from. Keeping the two
apart is the same rule Gate 1 follows: a probe that could issue another query
while deciding could widen its own evidence, and judgment that needs a cluster
cannot be tested without one.

The hypothesis space is declared, not discovered
------------------------------------------------
`NOT_VISITED` only means something against a space that was written down in
advance. A tool that reports "I explored everything I thought of" has said
nothing -- the set it is complete with respect to is the set it happened to
think of. So HYPOTHESES below is a fixed catalog, every entry appears in the
tree whether or not it was probed, and entries this index cannot answer are
recorded as unwalked with the data that would be needed named.

Magnitude by counterfactual
---------------------------
"How much does this explain" is answered by removing the subpopulation and
measuring again: `focus_p99 - focus_p99_without_v`. If dropping one endpoint
collapses the window's p99, that endpoint carries the effect. If dropping it
moves p99 by 8ms out of 400, it is a correlate that happens to be there -- and
Gate 3 will say so rather than accepting it.

A restatement may not account for anything
------------------------------------------
"The whole distribution shifted up" is true, useful for deciding where to look
next, and is *the observation said a second way*. Letting it account for the
effect would close the chain on "it got slower because it got slower", which is
the most confident-sounding empty answer available. It is structurally barred
from carrying magnitude.

Concentration is decided against a null, not against a constant
--------------------------------------------------------------
An earlier version of this probe required a value's median excess to reach 50%
of the window's own median rise. The evaluation measured that rule failing in
both directions at once: it missed a real concentration until it reached 68% of
the rise, and it confirmed one that did not exist on 3 negative-control runs in
5 -- because a window whose median moved only by noise still has a median rise
above zero, so dividing a few milliseconds of subgroup wobble by it produced a
large share and a CONFIRMED verdict.

One cause for both: there was no null. `concentration_null.py` builds one by
redrawing the window several hundred times with every group held at one level,
and asking where the observed value falls among the results. See that module for
why the null has to be a null of the maximum, and why an empirical p of zero is
never printed.

And the thing being asked about is a *change*, not a gap. A subgroup that is
permanently slower carries a large gap in every window, including the quiet ones,
so each latency has its own group's level from outside the focus window
subtracted before any comparison happens. Without that step the probe reports
*this subgroup is slow* while appearing to report *this subgroup got slow*: on
the corpus fixture built to catch exactly that, the earlier version confirmed a
concentration in 5 runs of 5 where nothing was concentrated at all.

The rate of confirming something that is not there is now a declared 5% rather
than a consequence of an arbitrary constant, and examples/miss-rate.txt reports
what that choice actually costs -- including the power given up to buy it.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import NamedTuple, Optional

sys.path.insert(0, __file__.rsplit("assemble_traversal.py", 1)[0])
from audit_window import _get as _request  # noqa: E402
from audit_window import add_connection_args, build_observation, endpoint_from_args  # noqa: E402
from closure_audit import RESIDUAL_TOLERANCE, audit_closure, closes  # noqa: E402
from concentration_null import MIN_SUBPOP_N as NULL_MIN_N  # noqa: E402
from concentration_null import assess  # noqa: E402
from premise_audit import Verdict, audit, estimator_divergence  # noqa: E402
from traversal import Gate1Carryover, Node, NodeState, Traversal  # noqa: E402

DEFAULT_ENDPOINT = "http://127.0.0.1:9250"

#: A shift that reaches the median is not a tail-only event. Expressed as a
#: fraction of the p99 movement so it scales with the incident.
MEDIAN_SHIFT_SHARE = 0.10

#: Documents read from the focus window for the null. Larger than any window
#: this project's fixtures produce, so the null is normally estimated on the
#: whole window. When a real window exceeds it the test is still valid --
#: observed statistic and null come from the same sample -- but it is a test on
#: that sample, and the report says so rather than implying otherwise.
SAMPLE_CAP = 5000

#: And from the baseline, to establish what each group's level normally is. The
#: baseline is every bucket except the focus one, so exceeding this cap is the
#: ordinary case rather than the exception -- which is why the draw below is
#: random rather than whatever the index hands back first.
BASELINE_SAMPLE_CAP = 5000

#: Fixed, so the draw is a measurement and not a different one each run.
SAMPLE_SEED = 20260802


def _post(endpoint, path, body):
    """Delegate to the one transport, which knows about credentials and TLS.

    This used to be a second copy of the same twelve lines. Two transports means
    a cluster that needs authentication has to be taught twice, and the second
    one is the one nobody remembers.
    """
    return _request(endpoint, path, body)


def _window(time_field, start, end):
    return {"range": {time_field: {"gte": start, "lt": end}}}


def _percentiles(endpoint, index, query, metric, percents):
    body = {"size": 0, "query": query,
            "aggs": {"p": {"percentiles": {"field": metric, "percents": percents}}}}
    values = _post(endpoint, f"/{index}/_search", body)["aggregations"]["p"]["values"]
    return {k: v for k, v in values.items()}


def _terms(endpoint, index, query, field, size=20):
    body = {"size": 0, "query": query, "aggs": {"t": {"terms": {"field": field, "size": size}}}}
    return _post(endpoint, f"/{index}/_search", body)["aggregations"]["t"]["buckets"]


def _sample(endpoint, index, query, metric, dimensions, cap=SAMPLE_CAP, seed=SAMPLE_SEED):
    """Raw values from one window, once, for every dimension at the same time.

    The null needs the documents themselves -- an aggregation returns summaries,
    and a summary cannot be resampled. Fetching once for all dimensions keeps
    this to a single extra request per window rather than one per hypothesis.

    Scored at random so that a window larger than the cap is read as a draw from
    the whole of it. A plain read returns whichever documents the index hands
    back first, which on a time-ordered index is its oldest part -- and a
    "normal" measured from the oldest stretch of a baseline is a normal for a
    different span of time than the one being explained. The seed is fixed, so
    two runs over an unchanged index read the same documents.
    """
    body = {"size": cap, "_source": [metric] + list(dimensions),
            "query": {"function_score": {"query": query,
                                         "random_score": {"seed": seed, "field": "_seq_no"}}}}
    res = _post(endpoint, f"/{index}/_search", body)
    total = res["hits"]["total"]
    total = total["value"] if isinstance(total, dict) else total
    rows = []
    for hit in res["hits"]["hits"]:
        src = hit["_source"]
        if metric in src:
            rows.append(src)
    return rows, bool(total and total > len(rows))


# --------------------------------------------------------------------------
# The declared hypothesis space
# --------------------------------------------------------------------------

#: Subpopulation hypotheses: the rise is confined to one value of a dimension.
#: Each is answerable from a latency log alone, which is why they are here.
CONCENTRATION_DIMENSIONS = (
    ("endpoint", "the rise is confined to one endpoint"),
    ("region", "the rise is confined to one region"),
    ("service", "the rise is confined to one service"),
    ("status", "the rise is confined to failing requests"),
)

#: Hypotheses a request log cannot answer *by itself*, named anyway. Leaving them
#: out would make the tree look complete; naming them is the difference between
#: "nothing else to check" and "the rest is not in this data".
#:
#: They are not, however, unanswerable. Most clusters carrying request logs also
#: carry deploy events, dependency latencies and node metrics -- in other
#: indices, which is a different statement from "not available". Until the caller
#: points at one, each stays NOT_VISITED and the chain stays open; pointed at
#: one, the branch is walked and disposed of like any other.
#:
#: The earlier version appended all three as NOT_VISITED unconditionally, and
#: that had two costs. It made closure unreachable by construction, so the
#: closure verdict was a constant rather than a judgement -- a refusal that can
#: never be lifted is not a finding. And on a cluster that *did* carry deploy
#: events the printed reason, "needs deploy/change events", was false: the events
#: existed and the tool had not looked.
#:
#: `kind` decides how the branch is walked. `events` asks whether a thing
#: happened in the window; `series` asks whether a number did something in the
#: window it did not do in any other bucket of the scan.
EXTERNAL_HYPOTHESES = (
    ("change", "events", "a deploy or config change landed in this window",
     "deploy/change events -- this index carries request logs only"),
    ("dependency", "series", "an upstream dependency got slower",
     "downstream call spans or a dependency's own latency series"),
    ("host", "series", "the host or container lost resources",
     "node-level CPU/memory/disk metrics, which are not request logs"),
)

#: Baseline buckets a series needs before its ordinary range means anything.
#: Below this the range is an artefact of how few readings there were, and the
#: branch declines rather than comparing against a normal it cannot establish --
#: the same rule the concentration probe applies to a subgroup with no history.
MIN_BASELINE_BUCKETS = 5


def _count(endpoint, index, query):
    body = {"size": 0, "track_total_hits": True, "query": query}
    total = _post(endpoint, f"/{index}/_search", body)["hits"]["total"]
    return total["value"] if isinstance(total, dict) else total


def _bucket_medians(endpoint, index, time_field, metric, gte, lt, bucket_minutes):
    body = {
        "size": 0,
        "query": _window(time_field, gte, lt),
        "aggs": {"per_bucket": {
            "date_histogram": {"field": time_field, "fixed_interval": f"{bucket_minutes}m",
                               "min_doc_count": 1},
            "aggs": {"p": {"percentiles": {"field": metric, "percents": [50]}}},
        }},
    }
    res = _post(endpoint, f"/{index}/_search", body)
    out = []
    for b in res["aggregations"]["per_bucket"]["buckets"]:
        # Sub-aggregation results are siblings of the bucket metadata, never
        # nested under an "aggs" key; the fallback that guessed otherwise was
        # dead code, and dead code in a parser reads as a supported shape.
        v = b["p"]["values"]["50.0"]
        if v is not None:
            out.append((b["key_as_string"], v))
    return out


def _event_node(endpoint, statement, needs, source, time_field, focus_start, focus_end,
                scan_start, scan_end):
    """Did a thing of this kind happen inside the window?

    Absence is only a ruling when presence was detectable. An index that holds
    no events anywhere in the scanned span cannot distinguish "no deploy
    happened" from "deploys are not recorded here", and reporting the first
    would be reading an empty source as evidence. That case stays unwalked and
    says which of the two it cannot tell apart.
    """
    in_window = _count(endpoint, source, _window(time_field, focus_start, focus_end))
    in_scan = _count(endpoint, source, _window(time_field, scan_start, scan_end))
    probe = f"count of `{source}` documents in the window, against the whole scanned span"
    if in_window:
        return Node(statement, NodeState.CONFIRMED, probe=probe,
                    evidence=(f"{in_window} event(s) in {focus_start} -> {focus_end}, "
                              f"{in_scan} across the scanned span"))
    if not in_scan:
        return Node(statement, NodeState.NOT_VISITED,
                    not_visited_reason=(f"`{source}` holds no events anywhere in the scanned span, so "
                                        f"an empty window cannot separate 'none happened' from 'none "
                                        f"recorded' -- {needs}"))
    return Node(statement, NodeState.RULED_OUT, probe=probe,
                evidence=(f"no event in {focus_start} -> {focus_end}; {in_scan} elsewhere in the "
                          f"scanned span, so the source was recording"))


def _series_node(endpoint, statement, needs, source, field, time_field, focus_start, focus_end,
                 scan_start, scan_end, bucket_minutes):
    """Did this number do something in the window it does not do otherwise?

    Threshold-free on purpose. A fitted constant here would be a constant fitted
    to the data it grades, which this project has already had to remove once. The
    question asked instead is non-parametric and uses the series' own behaviour
    as the ruler: bucket the scanned span the same way the latency was bucketed,
    and ask whether the focus bucket's median sits outside the range every other
    bucket occupied. Inside that range is not evidence of nothing happening -- it
    is evidence this series did nothing unusual, which is what ruling the branch
    out means and all it means.
    """
    buckets = _bucket_medians(endpoint, source, time_field, field, scan_start, scan_end, bucket_minutes)
    focus = [v for start, v in buckets if start == focus_start]
    others = [v for start, v in buckets if start != focus_start]
    probe = (f"`{field}` median per {bucket_minutes}m bucket in `{source}`, focus against the "
             f"range of every other bucket in the scanned span")
    if not focus:
        return Node(statement, NodeState.NOT_VISITED,
                    not_visited_reason=(f"`{source}` carries no `{field}` reading in {focus_start}, so "
                                        f"the window it would be judged on is empty -- {needs}"))
    if len(others) < MIN_BASELINE_BUCKETS:
        return Node(statement, NodeState.NOT_VISITED,
                    not_visited_reason=(f"`{source}` has {len(others)} other bucket(s) of `{field}` in "
                                        f"the scanned span; below {MIN_BASELINE_BUCKETS} there is no "
                                        f"ordinary range to compare against -- {needs}"))
    value, lo, hi = focus[0], min(others), max(others)
    ev = (f"`{field}` median {value:.2f} in the window; {lo:.2f}..{hi:.2f} across the other "
          f"{len(others)} bucket(s)")
    if value > hi or value < lo:
        return Node(statement, NodeState.CONFIRMED, probe=probe,
                    evidence=ev + " -- outside anything it did in the scanned span")
    return Node(statement, NodeState.RULED_OUT, probe=probe,
                evidence=ev + " -- inside the range it occupies in ordinary buckets")


def _external_node(endpoint, key, kind, statement, needs, external, time_field,
                   focus_start, focus_end, scan_start, scan_end, bucket_minutes):
    source = (external or {}).get(key)
    if not source:
        return Node(statement, NodeState.NOT_VISITED, not_visited_reason=f"needs {needs}")
    if kind == "events":
        return _event_node(endpoint, statement, needs, source, time_field,
                           focus_start, focus_end, scan_start, scan_end)
    index, field = source
    return _series_node(endpoint, statement, needs, index, field, time_field,
                        focus_start, focus_end, scan_start, scan_end, bucket_minutes)


def _immaterial(excess, observed_effect, tolerance):
    """Could a branch this size be the account of an effect that size?

    Asked because the null answers a different question. A subgroup's excess is
    judged against what redrawing at one level produces -- whether it is *larger
    than chance* -- and never against the rise it would have to explain. Those
    come apart badly: on this project's own runs a 13ms subgroup gap sat in the
    upper half of its null while the effect being explained was 1900ms. Judged
    against chance it is elevated. Judged against the thing it would have to
    account for it is 0.7% of it, and no confidence about a 0.7% wobble makes it
    a rival account.

    Blocking a chain on that is what made closure unreachable: three innocent
    dimensions each had to land in the lower half of their own null by luck, and
    0 of 11 runs closed. See examples/closure-ceiling.txt.

    The bar is Gate 3's, not a new one. `RESIDUAL_TOLERANCE` is already the share
    of an effect this project declines to claim precision below; a branch under
    it cannot be sized against the effect either way, so it cannot be the effect.

    Returns None when the question cannot be asked -- an unmeasured branch is
    never immaterial, because "too small to matter" is a measurement and a
    branch nobody could measure has not produced one.
    """
    if excess is None or not observed_effect:
        return None
    return excess < tolerance * abs(observed_effect)


def _concentration_node(endpoint, index, dim, statement, metric, focus_q, focus_p99,
                        sample, truncated, baseline_sample=None, baseline_truncated=False,
                        observed_effect=None, tolerance=RESIDUAL_TOLERANCE):
    """Has one value of this dimension moved further than the rest of the window?

    Asked on the **median**, against each value's **own normal**, and against a
    **null**. All three choices are the probe.

    The median, because the two obvious alternatives report sample size while
    appearing to report concentration:

      remove the value and re-measure the window. Taking 198 of 200 documents
      out moves p99 whatever those documents were.

      compare the value's own p99 to the rest's. A p99 estimated on n=49 is
      noisy and biased high -- measurably so: on this project's own fixtures
      the aggregation reads between +0.14% and +21.75% above the true value at
      n=200, and smaller subgroups are worse.

    Both are Gate 1's population_shift confound rebuilt one gate up.

    Its own normal, because some values are permanently slower than others and
    always have been. Subtracting each group's level from outside the window
    turns "this endpoint is slow" -- true every day, and an explanation of
    nothing -- into "this endpoint got slower than the rest did", which is the
    only version a rise can be concentrated in.

    The null, because a median change between subgroups is never zero and a
    constant cannot say when one is large. Redrawing the window with every group
    held at one level produces the distribution of that change when nothing is
    concentrated, at these sizes and on each group's own spread -- see
    `concentration_null.py`. A constant expressed as a share of anything is
    blind to scale, and the evaluation caught the earlier one failing in both
    directions because of it.

    Once a concentration stands out from the null, removal is a fair way to
    *size* it in the metric the observation was made in.

    Returns `(confirmed_value, node)`. The value is returned rather than parsed
    back out of the node's text later: a reader that has to recover structure
    from a sentence is one rewording away from silently finding nothing.
    """
    probe = (f"measured each `{dim}` value against its own level outside the window, compared the "
             f"movement with the rest's, and judged it against the change that redrawing at one "
             f"level produces at the same subgroup sizes")

    rows = [r for r in sample if dim in r]
    labels = {r[dim] for r in rows}
    if len(labels) < 2:
        only = next(iter(labels)) if labels else "nothing"
        return None, Node(
            statement, NodeState.INCONCLUSIVE, probe=f"grouped the focus window by `{dim}`",
            evidence=(f"only one value present ({only}); a dimension with nothing to compare "
                      "cannot separate a concentrated rise from a uniform one"),
        )

    # None means no baseline was offered at all; a list -- however empty -- is
    # a read that happened, and the null keeps that distinction: an empty read
    # is refused with its groups named, never silently downgraded to the
    # weaker no-baseline question.
    if baseline_sample is None:
        baseline_vals, baseline_dims = None, None
    else:
        baseline_rows = [r for r in baseline_sample if dim in r]
        baseline_vals = [float(r[metric]) for r in baseline_rows]
        baseline_dims = [r[dim] for r in baseline_rows]
    result = assess([float(r[metric]) for r in rows], [r[dim] for r in rows],
                    baseline_vals, baseline_dims,
                    sample_truncated=truncated, baseline_truncated=baseline_truncated)
    if result.excess is None:
        missing = result.too_small + result.without_normal
        return None, Node(
            statement, NodeState.INCONCLUSIVE, probe=probe,
            evidence=(f"no value could be compared ({'; '.join(missing)}); one needs "
                      f"{NULL_MIN_N} documents on both sides of the comparison, and enough of "
                      "its own outside this window to say what it normally runs at -- short of "
                      "either, the answer reports sample size and not concentration"),
        )

    ev = result.describe()
    value = result.group

    if result.stands_out:
        without = {"bool": {"must": [focus_q], "must_not": [{"term": {dim: value}}]}}
        p = _percentiles(endpoint, index, without, metric, [99]).get("99.0")
        drop = focus_p99 - p if p is not None else None
        if drop is None:
            return value, Node(f"{statement} ({dim}={value})", NodeState.CONFIRMED, probe=probe,
                               evidence=ev + " -- stands out from the null, but removing it left "
                                             "nothing to measure against")
        return value, Node(f"{statement} ({dim}={value})", NodeState.CONFIRMED, probe=probe,
                           evidence=ev + f"; removing it takes the window down by {drop:+.2f}",
                           magnitude_accounted=round(drop, 2))
    if result.is_ordinary:
        return None, Node(statement, NodeState.RULED_OUT, probe=probe,
                          evidence=ev + " -- at or below what a window with nothing concentrated "
                                        "in it produces; the rise is spread")
    elevated = " -- elevated, but not beyond what this window produces by chance"
    if _immaterial(result.excess, observed_effect, tolerance):
        share = result.excess / abs(observed_effect)
        return None, Node(
            statement, NodeState.IMMATERIAL, probe=probe,
            evidence=(ev + elevated + f", and at {result.excess:.2f} it is {share:.1%} of the "
                      f"{observed_effect:+.2f} being explained -- under the {tolerance:.0%} this "
                      "project will size an explanation to, so it is not a rival account of it"),
        )
    return None, Node(statement, NodeState.INCONCLUSIVE, probe=probe,
                      evidence=ev + elevated + "; not enough to say the effect lives here, and "
                                               "large enough that it could")


def _shape_node(endpoint, index, metric, focus_q, baseline_q, observed_effect):
    """Did the median move too, or only the tail?

    Deliberately carries no magnitude. It restates the observation in more
    detail rather than explaining it, and an explanation that is the observation
    said twice would close the chain on nothing.
    """
    f = _percentiles(endpoint, index, focus_q, metric, [50, 99])
    b = _percentiles(endpoint, index, baseline_q, metric, [50, 99])
    if f.get("50.0") is None or b.get("50.0") is None:
        return (Node("the whole distribution moved, not just the tail", NodeState.INCONCLUSIVE,
                     probe="compared p50 and p99 across focus and baseline", explanatory=False,
                     evidence="a percentile came back empty; the comparison could not be made"), None)

    median_shift = f["50.0"] - b["50.0"]
    share = median_shift / observed_effect if observed_effect else 0.0
    ev = (f"p50 {b['50.0']:.2f} -> {f['50.0']:.2f} ({median_shift:+.2f}), "
          f"p99 moved {observed_effect:+.2f}; the median carries {share:.0%} of it")

    if share >= MEDIAN_SHIFT_SHARE:
        return (Node("the whole distribution moved, not just the tail", NodeState.CONFIRMED,
                     probe="compared p50 and p99 across focus and baseline", explanatory=False,
                     evidence=ev + " -- a uniform shift. This says where to look next, "
                                   "and it is the observation restated, so it explains nothing on its own"),
                median_shift)
    return (Node("the whole distribution moved, not just the tail", NodeState.RULED_OUT,
                 probe="compared p50 and p99 across focus and baseline", explanatory=False,
                 evidence=ev + " -- the median held; this is a tail-only event"), median_shift)


class Assembled(NamedTuple):
    """Everything one run produced, named rather than positional.

    `observation` and `concentrations` are here so that a caller checking this
    tool's answers -- the evaluation harness, most of all -- reads structure
    instead of re-parsing the report's prose. A grader that recovers its facts
    from rendered sentences fails silently the first time a sentence is reworded,
    and reports a perfect score while measuring nothing.
    """

    premise: object
    traversal: Traversal
    observed_effect: float
    uncertainty: Optional[float]
    observation: object
    #: (dimension, value) pairs the traversal ended up CONFIRMING -- after the
    #: single-carrier rule below, not before it.
    concentrations: tuple


def assemble(endpoint, index, metric, time_field, dimension, bucket_minutes, lookback_hours,
             focus_window=None, reported_at=None, as_of=None, external=None) -> Assembled:
    obs, focus = build_observation(endpoint, index, metric, time_field, dimension,
                                   bucket_minutes, lookback_hours, focus_window, reported_at, as_of)
    premise = audit(obs)

    observed_effect = obs.focus_value - obs.baseline_value

    # The same floor Gate 3 sizes explanations against, widened the same way when
    # the two estimators disagree about how big the effect even is. Deciding
    # materiality against a tighter bar than the one used to accept an
    # explanation would let a branch be too small to be an answer and large
    # enough to block one.
    uncertainty = estimator_divergence(obs)
    tolerance = max(RESIDUAL_TOLERANCE, uncertainty or 0.0)

    # The refusal is structural, not cosmetic. Below an artifact there is no
    # hypothesis space worth walking -- and a traversal that gets built and then
    # merely goes unprinted is one refactor away from being printed. `traversal`
    # is None here because there is nothing to traverse, which is a different
    # statement from an empty tree.
    if premise.verdict is Verdict.ARTIFACT:
        return Assembled(premise, None, observed_effect, estimator_divergence(obs), obs, ())

    focus_q = _window(time_field, obs.window_start, obs.window_end)
    baseline_q = {"bool": {"must_not": [focus_q]}}

    shape, _ = _shape_node(endpoint, index, metric, focus_q, baseline_q, observed_effect)

    # One fetch of each raw window, shared by every dimension. The null resamples
    # documents, and a summary cannot be resampled. The baseline is read the same
    # way and through the same query the shape node used, so "normal" means one
    # thing here rather than two things that happen to share a name.
    dims = [dim for dim, _ in CONCENTRATION_DIMENSIONS]
    sample, truncated = _sample(endpoint, index, focus_q, metric, dims)
    baseline_sample, baseline_truncated = _sample(endpoint, index, baseline_q, metric, dims,
                                                  cap=BASELINE_SAMPLE_CAP)

    children, candidates = [], []
    for dim, statement in CONCENTRATION_DIMENSIONS:
        value, node = _concentration_node(endpoint, index, dim, statement, metric,
                                          focus_q, obs.focus_value, sample, truncated,
                                          baseline_sample, baseline_truncated,
                                          observed_effect, tolerance)
        children.append(node)
        candidates.append((dim, value))

    # At most one dimension may carry magnitude. Two dimensions that each
    # isolate the window may be isolating the *same documents* seen from two
    # angles, and summing them would explain the effect twice. The strongest
    # keeps its number; the others are recorded as still standing, because
    # "might be the same thing" is not grounds for ruling either out.
    carriers = [n for n in children if n.magnitude_accounted is not None]
    if len(carriers) > 1:
        carriers.sort(key=lambda n: -n.magnitude_accounted)
        note = (" -- another dimension isolates the window at least as strongly, and these may be "
                "the same documents seen from two angles; not independently established")
        for weaker in carriers[1:]:
            # Withdrawing the number is the whole of the rule: two dimensions
            # that may be the same documents must not be summed. Whether the
            # branch still stands as a rival is a separate question with a
            # separate answer -- one this used to skip by parking every demoted
            # branch in the open set, where "we declined to credit it" became
            # indistinguishable from "it is still standing". A demotion that can
            # never be lifted keeps a chain open on a finding nobody disputes.
            state = NodeState.INCONCLUSIVE
            extra = ""
            if _immaterial(weaker.magnitude_accounted, observed_effect, tolerance):
                state = NodeState.IMMATERIAL
                share = weaker.magnitude_accounted / abs(observed_effect)
                extra = (f". At {weaker.magnitude_accounted:+.2f} it is {share:.1%} of the "
                         f"{observed_effect:+.2f} being explained, under the {tolerance:.0%} floor, "
                         "so it is not a rival account of it either way")
            children[children.index(weaker)] = Node(
                weaker.hypothesis, state, probe=weaker.probe,
                evidence=weaker.evidence + note + extra,
            )

    # Read after the single-carrier rule, never before it: a dimension that was
    # downgraded above is not a finding, and a scorer told otherwise would credit
    # the tool with a confirmation it withdrew.
    concentrations = tuple(
        (dim, value)
        for (dim, value), node in zip(candidates, children)
        if value is not None and node.state is NodeState.CONFIRMED
    )

    children.append(shape)
    for key, kind, statement, needs in EXTERNAL_HYPOTHESES:
        children.append(_external_node(
            endpoint, key, kind, statement, needs, external, time_field,
            obs.window_start, obs.window_end, obs.scan_window_start, obs.scan_window_end,
            bucket_minutes))

    root = Node(
        f"{metric} rose {observed_effect:+.2f} in {obs.window_start}",
        NodeState.CONFIRMED,
        probe=f"p99 per {bucket_minutes}m bucket over the last {lookback_hours}h",
        evidence=f"focus {obs.focus_value:.2f} vs baseline {obs.baseline_value:.2f} (n={obs.focus_count})",
        children=tuple(children),
    )

    traversal = Traversal(
        observation=f"{metric} p99 {obs.baseline_value:.2f} -> {obs.focus_value:.2f} in {obs.window_start}",
        root=root,
        gate1=Gate1Carryover(premise.verdict.value, tuple(premise.missing_inputs)),
    )
    return Assembled(premise, traversal, observed_effect, estimator_divergence(obs),
                     obs, concentrations)


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble a traversal from an index and run all three gates.")
    ap.add_argument("--index", required=True)
    ap.add_argument("--metric", default="latency_ms")
    ap.add_argument("--time-field", default="@timestamp")
    ap.add_argument("--dimension", default="endpoint")
    ap.add_argument("--bucket-minutes", type=int, default=10)
    ap.add_argument("--lookback-hours", type=int, default=6)
    ap.add_argument("--focus-window", default=None)
    ap.add_argument("--reported-at", default=None)
    ap.add_argument("--as-of", default=None,
                    help="ISO moment the lookback ends. Without it the window is anchored on the "
                         "newest document in the index, never on the wall clock.")
    ap.add_argument("--change-events", default=None, metavar="INDEX",
                    help="Index of deploy/config change events. Without it that branch stays "
                         "unwalked and the chain cannot close.")
    ap.add_argument("--dependency", default=None, metavar="INDEX:FIELD",
                    help="A dependency's own latency series, e.g. dep-latency:latency_ms")
    ap.add_argument("--host-metrics", default=None, metavar="INDEX:FIELD",
                    help="A node-level resource series, e.g. node-metrics:cpu_pct")
    add_connection_args(ap)
    args = ap.parse_args()
    endpoint = endpoint_from_args(args)

    def _pair(value, flag):
        if not value:
            return None
        if ":" not in value:
            raise SystemExit(f"{flag} takes INDEX:FIELD, got {value!r}")
        return tuple(value.split(":", 1))

    external = {"change": args.change_events,
                "dependency": _pair(args.dependency, "--dependency"),
                "host": _pair(args.host_metrics, "--host-metrics")}

    run = assemble(endpoint, args.index, args.metric, args.time_field, args.dimension,
                   args.bucket_minutes, args.lookback_hours, args.focus_window, args.reported_at,
                   args.as_of, external)
    premise, traversal = run.premise, run.traversal
    observed_effect, uncertainty = run.observed_effect, run.uncertainty

    print("=" * 78)
    print(f"TRANSPORT: {endpoint.describe()}")
    print(premise.to_text())
    print()
    if premise.verdict is Verdict.ARTIFACT:
        print("=" * 78)
        print("Gate 2 not run: the premise did not survive Gate 1.")
        print("Walking a hypothesis space below an artifact would produce a tidy tree")
        print("explaining something that did not happen.")
        return 0

    print("=" * 78)
    print(traversal.to_text())
    print()
    print("=" * 78)
    print(audit_closure(traversal, observed_effect, uncertainty).to_text())
    print()
    closed, reasons = closes(traversal, observed_effect, uncertainty)
    print("=" * 78)
    print("ALL FOUR CONDITIONS: %s" % ("closed" if closed else "NOT CLOSED"))
    for r in reasons:
        print(f"  - {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
