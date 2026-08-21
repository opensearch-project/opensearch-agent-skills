"""Judged against the thing it would have to explain, not only against chance.

A concentration probe asks whether a subgroup moved further than redrawing at
one level produces. That is a question about *chance*. Closure asks whether any
rival account of the effect is still standing, which is a question about *size*,
and the two were never connected: a 13ms subgroup gap in the upper half of its
own null blocked a chain explaining a 1900ms rise.

Measured, that cost everything -- 0 of 11 runs closed, because three innocent
dimensions each had to land in the lower half of their own null by luck. The
arithmetic is in examples/closure-ceiling.txt.

`IMMATERIAL` is the state for a branch that was measured and cannot be the
answer. It is deliberately not a softer INCONCLUSIVE:

  INCONCLUSIVE  we could not establish whether the effect lives here
  IMMATERIAL    we measured how big this is, and it is too small to be where
                the effect lives

The second is a claim about magnitude and needs a measurement. A branch nobody
could compare at all never becomes IMMATERIAL -- "too small to matter" is
something you find out, not something you say when you did not look. That is the
load-bearing test in this file, because it is the way this state could quietly
become the escape hatch the whole design exists to refuse.
"""

import pytest

import assemble_traversal as at
from closure_audit import RESIDUAL_TOLERANCE
from traversal import DISPOSED, OPEN, SETTLED, NodeState

EFFECT = 1900.0


# --------------------------------------------------------------------------
# The comparison itself
# --------------------------------------------------------------------------

def test_a_wobble_far_under_the_effect_is_immaterial():
    assert at._immaterial(13.5, EFFECT, RESIDUAL_TOLERANCE) is True


def test_a_branch_that_could_carry_the_effect_is_not():
    assert at._immaterial(1500.0, EFFECT, RESIDUAL_TOLERANCE) is False


def test_the_bar_is_the_share_and_not_an_absolute_size():
    """13ms is nothing against 1900 and most of the story against 40."""
    assert at._immaterial(13.5, 1900.0, RESIDUAL_TOLERANCE) is True
    assert at._immaterial(13.5, 40.0, RESIDUAL_TOLERANCE) is False


def test_exactly_at_the_floor_is_not_immaterial():
    """The floor is what this project will still size an explanation to."""
    assert at._immaterial(RESIDUAL_TOLERANCE * EFFECT, EFFECT, RESIDUAL_TOLERANCE) is False


def test_a_widened_tolerance_widens_this_too():
    """Rulers that disagree about the effect cannot sharpen a judgement about it."""
    excess = 0.30 * EFFECT
    assert at._immaterial(excess, EFFECT, RESIDUAL_TOLERANCE) is False
    assert at._immaterial(excess, EFFECT, 0.40) is True


def test_an_unmeasured_branch_is_never_immaterial():
    """The escape hatch this state must not become."""
    assert at._immaterial(None, EFFECT, RESIDUAL_TOLERANCE) is None


def test_an_effect_of_zero_leaves_the_question_unanswerable():
    """Every size is infinite as a share of nothing; refusing beats dividing."""
    assert at._immaterial(13.5, 0.0, RESIDUAL_TOLERANCE) is None
    assert at._immaterial(13.5, None, RESIDUAL_TOLERANCE) is None


def test_a_negative_effect_is_judged_on_its_size():
    """A window that got faster is still a window with a size."""
    assert at._immaterial(13.5, -1900.0, RESIDUAL_TOLERANCE) is True
    assert at._immaterial(1500.0, -1900.0, RESIDUAL_TOLERANCE) is False


# --------------------------------------------------------------------------
# Where the state sits
# --------------------------------------------------------------------------

def test_immaterial_is_settled_and_disposed_but_is_not_ruled_out():
    assert NodeState.IMMATERIAL in SETTLED
    assert NodeState.IMMATERIAL in DISPOSED
    assert NodeState.IMMATERIAL not in OPEN
    assert NodeState.IMMATERIAL is not NodeState.RULED_OUT


def test_it_still_has_to_say_what_was_measured():
    """Disposed by measurement, so the measurement has to be on the record."""
    with pytest.raises(ValueError):
        at.Node("the rise is confined to one region", NodeState.IMMATERIAL)


def test_an_unmeasurable_branch_stays_open(monkeypatch):
    """Only one value present: nothing to compare, so nothing to call small."""
    node = at._concentration_node(
        "e", "i", "region", "the rise is confined to one region", "latency_ms",
        "FOCUS", 450.0, sample=[{"region": "us-east-1", "latency_ms": 90.0}], truncated=False,
        observed_effect=EFFECT,
    )[1]
    assert node.state is NodeState.INCONCLUSIVE
    assert node.state in OPEN
