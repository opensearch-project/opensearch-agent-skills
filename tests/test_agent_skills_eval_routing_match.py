"""Tests for tests/evals/routing_match.py

Dependency-free: the routing eval's scoring rule, exercised on hand-written
router responses (no Bedrock, no LLM). Runs in the regular suite so a change
to how routing is scored cannot land unnoticed.
"""

import json
from pathlib import Path

from tests.evals.routing_match import KNOWN_SKILLS, routed_skill

_TESTS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# the plain case — the response names one skill
# ---------------------------------------------------------------------------

def test_names_the_only_skill_mentioned():
    assert routed_skill("ubi — this is click tracking on an existing app.") == "ubi"


def test_no_skill_named_is_none():
    assert routed_skill("I'd need to know more about your cluster first.") is None
    assert routed_skill("") is None


def test_match_is_case_insensitive():
    assert routed_skill("Use UBI for this.") == "ubi"
    assert routed_skill("Log-Analytics handles that.") == "log-analytics"


def test_backticks_and_punctuation_do_not_block_the_match():
    assert routed_skill("**Skill:** `ubi`") == "ubi"
    assert routed_skill("Route to search/ubi, which owns behaviour capture.") == "ubi"


def test_a_spaced_name_still_counts_as_the_skill():
    # Models often write the name in prose rather than as a slug.
    assert routed_skill("This belongs to log analytics.") == "log-analytics"
    assert routed_skill("Use managed ingestion service for that.") == "managed-ingestion-service"


def test_a_name_split_across_whitespace_still_counts():
    # Wrapped prose and double spaces separate the words by more than one char.
    assert routed_skill("this is log\nanalytics work") == "log-analytics"
    assert routed_skill("this is log  analytics work") == "log-analytics"
    assert routed_skill("this is log_analytics work") == "log-analytics"


# ---------------------------------------------------------------------------
# first mention wins — the defect this module exists to fix
# ---------------------------------------------------------------------------

def test_a_wrong_route_that_merely_mentions_the_right_skill_does_not_count():
    # The old substring check passed this as a correct `ubi` route.
    response = "log-analytics — this is a logging question, not a UBI one."
    assert routed_skill(response) == "log-analytics"


def test_a_correct_route_that_mentions_a_neighbour_still_counts():
    response = "ubi — behaviour capture. Search quality tuning would be opensearch-launchpad."
    assert routed_skill(response) == "ubi"


def test_first_of_several_names_wins():
    response = "aiven-setup, not aws-setup, because the user named Aiven."
    assert routed_skill(response) == "aiven-setup"


def test_the_recorded_false_pass_from_the_last_run():
    # Verbatim from test-out/eval-results-raw.json of the previous routing run,
    # where the old substring rule recorded routed_correctly=true for a case
    # expecting log-analytics. The model chose trace-analytics.
    response = (
        "**trace-analytics**\n\n"
        "This request is asking about error rates for a specific service (payment "
        "service) over time, which is a classic observability/monitoring use case.\n\n"
        "While log-analytics could also handle error analysis, the framing of \"error "
        "rate for my payment service\" suggests the user wants service-level metrics "
        "and tracing data, which is the primary domain of trace-analytics."
    )
    assert routed_skill(response) == "trace-analytics"


# ---------------------------------------------------------------------------
# `ubi` is three letters — the substring trap the rename created
# ---------------------------------------------------------------------------

def test_ubi_does_not_match_inside_a_longer_word():
    assert routed_skill("The ubiquitous approach here is opensearch-launchpad.") == "opensearch-launchpad"
    assert routed_skill("That claim is dubious; use trace-analytics.") == "trace-analytics"


def test_ubi_does_not_match_across_a_hyphen_or_underscore():
    # "non-ubi" is prose that routes somewhere else. Matching it would recreate
    # the false pass this module exists to remove.
    assert routed_skill("This is a non-ubi question, use log-analytics.") == "log-analytics"
    assert routed_skill("Read my_ubi_field with log-analytics.") == "log-analytics"


# ---------------------------------------------------------------------------
# the known-skill list is the fixture's list
# ---------------------------------------------------------------------------

def test_known_skills_covers_every_expected_skill_in_the_fixture():
    fixture = json.loads(
        (_TESTS_DIR / "evals" / "fixtures" / "routing.json").read_text(encoding="utf-8")
    )
    expected = {case["expected_skill"] for case in fixture}
    assert expected <= set(KNOWN_SKILLS), f"fixture names skills the matcher cannot see: {expected - set(KNOWN_SKILLS)}"


def test_every_known_skill_matches_its_own_name():
    for name in KNOWN_SKILLS:
        assert routed_skill(name) == name
