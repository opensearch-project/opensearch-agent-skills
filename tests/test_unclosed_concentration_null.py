"""The null the concentration probe is judged against.

This module replaced a constant that the evaluation caught failing in both
directions, so the properties that make it a null rather than a differently
shaped constant are pinned here -- particularly the ones that are easy to get
wrong and invisible when wrong: that it is a null of the *maximum*, that it
scales with the data rather than with a chosen unit, that it keeps each group's
own spread instead of an average of everyone's, and that what it judges is the
*change* in a gap and not the gap.
"""

import random

import pytest

import concentration_null as cn


def uniform(n, median, sigma=0.6, seed=1):
    rng = random.Random(seed)
    return [rng.lognormvariate(__import__("math").log(median), sigma) for _ in range(n)]


def labelled(groups):
    """groups: {label: [values]} -> (values, labels)"""
    values, labels = [], []
    for label, vals in groups.items():
        values.extend(vals)
        labels.extend([label] * len(vals))
    return values, labels


def window(spec, n, seed):
    """One window: {label: median} -> (values, labels), n documents per label."""
    return labelled({label: uniform(n, median, seed=seed + i)
                     for i, (label, median) in enumerate(sorted(spec.items()))})


def test_a_planted_concentration_stands_out():
    values, labels = labelled({
        "/a": uniform(50, 600, seed=1),
        "/b": uniform(50, 80, seed=2),
        "/c": uniform(50, 80, seed=3),
        "/d": uniform(50, 80, seed=4),
    })
    result = cn.assess(values, labels, trials=200)
    assert result.group == "/a"
    assert result.stands_out
    assert result.p_value <= cn.ALPHA


def test_labels_that_mean_nothing_do_not_stand_out():
    # One distribution, four arbitrary labels. Whatever gap appears is the gap
    # the shuffling produces, so the observed draw cannot be extreme among them.
    values = uniform(200, 80, seed=9)
    labels = [f"/{'abcd'[i % 4]}" for i in range(200)]
    result = cn.assess(values, labels, trials=200)
    assert not result.stands_out
    assert result.p_value > cn.ALPHA


def test_the_null_scales_with_the_data_not_with_a_fixed_unit():
    # The same shape of data at ten times the scale produces a null ten times
    # wider. A threshold expressed in milliseconds, or as a share of anything
    # chosen elsewhere, is blind to exactly this -- which is how the constant
    # this module replaced managed to be too strict and too lax at once.
    small = cn.assess(*labelled({f"/{c}": uniform(50, 80, seed=i)
                                 for i, c in enumerate("abcd")}), trials=200)
    large = cn.assess(*labelled({f"/{c}": uniform(50, 800, seed=i)
                                 for i, c in enumerate("abcd")}), trials=200)
    assert large.null_threshold > small.null_threshold * 5


def test_the_statistic_is_the_largest_gap_not_the_first_one_found():
    # The probe reports the largest excess among several values, so the null has
    # to be the distribution of the largest too. A null built from one fixed
    # comparison is narrower, and comparing a maximum against it fires far more
    # often than the declared rate -- the same mistake as reading the highest
    # bucket in a chart as if someone had nominated it in advance.
    values, labels = labelled({
        "/a": uniform(50, 100, seed=1),
        "/b": uniform(50, 700, seed=2),   # the largest, and not the first
        "/c": uniform(50, 90, seed=3),
    })
    group, excess, *_ = cn._excesses(values, labels, ["/a", "/b", "/c"])
    assert group == "/b"


def test_more_groups_to_choose_from_widens_the_null():
    # Taking a maximum over eight comparisons finds a larger gap by chance than
    # taking it over two, and the null has to grow to match or the declared rate
    # is not the real one. Subgroup size is held at 40 in both.
    eight = cn.assess(*labelled({f"/{c}": uniform(40, 80, seed=i)
                                 for i, c in enumerate("abcdefgh")}), trials=200)
    two = cn.assess(*labelled({f"/{c}": uniform(40, 80, seed=i)
                               for i, c in enumerate("ab")}), trials=200)
    assert eight.compared == 8 and two.compared == 2
    assert eight.null_threshold > two.null_threshold


def test_a_subgroup_too_small_on_either_side_is_declined_and_named():
    values, labels = labelled({"/a": uniform(5, 900, seed=1), "/b": uniform(195, 80, seed=2)})
    result = cn.assess(values, labels, trials=50)
    assert result.excess is None
    assert any("/a (n=5" in entry for entry in result.too_small)


