#!/usr/bin/env python3
"""Gate 3 -- does the explanation account for the size of the thing it explains?

An explanation that covers 8ms of a 400ms regression is not a small
explanation. It is the wrong explanation, or a fragment of the right one, and
in either case it is not something to hand to whoever is deciding what to fix.
Nothing in an ordinary investigation forces this arithmetic, so nothing catches
it. The chain reads as complete because every step in it is true.

What this gate refuses
----------------------
Both directions, because both are incoherent:

    UNDER_ACCOUNTED  the confirmed branches explain far less than what happened
    OVER_ACCOUNTED   they explain far more -- 900ms of a 400ms effect. Usually
                     double counting, occasionally a sign that the baseline is
                     wrong. Nobody checks this one, and an explanation that
                     overshoots is exactly as unusable as one that falls short

And one that is not a judgement about the system at all:

    NOT_QUANTIFIED   a confirmed branch on the chain carries no number, so the
                     arithmetic cannot run. It names the branch. This is the
                     same discipline Gate 1 applies to COULD_NOT_RUN: a gate
                     that cannot decide must say which input it lacked, or
                     "cannot decide" becomes the place everything goes to hide

Where the numbers come from
---------------------------
Only from CONFIRMED nodes, and only at one depth per branch -- both enforced by
`Node` at construction. Gate 3 does no filtering of its own on purpose: if it
had to decide which numbers to trust, it would be re-litigating Gate 2's
verdicts with less evidence.

The residual is reported whatever the verdict. A chain that accounts for 92% of
the effect has 8% nobody has explained, and that 8% is a fact about the
incident, not a rounding error to be absorbed into a pass.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from traversal import NodeState, Traversal


class Accounting(str, Enum):
    ACCOUNTED = "ACCOUNTED"
    UNDER_ACCOUNTED = "UNDER_ACCOUNTED"
    OVER_ACCOUNTED = "OVER_ACCOUNTED"
    NOT_QUANTIFIED = "NOT_QUANTIFIED"


#: Fraction of the observed effect that may remain unexplained. Not a
#: statistical bound -- a declaration of how much slack an explanation is
#: allowed before it stops being one. Stated here so a reader can disagree with
#: the number instead of guessing at it.
RESIDUAL_TOLERANCE = 0.20

#: Below this, the observed effect is too small for the ratio to mean anything
#: and the gate declines rather than dividing by something near zero. In the
#: metric's own units.
MIN_MEANINGFUL_EFFECT = 1e-9


@dataclass
class ClosureReport:
    verdict: Accounting
    observed_effect: float
    accounted: float
    contributions: list = field(default_factory=list)
    unquantified: list = field(default_factory=list)
    tolerance: float = RESIDUAL_TOLERANCE
    tolerance_reason: Optional[str] = None

    @property
    def residual(self) -> float:
        return self.observed_effect - self.accounted

    @property
    def residual_fraction(self) -> Optional[float]:
        if abs(self.observed_effect) < MIN_MEANINGFUL_EFFECT:
            return None
        return self.residual / self.observed_effect

    def to_text(self) -> str:
        lines = [
            f"MAGNITUDE: {self.verdict.value}",
            f"  observed effect   {self.observed_effect:+.2f}",
            f"  accounted for     {self.accounted:+.2f}",
        ]
        frac = self.residual_fraction
        share = f" ({frac:+.1%} of the effect)" if frac is not None else ""
        lines.append(f"  unexplained       {self.residual:+.2f}{share}")
        lines.append(f"  tolerance         {self.tolerance:.0%}")
        if self.tolerance_reason:
            lines.append(f"                    {self.tolerance_reason}")
        lines.append("")

        if self.contributions:
            lines.append("  attributed to:")
            for hypothesis, amount in self.contributions:
                lines.append(f"    {amount:+10.2f}  {hypothesis}")
            lines.append("")

        if self.verdict is Accounting.NOT_QUANTIFIED:
            if self.unquantified:
                lines.append("  The arithmetic could not run. Confirmed but carrying no number:")
                for h in self.unquantified:
                    lines.append(f"    - {h}")
                lines.append("  A branch that is true but unmeasured cannot close a magnitude.")
            else:
                lines.append("  Nothing was confirmed that claims to explain the effect, so there is")
                lines.append("  no explanation to size. This is not a measurement gap -- it is the")
                lines.append("  absence of a candidate, and Gate 2 has already said which branches")
                lines.append("  would have to move for one to exist.")
        elif self.verdict is Accounting.UNDER_ACCOUNTED:
            lines.append(f"  The confirmed branches explain {self.accounted:+.2f} of {self.observed_effect:+.2f}.")
            lines.append("  Something else did the rest, and it is not in this tree.")
        elif self.verdict is Accounting.OVER_ACCOUNTED:
            lines.append(f"  The confirmed branches explain more than happened, by {-self.residual:.2f}.")
            lines.append("  Either an effect is counted twice, or the baseline is not the right baseline.")
        else:
            lines.append("  The size of the explanation matches the size of the effect.")
            lines.append("  This is still not a cause. It is a chain that survived being checked.")
        return "\n".join(lines)


def audit_closure(traversal: Traversal, observed_effect: float,
                  measurement_uncertainty: Optional[float] = None) -> ClosureReport:
    """Run the arithmetic over the confirmed chains of a traversal.

    `observed_effect` is the thing to be explained, in the metric's own units --
    typically focus minus baseline. It is passed in rather than derived here
    because deciding what counts as the baseline is a judgement someone has to
    make and record, not one this gate should make silently.

    `measurement_uncertainty` is how much the size of that effect depends on
    which estimator measured it, as a fraction -- Gate 1's estimator_choice
    probe produces it. When it exceeds the residual tolerance, the tolerance
    widens to match, because an explanation covering 75% of an effect whose size
    is only known to within 30% has not fallen short of anything a reader could
    act on. The widening is reported, never silent: a pass at a loosened
    tolerance is a weaker claim and has to read like one.
    """
    on_chains = {n for chain in traversal.closed_chains() for n in chain}
    if not on_chains:
        # No confirmed chain: Gate 2 already says so, and running arithmetic
        # over a tree with no closed path would invent a total nobody claimed.
        on_chains = {n for n in traversal.nodes() if n.state is NodeState.CONFIRMED}

    contributions = [(n.hypothesis, n.magnitude_accounted)
                     for n in on_chains if n.magnitude_accounted is not None]

    # Descriptive branches are skipped: a branch that restates the observation
    # has no number to be missing, and counting its absence as a gap would make
    # every tree containing one report NOT_QUANTIFIED regardless of the
    # incident. The gap this looks for is a branch that claims to explain
    # something and was never measured.
    unquantified = sorted(n.hypothesis for n in on_chains
                          if n.magnitude_accounted is None and n.is_leaf and n.explanatory)

    tolerance, reason = RESIDUAL_TOLERANCE, None
    if measurement_uncertainty is not None and measurement_uncertainty > RESIDUAL_TOLERANCE:
        tolerance = measurement_uncertainty
        reason = (f"widened from {RESIDUAL_TOLERANCE:.0%} because two estimators disagree about the "
                  f"size of the effect by {measurement_uncertainty:.0%}; a residual finer than the "
                  "ruler is not a finding")

    accounted = sum(a for _, a in contributions)
    report = ClosureReport(
        verdict=Accounting.NOT_QUANTIFIED,
        observed_effect=observed_effect,
        accounted=accounted,
        contributions=sorted(contributions, key=lambda c: -abs(c[1])),
        unquantified=unquantified,
        tolerance=tolerance,
        tolerance_reason=reason,
    )

    if unquantified or not contributions:
        return report

    frac = report.residual_fraction
    if frac is None:
        # The effect is ~zero. Anything attributed to it overshoots by
        # definition; nothing attributed is trivially fine.
        report.verdict = Accounting.ACCOUNTED if accounted == 0 else Accounting.OVER_ACCOUNTED
        return report

    if frac > tolerance:
        report.verdict = Accounting.UNDER_ACCOUNTED
    elif frac < -tolerance:
        report.verdict = Accounting.OVER_ACCOUNTED
    else:
        report.verdict = Accounting.ACCOUNTED
    return report


def closes(traversal: Traversal, observed_effect: float,
           measurement_uncertainty: Optional[float] = None):
    """All four closure conditions, and the only place they are asserted together.

    Gate 2 owns three (a confirmed chain, no live alternative beside it, no gap
    left by Gate 1). Gate 3 owns the fourth. Neither claims the other's, which
    is why this function exists instead of a property on either.

    Returns (closed, reasons). `closed` being True does not mean a cause was
    found. It means no step in the chain is unsupported, no alternative to it is
    still standing, the premise was cleared, and the sizes match. The skill
    still declines to name a cause, because the thing that would license that
    claim -- knowing the counterfactual -- is not in the logs.
    """
    reasons = list(traversal.unclosed_reasons())
    magnitude = audit_closure(traversal, observed_effect, measurement_uncertainty)
    if magnitude.verdict is not Accounting.ACCOUNTED:
        reasons.append(f"[magnitude] {magnitude.verdict.value}: "
                       f"{magnitude.accounted:+.2f} accounted of {magnitude.observed_effect:+.2f} observed")
    return (not reasons), reasons
