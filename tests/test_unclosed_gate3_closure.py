"""Gate 3: does the explanation account for the size of the thing it explains?

No running cluster.

The case this gate exists for is the seductive one: every step in the chain is
true, every alternative is disposed of, and the whole thing explains 8ms of a
400ms regression. Gate 2 passes it. Only the arithmetic catches it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "observability" / "unclosed" / "scripts"),
)

from closure_audit import (  # noqa: E402
    RESIDUAL_TOLERANCE,
    Accounting,
    audit_closure,
    closes,
)
from traversal import Gate1Carryover, Node, NodeState, Traversal  # noqa: E402


OBSERVED = 400.0  # a 400ms regression, in the metric's own units


def confirmed(name, *children, accounts=None):
    return Node(name, NodeState.CONFIRMED, probe=f"queried {name}", evidence="matched",
                magnitude_accounted=accounts, children=tuple(children))


def ruled_out(name):
    return Node(name, NodeState.RULED_OUT, probe=f"queried {name}", evidence="excluded")


def inconclusive(name):
    return Node(name, NodeState.INCONCLUSIVE, probe=f"queried {name}", evidence="settles nothing")


def tree(root, gate1=None):
    return Traversal(observation="p99 rose 400ms in the 14:20 bucket", root=root, gate1=gate1)


# --- the case the gate exists for -----------------------------------------


def test_a_true_chain_that_explains_almost_nothing_is_rejected():
    """Every step true, every alternative disposed of, 8ms of a 400ms effect.

    Gate 2 closes this. If Gate 3 did not exist, the report would read as a
    finished investigation.
    """
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=8.0), ruled_out("GC pause")))
    assert t.is_closed  # Gate 2 is satisfied
    assert audit_closure(t, OBSERVED).verdict is Accounting.UNDER_ACCOUNTED

    closed, reasons = closes(t, OBSERVED)
    assert not closed
    assert any("[magnitude]" in r for r in reasons)


def test_an_explanation_that_matches_the_effect_is_accepted():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=380.0), ruled_out("GC pause")))
    report = audit_closure(t, OBSERVED)
    assert report.verdict is Accounting.ACCOUNTED
    assert report.residual == pytest.approx(20.0)
    assert closes(t, OBSERVED)[0]


def test_overshooting_is_rejected_too():
    """An explanation covering 900ms of a 400ms effect is as unusable as one covering 8ms.

    Usually double counting; occasionally the baseline is wrong. Either way it
    is not an account of what happened, and nothing else in the pipeline looks
    for it.
    """
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=900.0)))
    report = audit_closure(t, OBSERVED)
    assert report.verdict is Accounting.OVER_ACCOUNTED
    assert "counted twice" in report.to_text()


def test_the_tolerance_boundary_is_where_it_says_it_is():
    inside = OBSERVED * (1 - RESIDUAL_TOLERANCE)
    outside = inside - 1.0
    assert audit_closure(tree(confirmed("d", confirmed("q", accounts=inside))), OBSERVED).verdict is Accounting.ACCOUNTED
    assert audit_closure(tree(confirmed("d", confirmed("q", accounts=outside))), OBSERVED).verdict is Accounting.UNDER_ACCOUNTED


# --- a gate that cannot decide must say what it lacked ---------------------


def test_a_confirmed_but_unmeasured_branch_blocks_the_arithmetic_and_names_itself():
    """Same discipline as Gate 1's COULD_NOT_RUN: name the missing input.

    Otherwise "cannot decide" becomes the place everything goes to hide.
    """
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan")))
    report = audit_closure(t, OBSERVED)
    assert report.verdict is Accounting.NOT_QUANTIFIED
    assert report.unquantified == ["new query plan"]
    assert "new query plan" in report.to_text()


def test_one_unmeasured_branch_blocks_the_arithmetic_even_when_another_adds_up():
    """The dangerous shape, and the one mutation verification had to find for me.

    380 of 400 is attributed and a second confirmed branch was never measured.
    Letting the arithmetic run treats the unmeasured branch as contributing
    zero -- turning "nobody measured this" into "this contributed nothing",
    which is an assertion no one made. The residual then looks like 20ms of
    honest slack instead of one measured branch and one unknown.
    """
    t = tree(confirmed("deploy at 14:18",
                       confirmed("new query plan", accounts=380.0),
                       confirmed("cold cache")))
    report = audit_closure(t, OBSERVED)
    assert report.verdict is Accounting.NOT_QUANTIFIED
    assert report.unquantified == ["cold cache"]


def test_a_descriptive_branch_is_not_a_measurement_gap():
    """A branch that restates the observation has no number to be missing.

    Counting its absence as a gap would make every tree containing one report
    NOT_QUANTIFIED forever -- a verdict that then says nothing about any
    incident, because it is really reporting the shape of the tree.
    """
    shape = Node("the whole distribution moved", NodeState.CONFIRMED, probe="compared p50 and p99",
                 evidence="the median moved too", explanatory=False)
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=380.0), shape))
    report = audit_closure(t, OBSERVED)
    assert report.unquantified == []
    assert report.verdict is Accounting.ACCOUNTED


def test_nothing_confirmed_to_explain_is_reported_as_that_and_not_as_a_missing_number():
    """"Nobody measured the candidate" and "there is no candidate" are different
    facts, and they send the reader to different places."""
    shape = Node("the whole distribution moved", NodeState.CONFIRMED, probe="compared p50 and p99",
                 evidence="the median moved too", explanatory=False)
    t = tree(confirmed("deploy at 14:18", shape, ruled_out("GC pause")))
    report = audit_closure(t, OBSERVED)
    assert report.verdict is Accounting.NOT_QUANTIFIED
    assert report.unquantified == []
    assert "absence of a candidate" in report.to_text()


def test_not_quantified_is_not_reported_as_under_accounted():
    """Zero attributed because nobody measured is a different fact from zero attributed
    because the branches genuinely explain nothing, and conflating them would tell
    the reader to go looking for a cause that may already be in front of them."""
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan")))
    assert audit_closure(t, OBSERVED).verdict is not Accounting.UNDER_ACCOUNTED


# --- no double counting, enforced by shape --------------------------------


def test_a_parent_may_not_account_for_what_its_child_already_accounts_for():
    """"The deploy did 380ms" and "the query plan under it did 380ms" are one 380ms."""
    with pytest.raises(ValueError, match="counted twice"):
        confirmed("deploy at 14:18", confirmed("new query plan", accounts=380.0), accounts=380.0)


def test_the_guard_reaches_grandchildren():
    with pytest.raises(ValueError, match="counted twice"):
        confirmed("deploy", confirmed("plan", confirmed("scan", accounts=380.0)), accounts=380.0)


def test_siblings_may_each_account_for_their_own_share():
    """Splitting an effect across genuine contributors is not double counting."""
    t = tree(confirmed("deploy at 14:18",
                       confirmed("new query plan", accounts=240.0),
                       confirmed("cold cache", accounts=150.0)))
    report = audit_closure(t, OBSERVED)
    assert report.accounted == pytest.approx(390.0)
    assert report.verdict is Accounting.ACCOUNTED


# --- Gate 3 does not re-litigate Gate 2 -----------------------------------


def test_magnitude_only_ever_comes_from_confirmed_branches():
    """Enforced upstream at construction. Gate 3 filtering on its own would mean
    deciding which of Gate 2's verdicts to trust, with less evidence than Gate 2 had."""
    with pytest.raises(ValueError, match="only a CONFIRMED node may account for magnitude"):
        Node("upstream retry storm", NodeState.INCONCLUSIVE, probe="q", evidence="e", magnitude_accounted=380.0)