def test_the_p_value_never_reads_zero():
    # With K shuffles the smallest supportable p is 1/(K+1). Printing 0.000
    # would claim a precision the shuffling cannot deliver, and the number would
    # then travel into a report as if it had been measured.
    values, labels = labelled({
        "/a": [10_000.0] * 50,
        "/b": uniform(150, 80, seed=5),
    })
    result = cn.assess(values, labels, trials=100)
    assert result.p_value == pytest.approx(1 / 101)
    assert result.p_value > 0


def test_the_same_data_always_reads_the_same():
    # The shuffling is a measurement instrument. One that reads differently on
    # every run cannot support a captured verdict.
    args = labelled({f"/{c}": uniform(50, 100 + i * 40, seed=i) for i, c in enumerate("abcd")})
    first = cn.assess(*args, trials=100)
    second = cn.assess(*args, trials=100)
    assert (first.p_value, first.null_threshold, first.group) == \
           (second.p_value, second.null_threshold, second.group)


def test_a_gap_at_the_middle_of_the_null_is_ordinary():
    values = uniform(200, 80, seed=21)
    labels = [f"/{'abcd'[i % 4]}" for i in range(200)]
    result = cn.assess(values, labels, trials=200)
    # Not standing out is not the same as being typical; both are reported so
    # the caller can tell "spread" from "elevated, not established".
    assert result.is_ordinary or (not result.stands_out)


def test_truncation_is_carried_into_the_description():
    values, labels = labelled({f"/{c}": uniform(50, 80, seed=i) for i, c in enumerate("abcd")})
    result = cn.assess(values, labels, trials=50, sample_truncated=True)
    assert "not on the window" in result.describe()


def test_the_description_names_the_numbers_it_decided_on():
    values, labels = labelled({
        "/a": uniform(50, 600, seed=1),
        "/b": uniform(150, 80, seed=2),
    })
    text = cn.assess(values, labels, trials=100).describe()
    for fragment in ("has median", "Redrawing each group", "p="):
        assert fragment in text


# --------------------------------------------------------------------------
# Each group against its own normal
# --------------------------------------------------------------------------

#: One group permanently slower, in the baseline and in the focus window alike.
PERMANENTLY_SLOW = {"/slow": 420.0, "/a": 70.0, "/b": 70.0, "/c": 70.0}

#: The same window after everything rises by the same amount. The gap between
#: subgroups is unchanged, so it explains none of the rise.
UNIFORM_RISE = {label: median + 300.0 for label, median in PERMANENTLY_SLOW.items()}


def test_a_subgroup_that_was_always_slower_is_not_a_new_concentration():
    # The failure the baseline reference exists for, and the one the evaluation
    # measured: without it the probe confirmed `/slow` in 5 runs of 5 on a rise
    # that was spread evenly across every group. "This subgroup is slow" is true
    # every day and explains nothing; only "this subgroup got slower than the
    # rest did" is a concentration.
    for seed in (1, 17, 33, 49, 65):
        result = cn.assess(*window(UNIFORM_RISE, 50, seed),
                           *window(PERMANENTLY_SLOW, 400, seed + 1000), trials=200)
        assert not result.stands_out, f"confirmed a standing gap as a change at seed {seed}"


def test_without_the_baseline_the_same_window_is_confirmed():
    # The other half of the test above: the data are unchanged and only the
    # baseline is withheld, so whatever difference appears is the baseline doing
    # the work rather than some other property of these numbers.
    values, labels = window(UNIFORM_RISE, 50, 1)
    bare = cn.assess(values, labels, trials=200)
    assert bare.stands_out and bare.group == "/slow"
    assert bare.baseline_referenced is False


def test_a_real_change_on_top_of_a_standing_gap_still_stands_out():
    # Subtracting the normal must not subtract the incident with it. `/slow` is
    # permanently slower AND is the only group that moved.
    focus = {**PERMANENTLY_SLOW, "/slow": 420.0 + 600.0}
    result = cn.assess(*window(focus, 50, 3),
                       *window(PERMANENTLY_SLOW, 400, 3 + 1000), trials=200)
    assert result.stands_out and result.group == "/slow"


