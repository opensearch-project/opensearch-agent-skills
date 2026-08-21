#!/usr/bin/env python3
"""How large a gap appears between subgroups when nothing is happening.

The question a concentration probe is really asking is not "is one endpoint's
median higher than the rest's" -- one of them always is. It is "is it higher
than it would be if nothing had happened here". Two different things make the
first question answer yes without the second one doing so, and the probe has to
survive both.

The first is chance. The previous version of this probe answered it with a
constant: a value's excess had to reach 50% of the window's own median rise.
That failed in both directions at once, and the evaluation measured both. It
missed a real concentration until it reached 68% of the rise, and -- because a
window whose median barely moved still has a median rise greater than zero -- it
divided a few milliseconds of subgroup wobble by a few milliseconds of drift,
got a large number, and confirmed a concentration on an index where nothing had
happened, in 3 runs of 5. One cause: there was no null. The absence cut both
ways, which is what the absence of a null does.

The second is a gap that was already there, and it is the subject of most of
what follows.

Each group is measured against its own normal
---------------------------------------------
A checkout path that writes to a database is slower than a health check in every
window, including the quiet ones. Asked whether its median exceeds the rest's,
the answer is yes, today and every day, and a probe that stops there reports
*this subgroup is slow* while appearing to report *this subgroup got slow*. The
evaluation measured the cost of not distinguishing them: on a fixture where one
endpoint runs permanently slower and then everything rises by the same amount --
so the gap is unchanged and explains none of the rise -- the earlier probe
confirmed a concentration in 5 runs of 5. Not occasionally. Every time.

So before anything is compared, every latency has its own group's median from
outside the focus window subtracted from it. What is left is how far that group
has moved from where it normally sits. A gap that was always there subtracts
out; a gap that is new does not. The statistic is then the *change* in the gap,
and that is the quantity a rise can be concentrated in.

The offset is a subtraction, not a ratio, because the observation being
explained is in milliseconds and the magnitude is reported in milliseconds. A
rise that is genuinely multiplicative -- everything doubles -- moves a slow
subgroup by more absolute milliseconds than a fast one, and this will read that
as concentrated. It is a different case from the one above, it is not handled,
and calling it handled is how a limit stops being visible.

A group whose normal cannot be measured is dropped and named. Subtracting an
offset estimated from a handful of documents would add more noise than the
offset removes, and the noise would land entirely on the confirming side.

The null keeps each group's own spread
--------------------------------------
The remaining question is how large a change appears when no group has moved
differently from any other. The window is redrawn several hundred times under
exactly that condition: each group is resampled **from its own latencies**,
shifted so every group sits at one common level. Each redraw produces a
largest-subgroup-change, and together they are the distribution of that
statistic when nothing is concentrated -- at these subgroup sizes, on this
data's own spread, group by group.

Shuffling the labels instead is simpler and was tried first. It pools every
group's spread into one, so a group that varies more than the others gets judged
against the average variation rather than its own -- and a slow subgroup varies
more in milliseconds for the same reason it is slow. Measured on the fixture
above, shuffled labels still confirmed a concentration in 1 run of 5 where
redrawing each group confirmed none. The cost is power: a real concentration at
47% of the window's median rise is found in 5 runs of 5 by the shuffled null and
2 by this one. That trade is deliberate and is the one this project has already
declared -- a miss costs a finding, a false confirmation costs the reason anyone
should believe the findings that remain.

Two details that are not incidental
-----------------------------------
**The null is a null of the maximum.** The probe reports the largest change among
several values, so the null has to be the distribution of the largest change too.
Comparing a maximum against the null of a single comparison would fire on the
most extreme of four groups at four times the intended rate -- the same mistake
as reading the highest bucket in a chart and treating it as if someone had
nominated it in advance, which is the failure Gate 1 exists to catch.

**An empirical p of zero is not reported.** With K redraws the smallest
defensible p is 1/(K+1), so the count of exceedances is incremented by one before
dividing. Printing 0.000 would claim a precision K draws cannot deliver, and the
number would then travel.

Standard library only. No retrieval here: this decides, and a decision that can
issue a query can widen its own evidence while making it.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from typing import Optional

#: Redraws. Enough that the 95th percentile is stable across runs and the
#: floor on the p-value (1/401) sits well below the level being tested.
DEFAULT_TRIALS = 400

#: A group needs this many documents on both sides, or its median is a statement
#: about sample size wearing the clothes of a statement about latency.
MIN_SUBPOP_N = 30

#: And this many outside the focus window before its normal is worth
#: subtracting. The floor is the same, but the binding condition is the second
#: one: the baseline must hold at least as many of a group's documents as the
#: focus window does, so the offset is no noisier than the median it corrects.
#: A noisy offset would move the change without measuring anything, and the
#: redraws do not model it -- it would land entirely on the confirming side.
MIN_BASELINE_N = 30

#: The false-positive rate this probe accepts. Declared, not fitted -- it is a
#: choice about how often to be wrong in the confirming direction, made before
#: seeing any data, and the evaluation measures whether the choice holds.
ALPHA = 0.05

#: A fixed seed so a captured verdict can be reproduced. The resampling is a
#: measurement instrument, and an instrument that reads differently every time
#: is not one.
SEED = 20260802


@dataclass(frozen=True)
class NullResult:
    """The observed change, and the distribution it has to stand out from."""

    group: Optional[str]
    excess: Optional[float]
    median_in: Optional[float]
    median_out: Optional[float]
    n_in: Optional[int]

    null_median: Optional[float]
    null_threshold: Optional[float]
    p_value: Optional[float]
    trials: int
    compared: int
    too_small: tuple = ()

    #: How many documents the test actually saw, and whether that was all of
    #: them. A null estimated on a truncated sample is a null for that sample.
    sample_n: int = 0
    sample_truncated: bool = False

    #: Whether `excess` is a change against each group's own normal or a bare
    #: gap. The two answer different questions and the same field would
    #: otherwise carry either without saying which -- the ruler has to be named
    #: alongside the number, which is the rule the eighth probe exists to keep.
    baseline_referenced: bool = False
    baseline_n: int = 0
    baseline_truncated: bool = False
    #: The gap this group already ran at outside the focus window. Reported so a
    #: reader can see what was subtracted rather than take it on faith.
    normal_gap: Optional[float] = None
    #: Groups excluded because their normal could not be measured.
    without_normal: tuple = ()

    @property
    def stands_out(self) -> bool:
        """Beyond what redrawing at one level produces at this rate."""
        return self.p_value is not None and self.p_value <= ALPHA

    @property
    def is_ordinary(self) -> bool:
        """At or below the middle of the null: exactly what noise does."""
        return (self.excess is not None and self.null_median is not None
                and self.excess <= self.null_median)

    def describe(self) -> str:
        if self.excess is None:
            base = "no value had enough documents on both sides to compare"
            return base + self._caveats()
        null = (f"Redrawing each group from its own latencies {self.trials} times, held at one "
                f"level, puts the typical largest {'change' if self.baseline_referenced else 'gap'} "
                f"at {self.null_median:.2f} and the {1 - ALPHA:.0%} point at "
                f"{self.null_threshold:.2f} (p={self.p_value:.3f}); {self.compared} value(s) compared")
        if self.baseline_referenced:
            normal = ("an unmeasured gap" if self.normal_gap is None
                      else f"a gap that already stood at {self.normal_gap:+.2f}")
            base = (f"`{self.group}` (n={self.n_in}) sits {self.median_in:+.2f} from its own level "
                    f"outside this window and the rest sit {self.median_out:+.2f} from theirs -- "
                    f"a change of {self.excess:+.2f} in {normal}, measured over "
                    f"{self.baseline_n} baseline documents. ")
        else:
            base = (f"`{self.group}` (n={self.n_in}) has median {self.median_in:.2f} against "
                    f"{self.median_out:.2f} for the rest -- {self.excess:+.2f}, with no baseline "
                    f"read, so this is the gap and not the change in it. ")
        return base + null + self._caveats()

    def _caveats(self) -> str:
        out = ""
        if self.too_small:
            out += f"; {len(self.too_small)} too small to compare ({'; '.join(self.too_small)})"
        if self.without_normal:
            out += (f"; {len(self.without_normal)} left out for want of a baseline to measure "
                    f"their normal against ({'; '.join(self.without_normal)})")
        if self.sample_truncated:
            out += (f"; the window holds more than {self.sample_n} documents, so this is a test "
                    "on the sample that was read, not on the window")
        if self.baseline_truncated:
            out += (f"; the baseline holds more than {self.baseline_n} documents, so each normal "
                    "is estimated from a random draw of it")
        return out


def _by_label(values, labels) -> dict:
    grouped = {}
    for value, label in zip(values, labels):
        grouped.setdefault(label, []).append(value)
    return grouped


def _excesses(values, labels, eligible):
    """Largest (median inside - median outside) over the eligible labels."""
    grouped = _by_label(values, labels)
    best = None
    for label in eligible:
        inside = grouped.get(label)
        if not inside:
            continue
        outside = [v for group, vs in grouped.items() if group != label for v in vs]
        if not outside:
            continue
        median_in = statistics.median(inside)
        median_out = statistics.median(outside)
        excess = median_in - median_out
        if best is None or excess > best[1]:
            best = (label, excess, median_in, median_out, len(inside))
    return best


def _normals(values, labels, focus_counts):
    """Each group's own level outside the focus window, where there is enough of it.

    Returns `(offsets, grouped)`. A group missing from `offsets` has no usable
    normal: either the baseline holds too little of it outright, or less of it
    than the focus window does, in which case subtracting the offset would add
    more uncertainty than it removes.
    """
    grouped = _by_label(values, labels)
    offsets = {}
    for group, vs in grouped.items():
        if len(vs) >= MIN_BASELINE_N and len(vs) >= focus_counts.get(group, 0):
            offsets[group] = statistics.median(vs)
    return offsets, grouped


def _null(values, labels, eligible, trials: int, seed: int) -> list:
    """The largest change, over and over, when every group sits at one level.

    Each group is resampled from its own latencies, so a group that varies more
    keeps varying more here. The alternative -- shuffling the labels over the
    pooled values -- gives every group the average spread, and then a group that
    is intrinsically noisier than the rest is judged against noise that is not
    its own. Sizes are preserved in both, so the null is estimated at the sizes
    actually present, which matters because a smaller subgroup produces a larger
    gap for free.
    """
    grouped = _by_label(values, labels)
    level = statistics.median(values)
    pools = {group: [v - statistics.median(vs) + level for v in vs]
             for group, vs in grouped.items()}

    rng = random.Random(seed)
    null = []
    for _ in range(trials):
        drawn_values, drawn_labels = [], []
        for group, pool in pools.items():
            drawn_values.extend(rng.choices(pool, k=len(pool)))
            drawn_labels.extend([group] * len(pool))
        drawn = _excesses(drawn_values, drawn_labels, eligible)
        if drawn is not None:
            null.append(drawn[1])
    return null


def assess(values, labels, baseline_values=None, baseline_labels=None,
           trials: int = DEFAULT_TRIALS, seed: int = SEED,
           sample_truncated: bool = False, baseline_truncated: bool = False) -> NullResult:
    """Has one group moved further from its own normal than the others have?

    `values` and `labels` are parallel: one latency and one group per document,
    both read from the *same* sample. Deriving the observed change from an
    aggregation and the null from a sample would compare two different
    estimators and call the difference a finding -- two rulers again, one gate
    further in. `baseline_values` and `baseline_labels` are the same pair read
    from outside the focus window, and are what makes this a question about a
    change rather than about a gap.

    Without them the weaker question is answered instead -- is this gap larger
    than one group could produce by accident -- and the result says so, because
    a caller that cannot tell which question was answered will read the answer
    to the wrong one.
    """
    focus_counts = {}
    for label in labels:
        focus_counts[label] = focus_counts.get(label, 0) + 1

    # `is not None`, not truthiness: a baseline that was supplied and came back
    # empty is an attempted read that found nothing, and must land in the
    # offered-but-not-referenced refusal below. Truthiness would silently
    # reclassify it as "no baseline supplied" and answer the weaker question --
    # the absent-versus-empty substitution this module exists to refuse.
    offered = baseline_values is not None
    offsets, baseline_grouped = ({}, {})
    if offered:
        offsets, baseline_grouped = _normals(baseline_values, baseline_labels, focus_counts)
    referenced = bool(offsets)
    baseline_n = len(baseline_values) if offered else 0

    without_normal = tuple(
        f"{group} (baseline n={len(baseline_grouped.get(group, ()))})"
        for group in sorted(focus_counts, key=str) if group not in offsets) if offered else ()

    if offered and not referenced:
        # A baseline was read and none of it was enough. Falling back to the
        # bare gap here would answer a different question in the same shape --
        # the substitution this probe exists to refuse, performed by the probe.
        return NullResult(None, None, None, None, None, None, None, None,
                          trials=trials, compared=0, too_small=(), sample_n=len(values),
                          sample_truncated=sample_truncated, baseline_referenced=False,
                          baseline_n=baseline_n, baseline_truncated=baseline_truncated,
                          without_normal=without_normal)

    if referenced:
        kept = [(v - offsets[g], g) for v, g in zip(values, labels) if g in offsets]
        values = [v for v, _ in kept]
        labels = [g for _, g in kept]

    n = len(values)
    counts = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1

    eligible = [g for g, c in counts.items() if c >= MIN_SUBPOP_N and n - c >= MIN_SUBPOP_N]
    too_small = tuple(f"{g} (n={c} vs {n - c})" for g, c in sorted(counts.items(), key=lambda kv: str(kv[0]))
                      if g not in eligible)

    blank = dict(trials=trials, compared=0, too_small=too_small, sample_n=n,
                 sample_truncated=sample_truncated, baseline_referenced=referenced,
                 baseline_n=baseline_n, baseline_truncated=baseline_truncated,
                 without_normal=without_normal)

    observed = _excesses(values, labels, eligible) if eligible else None
    if observed is None:
        return NullResult(None, None, None, None, None, None, None, None, **blank)
    group, excess, median_in, median_out, n_in = observed

    null = _null(values, labels, eligible, trials, seed)
    if not null:
        return NullResult(group, excess, median_in, median_out, n_in, None, None, None,
                          **{**blank, "compared": len(eligible)})

    null.sort()
    # +1 in both places: with K draws the smallest supportable p is 1/(K+1), and
    # a printed 0.000 would be a precision this many redraws cannot deliver.
    exceeded = sum(1 for value in null if value >= excess)
    p_value = (exceeded + 1) / (len(null) + 1)
    threshold = null[min(len(null) - 1, int(round((1 - ALPHA) * len(null))))]

    normal_gap = None
    if referenced:
        inside = baseline_grouped.get(group)
        outside = [v for g, vs in baseline_grouped.items() if g != group and g in offsets
                   for v in vs]
        if inside and outside:
            normal_gap = statistics.median(inside) - statistics.median(outside)

    return NullResult(
        group=group, excess=excess, median_in=median_in, median_out=median_out, n_in=n_in,
        null_median=statistics.median(null), null_threshold=threshold, p_value=p_value,
        trials=len(null), compared=len(eligible), too_small=too_small,
        sample_n=n, sample_truncated=sample_truncated,
        baseline_referenced=referenced, baseline_n=baseline_n,
        baseline_truncated=baseline_truncated, normal_gap=normal_gap,
        without_normal=without_normal,
    )
