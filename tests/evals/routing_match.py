"""Scoring rule for the routing eval: which skill did the router actually name?

Kept out of conftest.py so the regular (non-LLM) suite can import and test it.

The rule is *first mention wins*. A plain substring test scores "log-analytics —
this is a logging question, not a UBI one" as a correct route to `ubi`, which
inflates accuracy for exactly the cases that were meant to fence two skills
apart. Reading the first skill the response names measures the routing decision
instead of the vocabulary.
"""

import re

# Every skill the top-level router can name. A skill missing from here reads as
# "no skill named", which fails cases that should have passed — so the fixture's
# expected skills are held against this list by a test in the regular suite.
KNOWN_SKILLS = (
    "opensearch-launchpad",
    "ubi",
    "log-analytics",
    "trace-analytics",
    "aws-setup",
    "aiven-setup",
    "document-processing",
    "managed-ingestion-service",
)


def _pattern(skill: str) -> re.Pattern:
    """Match a skill name as a whole token, hyphenated, underscored or spaced.

    The boundaries exclude `-` and `_` as well as alphanumerics, so the
    three-letter `ubi` matches "UBI" and "`ubi`" but neither "ubiquitous" nor
    "non-ubi" — the latter being prose that routes somewhere else.
    """
    body = r"[-_\s]+".join(re.escape(part) for part in skill.split("-"))
    return re.compile(rf"(?<![a-z0-9_-]){body}(?![a-z0-9_-])", re.IGNORECASE)


_PATTERNS = {skill: _pattern(skill) for skill in KNOWN_SKILLS}


def routed_skill(response: str) -> str | None:
    """Return the first skill the response names, or None if it names none."""
    hits = []
    for skill, pattern in _PATTERNS.items():
        match = pattern.search(response)
        if match:
            hits.append((match.start(), skill))
    if not hits:
        return None
    return min(hits)[1]