def test_the_result_says_which_question_it_answered():
    # `excess` means "the change in the gap" with a baseline and "the gap"
    # without one. A field that carries either without saying which is the
    # two-rulers failure this project spends a whole gate on.
    values, labels = window(UNIFORM_RISE, 50, 5)
    referenced = cn.assess(values, labels, *window(PERMANENTLY_SLOW, 400, 1005), trials=100)
    assert referenced.baseline_referenced
    # The gap that was subtracted is reported, not taken on faith. Which group
    # wins is whichever wobbled highest here -- nothing is concentrated -- so the
    # check is that the number is present and belongs to that group.
    assert referenced.normal_gap is not None
    assert "from its own level outside this window" in referenced.describe()
    assert f"{referenced.normal_gap:+.2f}" in referenced.describe()

    bare = cn.assess(values, labels, trials=100)
    assert bare.baseline_referenced is False and bare.normal_gap is None
    assert "no baseline read" in bare.describe()


def test_a_group_with_too_little_history_is_dropped_and_named():
    # An offset estimated from a handful of documents adds more noise than it
    # removes, and the noise lands on the confirming side. Declining is the
    # under-claiming direction, which is the one this project chooses.
    focus_values, focus_labels = window({"/a": 80.0, "/b": 80.0, "/new": 80.0}, 50, 7)
    base_values, base_labels = labelled({
        "/a": uniform(400, 80, seed=71),
        "/b": uniform(400, 80, seed=72),
        "/new": uniform(4, 80, seed=73),
    })
    result = cn.assess(focus_values, focus_labels, base_values, base_labels, trials=100)
    assert any(entry.startswith("/new") for entry in result.without_normal)
    assert "for want of a baseline" in result.describe()


def _shuffled_threshold(values, labels, eligible, trials=200):
    """What the null would be if the labels were shuffled over the pooled values.

    The version this module used first, kept here as the thing being measured
    against rather than as a description of it -- a test that restates the code
    in a second dialect agrees with the code's bugs.
    """
    rng = random.Random(cn.SEED)
    shuffled = list(labels)
    null = []
    for _ in range(trials):
        rng.shuffle(shuffled)
        null.append(cn._excesses(values, shuffled, eligible)[1])
    null.sort()
    return null[min(len(null) - 1, int(round((1 - cn.ALPHA) * len(null))))]


def test_the_null_keeps_each_group_its_own_spread():
    # A slow subgroup varies more in milliseconds for the same reason it is
    # slow. Shuffling the labels pools every group's spread into one, so the
    # widest group gets judged against the average variation rather than its
    # own -- and then it looks like it moved when only it could have moved that
    # far by accident. Redrawing each group from its own values does not, and on
    # a window holding one much wider group the difference has to be visible in
    # the threshold itself, not merely in how often the two disagree.
    # Every group already sits at the same level -- what the baseline subtraction
    # produces -- and one of them varies ten times as much as the rest.
    wide = uniform(50, 900, seed=2)
    values, labels = labelled({
        "/wide": [v - 900.0 + 90.0 for v in wide],
        "/a": uniform(50, 90, seed=3),
        "/b": uniform(50, 90, seed=4),
        "/c": uniform(50, 90, seed=5),
    })
    eligible = ["/wide", "/a", "/b", "/c"]
    result = cn.assess(values, labels, trials=200)
    assert result.null_threshold > _shuffled_threshold(values, labels, eligible) * 1.5

    # And where every group has the same spread there is nothing to pool wrongly,
    # so the two nulls have to agree. Otherwise the difference above is this
    # module being differently shaped rather than differently right.
    even_values, even_labels = labelled({f"/{c}": uniform(50, 90, seed=i)
                                         for i, c in enumerate("abcd")})
    even = cn.assess(even_values, even_labels, trials=200)
    pooled = _shuffled_threshold(even_values, even_labels, [f"/{c}" for c in "abcd"])
    assert even.null_threshold == pytest.approx(pooled, rel=0.35)


def test_an_empty_baseline_is_an_attempted_read_not_an_absent_one():
    """`baseline_values=[]` means the baseline was read and held nothing --
    materially different from None, where no baseline was offered at all.
    Truthiness conflated the two and silently fell back to the weaker
    gap-question; `is not None` routes the empty read into the refusal that
    names what could not be normalized. Found by an automated review, kept
    because absent-versus-empty is this module's own stated rule."""
    rng = random.Random(7)
    values = [rng.gauss(100, 10) for _ in range(120)]
    labels = ["a", "b"] * 60

    silently_weaker = cn.assess(values, labels, None, None)
    refused = cn.assess(values, labels, [], [])

    # No baseline offered: the probe answers the gap question.
    assert silently_weaker.excess is not None
    # Baseline offered and empty: the probe refuses rather than substituting.
    assert refused.excess is None
    assert refused.baseline_referenced is False
    assert refused.compared == 0
