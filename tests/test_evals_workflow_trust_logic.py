"""Tests for the trust/trigger logic in .github/workflows/evals.yml.

GitHub Actions `if:` expressions can't be executed directly outside a
workflow run, so this file mirrors the exact boolean expression from
evals.yml's `evals` job as a Python function and tests it. If the
condition in evals.yml changes, `evals_should_run` below must be kept
in sync.
"""

import pytest


def evals_should_run(
    event_name,
    review_state=None,
    review_commit_id=None,
    pr_head_sha=None,
    is_trusted_reviewer="false",
):
    """Mirrors evals.yml's `evals` job `if:` condition:

        event_name != 'pull_request_review'
        || (review.state == 'approved'
            && review.commit_id == pull_request.head.sha
            && check-reviewer.outputs.is-trusted-reviewer == 'true')

    push, schedule, and workflow_dispatch are not pull_request_review
    events, so they always run. pull_request_review only unblocks the
    job when: the review is an approval, submitted against the PR's
    current head commit, AND the reviewer's login appears in
    .github/CODEOWNERS — anyone can submit an "Approve" review on a
    public repo, so state == 'approved' alone is not sufficient.
    """
    return event_name != "pull_request_review" or (
        review_state == "approved"
        and review_commit_id == pr_head_sha
        and is_trusted_reviewer == "true"
    )


@pytest.mark.parametrize("event_name", ["push", "schedule", "workflow_dispatch"])
def test_non_review_events_always_run(event_name):
    assert evals_should_run(event_name=event_name) is True


def test_approved_review_by_trusted_reviewer_unblocks_run():
    assert (
        evals_should_run(
            event_name="pull_request_review",
            review_state="approved",
            review_commit_id="sha123",
            pr_head_sha="sha123",
            is_trusted_reviewer="true",
        )
        is True
    )


def test_approved_review_by_untrusted_reviewer_is_blocked():
    """Anyone can submit an Approve review on a public repo — an
    approval alone must not be enough."""
    assert (
        evals_should_run(
            event_name="pull_request_review",
            review_state="approved",
            review_commit_id="sha123",
            pr_head_sha="sha123",
            is_trusted_reviewer="false",
        )
        is False
    )


def test_approved_review_on_stale_commit_is_blocked():
    """A push after approval must invalidate the earlier review."""
    assert (
        evals_should_run(
            event_name="pull_request_review",
            review_state="approved",
            review_commit_id="sha123",
            pr_head_sha="sha456",  # PR moved on after the review
            is_trusted_reviewer="true",
        )
        is False
    )


@pytest.mark.parametrize(
    "review_state", ["commented", "changes_requested", "dismissed"]
)
def test_non_approving_review_is_blocked(review_state):
    assert (
        evals_should_run(
            event_name="pull_request_review",
            review_state=review_state,
            review_commit_id="sha123",
            pr_head_sha="sha123",
            is_trusted_reviewer="true",
        )
        is False
    )
