"""Gate 2 traversal: what was looked at, and what was left standing.

No running cluster: the tree is plain data by design.

Each test pins one rule that makes a traversal record mean something. The rules
divide on two axes -- whether re-running would change a branch (what to do next)
and whether a branch has been disposed of (whether the chain may close) -- and
conflating those two is the mistake these tests exist to catch.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "observability" / "unclosed" / "scripts"),
)

from traversal import (  # noqa: E402
    DISPOSED,
    MOVABLE,
    OPEN,
    SETTLED,
    Gate1Carryover,
    Node,
    NodeState,
    Traversal,
)


T0 = "2026-08-02T09:15:00Z"
T1 = "2026-08-02T09:41:00Z"


def confirmed(name, *children, accounts=None):
    return Node(name, NodeState.CONFIRMED, probe=f"queried {name}", evidence="matched",
                magnitude_accounted=accounts, children=tuple(children))


def ruled_out(name):
    return Node(name, NodeState.RULED_OUT, probe=f"queried {name}", evidence="excluded")


def inconclusive(name):
    return Node(name, NodeState.INCONCLUSIVE, probe=f"queried {name}", evidence="neither supports nor excludes")


def pending(name, awaiting="the shard to finish backfilling", at=T0):
    return Node(name, NodeState.PENDING, awaiting=awaiting, observed_at=at)


def not_visited(name, reason=None):
    return Node(name, NodeState.NOT_VISITED, not_visited_reason=reason)


def tree(root, gate1=None):
    return Traversal(observation="p99 rose 5x in the 14:20 bucket", root=root, gate1=gate1)


# --- the two axes are not the same axis -----------------------------------


def test_inconclusive_is_settled_and_still_open():
    """The one state in both sets, and the reason both sets exist.

    Re-running does not move it, so it is finished work. The branch is still
    standing, so nothing may close over it. A design with a single axis has to
    lose one of those two facts.
    """
    assert NodeState.INCONCLUSIVE in SETTLED
    assert NodeState.INCONCLUSIVE in OPEN
    assert NodeState.INCONCLUSIVE not in MOVABLE
    assert NodeState.INCONCLUSIVE not in DISPOSED


def test_every_state_lands_on_exactly_one_side_of_each_axis():
    for state in NodeState:
        assert (state in SETTLED) ^ (state in MOVABLE), state
        assert (state in DISPOSED) ^ (state in OPEN), state


# --- closure --------------------------------------------------------------


def test_a_chain_closes_only_when_every_alternative_is_disposed_of():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan", ruled_out("cache eviction"))))
    assert t.is_closed
    assert len(t.closed_chains()) == 1


def test_a_confirmed_branch_does_not_close_while_a_sibling_is_inconclusive():
    """The first plausible correlate is not an answer.

    Confirming one branch while an alternative to it is still standing is
    precisely the failure this gate exists to catch, and it is invisible in any
    output that reports only what was found.
    """
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan"), inconclusive("upstream retry storm")))
    assert not t.is_closed
    assert any("not ruled out" in r for r in t.unclosed_reasons())
    # Pin the traversal itself, not just the wording of the report. `is_closed`
    # would still be False here on the strength of the reason list alone, which
    # would leave the rule inside closed_chains() untested -- and mutation
    # verification caught exactly that.
    assert t.closed_chains() == []


def test_a_confirmed_branch_does_not_close_while_a_sibling_was_never_walked():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan"), not_visited("GC pause")))
    assert not t.is_closed
    assert t.closed_chains() == []


def test_a_confirmed_branch_does_not_close_while_a_sibling_is_pending():
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan"), pending("shard rebalance")))
    assert not t.is_closed
    assert t.closed_chains() == []


def test_ruled_out_siblings_do_not_block_closure():
    """Disposing of an alternative is the work. It must not read as a defect."""
    t = tree(confirmed("deploy at 14:18", confirmed("new query plan"), ruled_out("GC pause"), ruled_out("noisy neighbour")))
    assert t.is_closed
    chain = t.closed_chains()
    assert len(chain) == 1
    assert [n.hypothesis for n in chain[0]] == ["deploy at 14:18", "new query plan"]


# --- Gate 1 travels with the tree -----------------------------------------


def test_an_undecidable_premise_does_not_stop_the_traversal():
    """Branches below an unverified premise are still worth walking.

    Gate 1 failing to clear the premise is not a reason to collect no evidence.
    The evidence is real; what it rests on is what is in question.
    """
    t = tree(
        confirmed("deploy at 14:18", ruled_out("cache eviction")),
        gate1=Gate1Carryover("UNDECIDABLE", ("a second time field (ingest/observed time)",)),
    )
    assert len(t.in_state(*SETTLED)) == 2
    assert t.closed_chains()


def test_a_gate1_gap_keeps_the_tree_open_even_when_every_node_closed():
    """The unbought ticket is at the entrance, and by the last turnstile nobody remembers.

    Without this, a perfect-looking tree can rest on a premise that was never
    verified -- and the report would read as complete.
    """
    perfect = confirmed("deploy at 14:18", ruled_out("cache eviction"))
    assert tree(perfect).is_closed

    carried = tree(perfect, gate1=Gate1Carryover("UNDECIDABLE", ("a second time field (ingest/observed time)",)))
    assert not carried.is_closed
    assert any("[premise]" in r for r in carried.unclosed_reasons())


def test_a_substantiated_premise_carries_no_gap():
    t = tree(confirmed("deploy at 14:18", ruled_out("cache eviction")), gate1=Gate1Carryover("SUBSTANTIATED", ()))
    assert t.is_closed


# --- PENDING must not become the escape hatch -----------------------------


def test_pending_must_name_what_it_awaits():
    with pytest.raises(ValueError, match="must name what it is waiting on"):
        Node("shard rebalance", NodeState.PENDING, observed_at=T0)


def test_pending_must_record_the_moment_its_state_was_read():
    with pytest.raises(ValueError, match="moment this state was read"):
        Node("shard rebalance", NodeState.PENDING, awaiting="the shard to finish")


def test_pending_rejects_an_unparseable_moment():
    with pytest.raises(ValueError, match="not a parseable time"):
        Node("shard rebalance", NodeState.PENDING, awaiting="the shard", observed_at="sometime this morning")


def test_only_pending_may_await_something():
    with pytest.raises(ValueError, match="only PENDING may name what it awaits"):
        Node("GC pause", NodeState.NOT_VISITED, awaiting="nothing in particular")


# --- a node may not record an answer it does not have ---------------------


def test_settled_states_must_record_the_probe_and_its_evidence():
    with pytest.raises(ValueError, match="must record both the probe and its evidence"):
        Node("new query plan", NodeState.CONFIRMED, probe="queried it")


def test_movable_states_must_not_carry_evidence():
    """A branch nobody walked cannot have found anything."""
    with pytest.raises(ValueError, match="no answer to record"):
        Node("GC pause", NodeState.NOT_VISITED, probe="queried it", evidence="looked fine")


def test_an_unwalked_branch_still_has_to_be_named():
    """The state only exists so the branch is visible. An unnamed one is not a record."""
    with pytest.raises(TypeError):
        Node(state=NodeState.NOT_VISITED)  # noqa


# --- magnitude may not outrun the evidence --------------------------------


def test_only_a_confirmed_node_may_account_for_magnitude():
    """Otherwise Gate 3 could close its arithmetic on a branch Gate 2 never established."""
    with pytest.raises(ValueError, match="only a CONFIRMED node may account for magnitude"):
        Node("upstream retry storm", NodeState.INCONCLUSIVE, probe="q", evidence="e", magnitude_accounted=380.0)


def test_a_branch_that_restates_the_observation_may_not_account_for_it():
    """"The whole distribution shifted up" is the observation said a second way.

    If it could carry the effect, the chain would close on "it got slower
    because it got slower" -- which is the most confident-sounding empty answer
    available, and the one a reader is least equipped to challenge.
    """
    with pytest.raises(ValueError, match="descriptive branch may not account for magnitude"):
        Node("the whole distribution moved", NodeState.CONFIRMED, probe="compared p50 and p99",
             evidence="p50 moved too", explanatory=False, magnitude_accounted=380.0)


def test_gate2_does_not_claim_the_magnitude_question():
    """is_closed is Gate 2's half. Saying more here would answer Gate 3 without doing its work."""
    t = tree(confirmed("deploy at 14:18", ruled_out("cache eviction"), accounts=8.0))
    assert t.is_closed
    assert "Gate 3" in t.to_text()


