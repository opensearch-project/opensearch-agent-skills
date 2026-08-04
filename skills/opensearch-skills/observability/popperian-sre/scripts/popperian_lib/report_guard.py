import re
from typing import List, Tuple

class ReportGuard:
    """
    Deterministically checks a generated incident report's text against the
    three explicit constraints in SKILL.md's "Constraints & Rules" section.
    Those are currently enforced only by prompting the LLM to follow them --
    a prompted instruction is not a guaranteed one. This is the code-level
    backstop: it inspects the agent's own final written output and flags it
    if the text claims more than the deterministic gate actually established.
    """

    # SKILL.md: "Do NOT claim to prove the true root cause. You only rank the
    # candidate explanations supported by available indexed evidence."
    PROOF_CLAIM_PATTERNS = [
        re.compile(r'\bthe (root )?cause (is|was)\b'),
        re.compile(r'\bcaused by\b'),
        re.compile(r'\bis responsible for\b'),
        re.compile(r'\b(confirmed|proven|definitively)\s+(the\s+)?(root )?cause\b'),
        re.compile(r'\bwe have (confirmed|proven|established)\b'),
    ]

    # SKILL.md: "Do NOT invent a Bayesian probability percentage. Use explicit
    # evidence scoring (Score = Supporting Weight - Contradicting Weight - Missing Penalty)."
    PROBABILITY_CLAIM_PATTERN = re.compile(r'\b\d{1,3}%\s*(chance|probability|confiden(t|ce)|certain(ty)?|likely)\b')

    # SKILL.md: "Refusal is a feature. If required evidence is missing, you
    # must refuse to recommend a change" -- so when the gate refused, the
    # report must not still tell the reader what action to take.
    RECOMMENDATION_PATTERNS = [
        re.compile(r'\bwe recommend\b'),
        re.compile(r'\brecommended (fix|action|remediation)\b'),
        re.compile(r'\bnext steps?:\s'),
        re.compile(r'\bto (fix|resolve|remediate) this\b'),
    ]

    @classmethod
    def find_violations(cls, report_text: str, gate_passed: bool) -> List[str]:
        violations = []
        lower = report_text.lower()

        for pattern in cls.PROOF_CLAIM_PATTERNS:
            match = pattern.search(lower)
            if match:
                violations.append(
                    f"Report claims proof (matched {match.group(0)!r}), but this system only "
                    "ranks candidate explanations by evidence score -- it never proves a cause."
                )

        if cls.PROBABILITY_CLAIM_PATTERN.search(lower):
            violations.append(
                "Report invents a Bayesian-style confidence percentage; SKILL.md requires "
                "explicit evidence scoring instead."
            )

        if not gate_passed:
            for pattern in cls.RECOMMENDATION_PATTERNS:
                match = pattern.search(lower)
                if match:
                    violations.append(
                        f"Sufficiency gate refused, but the report still recommends an action "
                        f"(matched {match.group(0)!r}). Refusal must mean refusal."
                    )

        return violations

    @classmethod
    def validate(cls, report_text: str, gate_passed: bool) -> Tuple[bool, List[str]]:
        violations = cls.find_violations(report_text, gate_passed)
        return (len(violations) == 0, violations)
