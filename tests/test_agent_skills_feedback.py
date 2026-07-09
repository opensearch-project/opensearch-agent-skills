"""Tests for the feedback module."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "opensearch-skills" / "scripts"))

from lib.feedback import format_feedback_preview, submit_feedback


def test_format_feedback_preview_shows_all_data():
    preview = format_feedback_preview(
        feedback_type="gap",
        skill_name="opensearch-launchpad",
        context="User asked for GraphQL integration",
        comment="Would be nice to have",
    )
    assert "gap" in preview
    assert "opensearch-launchpad" in preview
    assert "GraphQL" in preview
    assert "Would be nice" in preview


def test_format_feedback_preview_shows_rating():
    preview = format_feedback_preview(
        feedback_type="success",
        skill_name="log-analytics",
        rating="4",
    )
    assert "4/5" in preview


def test_format_feedback_preview_truncates_long_context():
    preview = format_feedback_preview(
        feedback_type="failure",
        skill_name="test",
        context="a" * 300,
    )
    assert "..." in preview


def test_submit_feedback_returns_not_configured_when_empty():
    """When GOOGLE_FORM_ID is empty, returns configuration message."""
    import lib.feedback as fb
    original_id = fb.GOOGLE_FORM_ID
    fb.GOOGLE_FORM_ID = ""
    try:
        result = submit_feedback(feedback_type="success", skill_name="test")
        assert "not yet configured" in result
    finally:
        fb.GOOGLE_FORM_ID = original_id


def test_submit_feedback_posts_form_data(monkeypatch):
    """When configured, POSTs form-urlencoded data to Google Forms."""
    import lib.feedback as fb
    monkeypatch.setattr(fb, "GOOGLE_FORM_ID", "1FAIpQLSeFAKE")
    monkeypatch.setattr(fb, "FIELD_IDS", {
        "feedback_type": "entry.100",
        "skill_name": "entry.200",
        "context": "entry.300",
        "comment": "entry.400",
        "rating": "entry.500",
    })

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = submit_feedback(
            feedback_type="failure",
            skill_name="opensearch-launchpad",
            context="IndexNotFoundError",
        )

    assert "✓" in result
    req = mock_urlopen.call_args[0][0]
    assert "entry.100=Failure" in req.data.decode()
    assert "entry.200=opensearch-launchpad" in req.data.decode()
    assert "entry.300=IndexNotFoundError" in req.data.decode()


def test_submit_feedback_handles_network_error(monkeypatch):
    """Returns error message on network failure."""
    import lib.feedback as fb
    monkeypatch.setattr(fb, "GOOGLE_FORM_ID", "1FAIpQLSeFAKE")
    monkeypatch.setattr(fb, "FIELD_IDS", {
        "feedback_type": "entry.100", "skill_name": "entry.200",
        "context": "entry.300", "comment": "entry.400", "rating": "entry.500",
    })

    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = submit_feedback(feedback_type="friction", skill_name="test")

    assert "Failed" in result


def test_submit_feedback_truncates_long_context(monkeypatch):
    """Context is truncated to 2000 chars."""
    import lib.feedback as fb
    monkeypatch.setattr(fb, "GOOGLE_FORM_ID", "1FAIpQLSeFAKE")
    monkeypatch.setattr(fb, "FIELD_IDS", {
        "feedback_type": "entry.100", "skill_name": "entry.200",
        "context": "entry.300", "comment": "entry.400", "rating": "entry.500",
    })

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        submit_feedback(feedback_type="failure", skill_name="test", context="x" * 3000)

    req = mock_urlopen.call_args[0][0]
    # URL-encoded "x" is just "x", so check length of the context value
    assert "x" * 2001 not in req.data.decode()