# --- settled work survives a block elsewhere ------------------------------


def test_evidence_on_one_branch_is_not_invalidated_by_a_block_on_another():
    """Being stopped at one turnstile does not void the tickets already bought.

    A traversal that discards finished work whenever something else is blocked
    would make every incomplete run indistinguishable from a run that found
    nothing -- which is most runs.
    """
    t = tree(confirmed(
        "deploy at 14:18",
        ruled_out("cache eviction"),
        ruled_out("noisy neighbour"),
        pending("shard rebalance"),
    ))
    assert not t.is_closed
    assert len(t.in_state(*SETTLED)) == 3
    text = t.to_text()
    assert "3 branch(es) settled" in text
    assert "does not invalidate evidence collected on another" in text


# --- the report has to say what to do next --------------------------------


def test_the_three_open_states_produce_three_different_next_actions():
    """Reporting "not closed" without saying which kind of gap it is helps nobody."""
    t = tree(confirmed(
        "deploy at 14:18",
        pending("shard rebalance"),
        not_visited("GC pause"),
        inconclusive("upstream retry storm"),
    ))
    text = t.to_text()
    assert "wait and re-run" in text
    assert "go and look" in text
    assert "different evidence, and it may not exist" in text


def test_a_closed_chain_is_never_called_a_cause():
    """The contract: logs cannot establish causation, so the output never asserts one."""
    text = tree(confirmed("deploy at 14:18", ruled_out("cache eviction"))).to_text()
    assert "is not a cause" in text
    assert "the cause is" not in text.lower()


def test_an_unwalked_branch_appears_in_the_report():
    """A tree that omits what it skipped looks complete, and looking complete is the failure."""
    text = tree(confirmed("deploy at 14:18", confirmed("new query plan"), not_visited("GC pause"))).to_text()
    assert "GC pause" in text
    assert "NOT_VISITED" in text


# --- two clocks -----------------------------------------------------------


def test_states_read_at_different_moments_are_reported_as_a_span():
    """Two nodes read 26 minutes apart are two datasets sharing a tree.

    The spread is the width of the window in which this tree was ever
    simultaneously true. Averaging it away would hide exactly the thing a reader
    needs to judge whether to trust it.
    """
    t = tree(confirmed("deploy at 14:18", pending("shard rebalance", at=T0), pending("index backfill", at=T1)))
    span = t.observation_span
    assert span and span[0].isoformat() != span[1].isoformat()
    assert "never simultaneously true" in t.to_text()


def test_a_tree_read_at_one_moment_reports_no_span():
    t = tree(confirmed("deploy at 14:18", pending("shard rebalance", at=T0), pending("index backfill", at=T0)))
    assert "never simultaneously true" not in t.to_text()