def test_a_perfect_magnitude_does_not_close_a_tree_gate2_left_open():
    """The arithmetic adding up says nothing about whether an alternative is still standing."""
    t = tree(confirmed("deploy at 14:18",
                       confirmed("new query plan", accounts=380.0),
                       inconclusive("upstream retry storm")))
    assert audit_closure(t, OBSERVED).verdict is Accounting.ACCOUNTED
    closed, reasons = closes(t, OBSERVED)
    assert not closed
    assert any("not ruled out" in r for r in reasons)


def test_a_perfect_magnitude_does_not_close_over_an_unverified_premise():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=380.0)),
             gate1=Gate1Carryover("UNDECIDABLE", ("a second time field (ingest/observed time)",)))
    assert audit_closure(t, OBSERVED).verdict is Accounting.ACCOUNTED
    closed, reasons = closes(t, OBSERVED)
    assert not closed
    assert any("[premise]" in r for r in reasons)


def test_all_four_conditions_together_still_refuse_to_name_a_cause():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=380.0), ruled_out("GC pause")),
             gate1=Gate1Carryover("SUBSTANTIATED", ()))
    closed, reasons = closes(t, OBSERVED)
    assert closed and reasons == []
    assert "is not a cause" in t.to_text()
    assert "still not a cause" in audit_closure(t, OBSERVED).to_text()


# --- the residual is reported, not absorbed -------------------------------


def test_the_unexplained_remainder_is_always_stated():
    """92% explained leaves 8% nobody has accounted for, and that is a fact about
    the incident rather than a rounding error to be folded into a pass."""
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=368.0)))
    report = audit_closure(t, OBSERVED)
    assert report.verdict is Accounting.ACCOUNTED
    assert report.residual == pytest.approx(32.0)
    text = report.to_text()
    assert "unexplained" in text
    assert "+32.00" in text


def test_a_near_zero_effect_declines_the_ratio_instead_of_dividing_by_it():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=5.0)))
    report = audit_closure(t, 0.0)
    assert report.residual_fraction is None
    assert report.verdict is Accounting.OVER_ACCOUNTED


# --- a residual finer than the ruler is not a finding ----------------------


def test_the_tolerance_widens_to_the_measurement_and_says_so():
    """An explanation covering 75% of an effect whose size is only known to
    within 30% has not fallen short of anything a reader could act on.

    The widening is reported. A pass at a loosened tolerance is a weaker claim
    and has to read like one, or the report launders imprecision into agreement.
    """
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=300.0)))
    strict = audit_closure(t, OBSERVED)
    assert strict.verdict is Accounting.UNDER_ACCOUNTED  # 25% short of 400

    loose = audit_closure(t, OBSERVED, measurement_uncertainty=0.30)
    assert loose.verdict is Accounting.ACCOUNTED
    assert loose.tolerance == pytest.approx(0.30)
    assert "two estimators disagree" in loose.to_text()


def test_a_ruler_more_precise_than_the_tolerance_does_not_tighten_it():
    """The tolerance is a declaration about what counts as an explanation, not a
    statistical bound. A sharper ruler does not raise the bar for one."""
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=330.0)))
    assert audit_closure(t, OBSERVED, measurement_uncertainty=0.02).tolerance == pytest.approx(RESIDUAL_TOLERANCE)
    assert audit_closure(t, OBSERVED, measurement_uncertainty=0.02).verdict is Accounting.ACCOUNTED


def test_closes_carries_the_uncertainty_through():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", accounts=300.0), ruled_out("GC pause")),
             gate1=Gate1Carryover("SUBSTANTIATED", ()))
    assert not closes(t, OBSERVED)[0]
    assert closes(t, OBSERVED, measurement_uncertainty=0.30)[0]
