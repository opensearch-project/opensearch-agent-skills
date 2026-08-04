#!/usr/bin/env python3
"""The translation layer, and the check on it.

Nothing in this skill talks to a model. The host agent reading it already is
one, which is the whole problem: three gates spend their entire design refusing
to name a cause, and then a language model renders the report into prose and
puts the cause back. The refusal has to survive the last step, and the last step
is the one component this repository does not control.

So it is checked instead of trusted.

    python provenance_guard.py --report run.txt --narration summary.txt

Exit status is 0 when the narration is grounded and 1 when it is not, so an
agent can run it on its own output before showing that output to anyone.

The rule
--------
**Every number in the narration must already appear in the report.** Not
derivable from it -- present in it. A ratio the narration computes on its own is
exactly where a fabricated figure hides, and it is indistinguishable from a real
one at a glance because it is formatted identically and sits in a true sentence.

Rounding down to fewer decimals is allowed: a narration saying 451 where the
report says 451.37 has lost precision, not invented any. Gaining precision is
refused, because a number stated more finely than it was measured is a claim
nobody made.

This is deliberately strict, and the strictness is the feature. If a derived
figure is worth reporting, the derivation belongs in the gates -- where it is
tested, mutation-verified, and printed with the inputs that produced it -- not
in a sentence generated once and checked by nobody. Every time this guard
rejects a useful number, the fix is to compute it upstream.

The other rule
--------------
Three phrasings are refused outright, because each contradicts something the
report itself says:

- naming a cause. Logs cannot establish causation; a skill that emits "the cause
  is X" commits the error it exists to catch
- asserting closure when the report says the chain did not close
- calling the two-estimator divergence a confidence interval, a margin of error,
  or anything with the same meaning. The eighth probe rules out the effect
  belonging to one estimator. It does not bound the error -- both estimators can
  be wrong in the same direction, and on this project's own fixtures they are

What this does not do
---------------------
This half is lexical. It catches the phrasing, not the intent, and a narration
determined to imply a cause without using the word will pass. It is a floor
under the default failure, not a proof of anything, and it is reported as a
check that ran rather than as a clean bill of health.

The numeric half is not lexical and does not have that weakness: a number is
either in the report or it is not.

Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class Verdict(str, Enum):
    GROUNDED = "GROUNDED"
    UNSOURCED = "UNSOURCED"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"


#: Whole timestamps, checked as units. Decomposing one into 2026, 8, 2, 14, 20
#: would ask the report to contain five integers it has no reason to contain,
#: and would then report five fabrications where there are none.
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)?")

#: Numbers, with the thousands separators a model tends to add back in and the
#: percent sign kept, because whether a figure was written as 13% or 0.13 is
#: what decides if the two are the same claim.
#:
#: The lookbehind excludes a digit glued to a letter. `p99` and `p50` are the
#: names of the quantities being discussed, not assertions about them, and
#: demanding the report contain the integer 99 would flag the most ordinary
#: sentence a narration can write.
NUMBER = re.compile(r"(?<![A-Za-z\d])-?\d[\d,]*(?:\.\d+)?%?")

#: List markers and headings. Formatting, not claims about the incident.
LIST_MARKER = re.compile(r"^\s*(?:[-*]\s*)?\(?\d+[.)]\s+")

#: Phrases that assert what this skill contractually will not assert.
CAUSE_CLAIMS = (
    r"\b(?:the\s+)?root\s+cause\s+(?:is|was|:)",
    r"\bthe\s+cause\s+(?:is|was|:)",
    r"\bcaused\s+by\b",
    r"\bis\s+responsible\s+for\b",
    r"\bto\s+blame\b",
    r"\bthe\s+culprit\b",
)

#: Phrases that assert closure. Only refused when the report says otherwise --
#: a report that did close is entitled to be narrated as one.
CLOSURE_CLAIMS = (
    r"\bfully\s+explain(?:s|ed)?\b",
    r"\bcompletely\s+account(?:s|ed)?\s+for\b",
    r"\bcase\s+closed\b",
    r"\bwe\s+now\s+know\s+why\b",
    r"\bthe\s+answer\s+is\b",
    r"\bmystery\s+solved\b",
    r"\bconfirms?\s+the\s+cause\b",
)

#: Refused always. SKILL.md states in as many words that two estimators are not
#: a confidence interval, so a narration calling their divergence one is
#: contradicting the document it is narrating.
PRECISION_CLAIMS = (
    r"\bconfidence\s+interval\b",
    r"\bmargin\s+of\s+error\b",
    r"\berror\s+bars?\b",
    r"\b95%\s+confident\b",
    r"\bwithin\s+error\b",
    r"\bstatistically\s+significant\b",
)

CLOSED_MARKER = "ALL FOUR CONDITIONS: closed"


def report_says_closed(report: str) -> bool:
    return CLOSED_MARKER in report


def _strip_markers(text: str) -> str:
    return "\n".join(LIST_MARKER.sub("", line) for line in text.splitlines())


def timestamps(text: str) -> set:
    return set(TIMESTAMP.findall(text))


def numbers(text: str) -> list:
    """Numeric tokens, with timestamps and list markers removed first.

    Returns the tokens as written rather than as floats: a token is what has to
    be shown to a reader when it turns out to be unsourced, and 0.50 and .5 are
    the same value but not the same claim about precision.
    """
    without_time = TIMESTAMP.sub(" ", _strip_markers(text))
    return NUMBER.findall(without_time)


def _value(token: str) -> Optional[float]:
    try:
        return float(token.rstrip("%").replace(",", ""))
    except ValueError:
        return None


def _decimals(token: str) -> int:
    return len(token.rstrip("%").split(".")[1]) if "." in token else 0


def _parsed(tokens):
    """(value, was_written_as_a_percentage) for each token that parses."""
    out = []
    for tok in tokens:
        value = _value(tok)
        if value is not None:
            out.append((value, tok.endswith("%")))
    return out


def _grounded(token: str, pool) -> bool:
    """Is this token a report number, or a rounding of one?

    Rounding to *fewer* decimals passes -- precision was lost, not invented.
    Rounding to more does not, because a number stated more finely than it was
    measured is a claim nobody made.

    The hundredfold rescaling is allowed only when exactly one side carries a
    percent sign. Reports print 0.13 and 13% for the same quantity and a
    narration picking the other rendering has not changed the number -- but
    allowing the rescaling unconditionally would pass any invented figure that
    happened to land a factor of a hundred from a real one, which is a hole
    wide enough to walk a fabricated total through.
    """
    want = _value(token)
    if want is None:
        return False
    places = _decimals(token)
    want_pct = token.endswith("%")
    for value, was_pct in pool:
        options = [value]
        if want_pct != was_pct:
            options += [value * 100.0, value / 100.0]
        for option in options:
            if round(option, places) == round(want, places):
                return True
    return False


@dataclass
class GuardReport:
    verdict: Verdict
    unsourced_numbers: list = field(default_factory=list)
    unsourced_timestamps: list = field(default_factory=list)
    contract_violations: list = field(default_factory=list)
    checked_numbers: int = 0

    def to_text(self) -> str:
        lines = [f"NARRATION CHECK: {self.verdict.value}",
                 f"  numbers checked against the report: {self.checked_numbers}"]
        if self.unsourced_numbers:
            lines.append("")
            lines.append("  NOT IN THE REPORT -- these figures were produced by the narration:")
            for tok in self.unsourced_numbers:
                lines.append(f"    {tok}")
            lines.append("  A number the gates did not compute has not been tested, mutation-")
            lines.append("  verified, or printed with its inputs. Compute it upstream or drop it.")
        if self.unsourced_timestamps:
            lines.append("")
            lines.append("  MOMENTS NOT IN THE REPORT:")
            for tok in self.unsourced_timestamps:
                lines.append(f"    {tok}")
            lines.append("  A window or report time the run never mentioned is a claim about")
            lines.append("  when something happened that nothing in the run supports.")
        if self.contract_violations:
            lines.append("")
            lines.append("  CONTRACT:")
            for kind, phrase in self.contract_violations:
                lines.append(f"    [{kind}] {phrase!r}")
        lines.append("")
        if self.verdict is Verdict.GROUNDED:
            lines.append("  Every figure in the narration appears in the report, and no refused")
            lines.append("  phrasing was found. The numeric half of that is exact. The phrasing")
            lines.append("  half is lexical: it catches the default failure, not a determined one.")
        return "\n".join(lines)


def check(report: str, narration: str, closed: Optional[bool] = None) -> GuardReport:
    """Check a narration against the report it claims to summarise."""
    if closed is None:
        closed = report_says_closed(report)

    pool = _parsed(numbers(report))
    narrated = numbers(narration)
    unsourced = [t for t in narrated if not _grounded(t, pool)]

    report_moments = timestamps(report)
    unsourced_moments = sorted(t for t in timestamps(narration) if t not in report_moments)

    violations = []
    lowered = narration.lower()
    for pattern in CAUSE_CLAIMS:
        for m in re.finditer(pattern, lowered):
            violations.append(("names a cause", m.group(0).strip()))
    for pattern in PRECISION_CLAIMS:
        for m in re.finditer(pattern, lowered):
            violations.append(("claims a precision nobody measured", m.group(0).strip()))
    if not closed:
        for pattern in CLOSURE_CLAIMS:
            for m in re.finditer(pattern, lowered):
                violations.append(("asserts closure the report denies", m.group(0).strip()))

    if violations:
        verdict = Verdict.CONTRACT_VIOLATION
    elif unsourced or unsourced_moments:
        verdict = Verdict.UNSOURCED
    else:
        verdict = Verdict.GROUNDED

    # First-seen order without list.index: index() rescans per element and
    # raises if a token ever arrives from anywhere but `narrated`.
    deduped = []
    for tok in unsourced:
        if tok not in deduped:
            deduped.append(tok)

    return GuardReport(
        verdict=verdict,
        unsourced_numbers=deduped,
        unsourced_timestamps=unsourced_moments,
        contract_violations=violations,
        checked_numbers=len(narrated),
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check an agent's narration against the gate report it summarises.")
    ap.add_argument("--report", required=True, help="File holding the three gates' output")
    ap.add_argument("--narration", required=True, help="File holding the summary to check")
    args = ap.parse_args()

    report = Path(args.report).read_text(encoding="utf-8")
    narration = Path(args.narration).read_text(encoding="utf-8")
    result = check(report, narration)
    print(result.to_text())
    return 0 if result.verdict is Verdict.GROUNDED else 1


if __name__ == "__main__":
    sys.exit(main())
