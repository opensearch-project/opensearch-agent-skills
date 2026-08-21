#!/usr/bin/env python3
"""Gate 2 -- the traversal record.

Gate 1 asked whether the observation is real. This gate asks a different
question: given that something is worth explaining, *what was actually looked
at* on the way to explaining it.

The failure this addresses is not being wrong. It is being unfalsifiably
right-looking: an agent follows the direction the question implies, halts at the
first plausible correlate, and reports it. What it found was *a* related signal.
What it reported was *the* cause. Nothing in that output distinguishes "I
checked the four alternatives and none held" from "I never thought of them".

So the output is not a conclusion. It is the tree: every hypothesis that was
raised, what was queried for it, what came back, and -- the part that is
normally invisible -- every branch that was named and never walked.

Node states
-----------
A branch is not binary. The states divide on one axis that matters
operationally: **would running this again change the answer?**

    CONFIRMED     evidence supports this link                    settled
    RULED_OUT     evidence excludes this branch                  settled
    INCONCLUSIVE  it was queried; the answer neither supports
                  nor excludes. Different evidence is needed,
                  not more patience                              settled
    PENDING       it was asked and has not come back yet at the
                  moment this tree was assembled. Time alone
                  resolves it                                    movable
    NOT_VISITED   the branch exists in the hypothesis space and
                  no one walked it                               movable

The three settled states are finished work and are reported as such even when
the chain does not close -- evidence collected on one branch is not invalidated
by another branch being blocked. The two movable states are the only ones that
generate a next action, and they generate *different* ones: PENDING says wait
and re-run, NOT_VISITED says go and look.

Why PENDING needs a guard
-------------------------
A state meaning "not answered yet" is an escape hatch unless something stops it
from being free. Left unconstrained it re-opens, one level up, exactly the hole
Gate 1's verdict precedence was built to close: anything inconvenient becomes
"pending" and the tree never has to close.

So PENDING must name what it is waiting on **and** the moment its state was
read, and the constructor enforces both. A state read at one moment is not the
same state at the next; a pending branch with no timestamp is a claim about a
present that has already passed.

Naming
------
Gate 1's `REFUTED` means "the observation is an artifact". This gate's
`RULED_OUT` means "this hypothesis does not hold". Different subjects. They are
deliberately not the same word.

Standard library only. No retrieval here -- judgment must be testable without a
cluster, and a node must not be able to widen its own evidence while deciding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class NodeState(str, Enum):
    CONFIRMED = "CONFIRMED"
    RULED_OUT = "RULED_OUT"
    INCONCLUSIVE = "INCONCLUSIVE"
    IMMATERIAL = "IMMATERIAL"
    PENDING = "PENDING"
    NOT_VISITED = "NOT_VISITED"


# Two axes, and they are not the same axis.
#
# The first asks: would running this again change the answer? It decides what
# the reader should do next.

#: Finished work. Re-running changes nothing.
SETTLED = frozenset({NodeState.CONFIRMED, NodeState.RULED_OUT, NodeState.INCONCLUSIVE,
                     NodeState.IMMATERIAL})

#: Can still move, and the only states that produce a next action.
MOVABLE = frozenset({NodeState.PENDING, NodeState.NOT_VISITED})

# The second asks: has this branch been disposed of? It decides closure.

#: Resolved one way or the other. The branch is off the board.
#:
#: IMMATERIAL is here, and it is the one that needs defending. It does not mean
#: the branch was ruled out -- it was not, and the tree still reports it as
#: elevated. It means the branch was *measured against the thing being
#: explained* and cannot be it: a subgroup gap of 13ms is not a rival account of
#: a 1900ms rise at any confidence.
#:
#: The earlier version had no such comparison. A branch was judged only against
#: its own null, so a wobble in the upper half of that null blocked a chain
#: exactly as a live rival did, and the measured cost was that nothing ever
#: closed: 0 of 11 runs, with three innocent dimensions each needing to land in
#: the lower half of their own null by chance. See examples/closure-ceiling.txt.
DISPOSED = frozenset({NodeState.CONFIRMED, NodeState.RULED_OUT, NodeState.IMMATERIAL})

#: Still standing. Any of these at a decision point keeps the chain open --
#: a confirmed branch means nothing while an alternative to it is still live.
#: Reporting the first plausible correlate as the answer *is* the failure mode
#: this gate exists to catch, and it looks exactly like ignoring these.
OPEN = frozenset({NodeState.INCONCLUSIVE, NodeState.PENDING, NodeState.NOT_VISITED})

# INCONCLUSIVE is the only state in both SETTLED and OPEN: the work is done and
# the branch is still standing. It is the state that can make a chain
# *permanently* unclosable -- no amount of waiting or walking moves it, only
# different evidence, which may not exist. That case is not a defect in the
# tool. It is the honest answer, and the evaluation includes one.
#
# IMMATERIAL is settled and disposed, and is not a weaker INCONCLUSIVE. The two
# answer different questions. INCONCLUSIVE says *we could not establish whether
# this is where the effect lives*. IMMATERIAL says *we measured how big this is,
# and it is too small to be where the effect lives* -- a statement about size,
# which is available whether or not the first question was settled. A branch
# that cannot be measured at all is never IMMATERIAL; it stays INCONCLUSIVE,
# because "too small to matter" is a measurement and not a shrug.

#: States that require the node to say what was queried and what came back.
_REQUIRES_EVIDENCE = frozenset({NodeState.CONFIRMED, NodeState.RULED_OUT,
                                NodeState.INCONCLUSIVE, NodeState.IMMATERIAL})


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class Node:
    """One hypothesis and what happened to it.

    `hypothesis` is required in every state, including NOT_VISITED. That is the
    whole point of the state: an unwalked branch is only visible if it was
    written down. A tree that omits its unwalked branches looks complete, and
    looking complete is the failure being attacked.
    """

    hypothesis: str
    state: NodeState

    # What was actually asked of the data, and what came back. Required for the
    # settled states; forbidden for the two movable ones, which by definition
    # have no answer to record.
    probe: Optional[str] = None
    evidence: Optional[str] = None

    # PENDING only: what is being waited on, and when this state was read.
    awaiting: Optional[str] = None
    observed_at: Optional[str] = None

    # NOT_VISITED only: why the branch was left alone. Optional -- an honest
    # "no reason, it was not walked" is a legitimate record and forcing a
    # justification would only teach the caller to invent one.
    not_visited_reason: Optional[str] = None

    # How much of the observed effect this node accounts for, in the metric's
    # own units. Gate 3 does the arithmetic; Gate 2 only carries the number.
    magnitude_accounted: Optional[float] = None

    # Does this branch claim to *explain* the effect, or to *describe* it?
    #
    # "The whole distribution shifted up" is true, tells you where to look next,
    # and is the observation said a second way. If a descriptive branch could
    # account for magnitude, the chain would close on "it got slower because it
    # got slower" -- the most confident-sounding empty answer available. And if
    # Gate 3 counted it as merely unmeasured, every tree containing one would
    # report NOT_QUANTIFIED forever, which says nothing about the incident.
    #
    # So the distinction is carried on the node: a descriptive branch may not
    # hold a number, and its lack of one is not a gap anybody can close.
    explanatory: bool = True

    children: tuple = ()

    def __post_init__(self):
        if self.state in _REQUIRES_EVIDENCE and not (self.probe and self.evidence):
            raise ValueError(
                f"node {self.hypothesis!r}: {self.state.value} must record both the probe and its evidence"
            )
        if self.state in MOVABLE and (self.probe or self.evidence):
            raise ValueError(
                f"node {self.hypothesis!r}: {self.state.value} has no answer to record, "
                "so it must not carry probe or evidence"
            )

        # The guard that keeps PENDING from becoming the escape hatch.
        if self.state is NodeState.PENDING:
            if not self.awaiting:
                raise ValueError(f"node {self.hypothesis!r}: PENDING must name what it is waiting on")
            if not self.observed_at:
                raise ValueError(
                    f"node {self.hypothesis!r}: PENDING must record the moment this state was read -- "
                    "a pending branch with no timestamp is a claim about a present that has passed"
                )
            if _parse(self.observed_at) is None:
                raise ValueError(f"node {self.hypothesis!r}: observed_at {self.observed_at!r} is not a parseable time")
        else:
            if self.awaiting:
                raise ValueError(f"node {self.hypothesis!r}: only PENDING may name what it awaits")

        if self.not_visited_reason and self.state is not NodeState.NOT_VISITED:
            raise ValueError(f"node {self.hypothesis!r}: only NOT_VISITED may carry not_visited_reason")

        if self.magnitude_accounted is not None and self.state is not NodeState.CONFIRMED:
            raise ValueError(
                f"node {self.hypothesis!r}: only a CONFIRMED node may account for magnitude -- "
                "an unconfirmed branch that contributes to the arithmetic would let Gate 3 close "
                "on evidence Gate 2 never established"
            )

        if self.magnitude_accounted is not None and not self.explanatory:
            raise ValueError(
                f"node {self.hypothesis!r}: a descriptive branch may not account for magnitude -- "
                "it restates the observation, and letting a restatement carry the effect closes "
                "the chain on 'it got slower because it got slower'"
            )

        # No double counting, enforced by shape rather than by convention.
        #
        # "The deploy accounts for 380ms" and "the new query plan under it
        # accounts for 380ms" are the same 380ms described at two depths. Summed,
        # they explain 760ms of a 400ms effect -- and Gate 3 would report a
        # closed chain built on counting one thing twice. Requiring the number to
        # sit at exactly one depth makes that arithmetic impossible to write.
        if self.magnitude_accounted is not None:
            deeper = [n.hypothesis for c in self.children for n in c.walk()
                      if n.magnitude_accounted is not None]
            if deeper:
                raise ValueError(
                    f"node {self.hypothesis!r}: a node whose descendants already account for magnitude "
                    f"may not account for it too -- that is the same effect counted twice. "
                    f"Already accounting below: {deeper}"
                )

    # -- shape -------------------------------------------------------------

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    @property
    def is_leaf(self) -> bool:
        return not self.children


@dataclass(frozen=True)
class Gate1Carryover:
    """What Gate 1 leaves behind when it did not fully clear the premise.

    An UNDECIDABLE premise does not stop the traversal -- the branches below it
    are still worth walking and the evidence found there is still real. But the
    gap has to travel with the tree, because otherwise every node can close and
    the report reads as complete while resting on a premise that was never
    verified. The unbought ticket is at the entrance, and by the last turnstile
    nobody remembers.
    """

    verdict: str
    missing_inputs: tuple = ()

    @property
    def leaves_a_gap(self) -> bool:
        return bool(self.missing_inputs)


@dataclass
class Traversal:
    observation: str
    root: Node
    gate1: Optional[Gate1Carryover] = None
    assembled_at: Optional[str] = None

    # -- inspection --------------------------------------------------------

    def nodes(self) -> list:
        return list(self.root.walk())

    def in_state(self, *states) -> list:
        wanted = set(states)
        return [n for n in self.nodes() if n.state in wanted]

    @property
    def pending(self) -> list:
        return self.in_state(NodeState.PENDING)

    @property
    def not_visited(self) -> list:
        return self.in_state(NodeState.NOT_VISITED)

    @property
    def inconclusive(self) -> list:
        return self.in_state(NodeState.INCONCLUSIVE)

    @property
    def observation_span(self):
        """Earliest and latest moment any node's state was read.

        Two nodes read minutes apart are two different datasets that share a
        tree. The spread is not noise to be averaged away -- it is the width of
        the window in which this tree was ever simultaneously true, and a reader
        deciding whether to trust it needs to see it.
        """
        moments = sorted(m for m in (_parse(n.observed_at) for n in self.nodes()) if m)
        return (moments[0], moments[-1]) if moments else None

    # -- closure -----------------------------------------------------------

    def closed_chains(self) -> list:
        """Root-to-leaf paths on which every node is CONFIRMED and no sibling is movable.

        A chain that closes is *not* a cause. It is a path through the
        hypothesis space along which nothing was left open. Naming it a cause
        would be the error this skill exists to catch.
        """
        chains = []

        def descend(node: Node, path: list):
            path = path + [node]
            if node.state is not NodeState.CONFIRMED:
                return
            # A confirmed node with any live alternative below it has closed
            # nothing. This is the whole gate in one line: an explanation is not
            # established by being found, it is established by the others being
            # disposed of.
            if any(c.state in OPEN for c in node.children):
                return
            onward = [c for c in node.children if c.state is NodeState.CONFIRMED]
            if not onward:
                chains.append(tuple(path))
                return
            for child in onward:
                descend(child, path)

        descend(self.root, [])
        return chains

    def unclosed_reasons(self) -> list:
        """Every reason this traversal does not close, in the order they must be fixed."""
        reasons = []
        if self.gate1 and self.gate1.leaves_a_gap:
            for m in self.gate1.missing_inputs:
                reasons.append(f"[premise] Gate 1 returned {self.gate1.verdict} and still lacks: {m}")
        for n in self.inconclusive:
            reasons.append(f"[not ruled out] {n.hypothesis} -- {n.evidence}")
        for n in self.pending:
            reasons.append(f"[pending] {n.hypothesis} -- awaiting {n.awaiting} (as of {n.observed_at})")
        for n in self.not_visited:
            suffix = f" -- {n.not_visited_reason}" if n.not_visited_reason else ""
            reasons.append(f"[not visited] {n.hypothesis}{suffix}")
        if not self.closed_chains():
            reasons.append("[no chain] no root-to-leaf path is confirmed end to end")
        return reasons

    @property
    def is_closed(self) -> bool:
        """Gate 2's half of closure.

        Three of the four conditions live here: a confirmed chain exists, no
        decision point has a live alternative still standing, and Gate 1 left no
        gap. The fourth -- does the accounted-for magnitude add up to the
        observed effect -- is Gate 3's, and this property deliberately does not
        claim it.
        """
        return not self.unclosed_reasons()

    # -- report ------------------------------------------------------------

    def to_text(self) -> str:
        lines = [f"OBSERVATION: {self.observation}"]
        if self.gate1:
            lines.append(f"PREMISE (Gate 1): {self.gate1.verdict}")
        span = self.observation_span
        if span and span[0] != span[1]:
            lines.append(
                f"NODE STATES READ BETWEEN: {span[0].isoformat()} .. {span[1].isoformat()} "
                "-- this tree was never simultaneously true across that whole span"
            )
        lines.append("")
        lines.append("TRAVERSAL:")

        def render(node: Node, depth: int):
            pad = "  " * (depth + 1)
            lines.append(f"{pad}[{node.state.value:<12}] {node.hypothesis}")
            if node.probe:
                lines.append(f"{pad}     asked: {node.probe}")
            if node.evidence:
                lines.append(f"{pad}     got:   {node.evidence}")
            if node.awaiting:
                lines.append(f"{pad}     AWAITING: {node.awaiting} (state read {node.observed_at})")
            if node.not_visited_reason:
                lines.append(f"{pad}     NOT WALKED: {node.not_visited_reason}")
            if node.magnitude_accounted is not None:
                lines.append(f"{pad}     accounts for: {node.magnitude_accounted}")
            for child in node.children:
                render(child, depth + 1)

        render(self.root, 0)
        lines.append("")

        chains = self.closed_chains()
        if chains:
            lines.append(f"CONFIRMED CHAINS ({len(chains)}):")
            for c in chains:
                lines.append("  " + " -> ".join(n.hypothesis for n in c))
            lines.append("  A chain that closes is a path with nothing left open on it.")
            lines.append("  It is not a cause, and this skill will not call it one.")
            lines.append("")

        if self.is_closed:
            lines.append("GATE 2: no branch left open. Magnitude is Gate 3's question, not answered here.")
            return "\n".join(lines)

        lines.append("GATE 2: NOT CLOSED")
        for r in self.unclosed_reasons():
            lines.append(f"  - {r}")

        # The two movable states generate different next actions, and a report
        # that does not separate them tells the reader nothing about what to do.
        wait, walk, stuck = self.pending, self.not_visited, self.inconclusive
        if wait or walk or stuck:
            lines.append("")
            lines.append("WHAT WOULD MOVE THIS:")
            if wait:
                lines.append(f"  wait and re-run -- {len(wait)} branch(es) asked and not yet answered:")
                for n in wait:
                    lines.append(f"    - {n.hypothesis}: {n.awaiting}")
            if walk:
                lines.append(f"  go and look -- {len(walk)} branch(es) never walked:")
                for n in walk:
                    lines.append(f"    - {n.hypothesis}")
            if stuck:
                lines.append(
                    f"  neither -- {len(stuck)} branch(es) were queried and the answer settles nothing. "
                    "These need different evidence, and it may not exist:"
                )
                for n in stuck:
                    lines.append(f"    - {n.hypothesis}")
        settled = self.in_state(*SETTLED)
        if settled:
            lines.append("")
            lines.append(
                f"Work already done and still valid: {len(settled)} branch(es) settled. "
                "Being blocked at one branch does not invalidate evidence collected on another."
            )
        return "\n".join(lines)
