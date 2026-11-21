"""Branches a request log cannot answer alone, walked when something else can.

The three of them -- a deploy landed, a dependency slowed, the host lost
resources -- used to be appended NOT_VISITED unconditionally. Two things were
wrong with that, and only the first is obvious.

It made closure unreachable by construction. Any NOT_VISITED node keeps the
chain open, so the closure verdict was a constant rather than a judgement, and a
refusal that can never be lifted reports nothing. Gate 1's own rule applies to
the gate that owns it: a pass nobody can obtain is not a strict pass, it is an
absent one.

And on a cluster that *did* carry deploy events, the printed reason -- "needs
deploy/change events" -- was false. The events existed. The tool had not looked.

What is tested here is the decision, not the transport: the retrieval helpers are
stubbed so each branch's rule is read directly. Whether the queries are right is
what a live index answers, and `examples/` carries those runs.

The rule the two shapes share: **absence is only a ruling when presence was
detectable.** An empty event index and a quiet system look identical, so the
empty one declines instead of ruling out.
"""

import pytest

import assemble_traversal as at
from traversal import NodeState

FOCUS_START, FOCUS_END = "2026-08-03T03:10:00.000Z", "2026-08-03T03:20:00Z"
SCAN_START, SCAN_END = "2026-08-02T21:50:00Z", "2026-08-03T03:50:00Z"
STATEMENT, NEEDS = "a deploy or config change landed in this window", "deploy/change events"


def _event(monkeypatch, in_window, in_scan):
    calls = []

    def fake_count(endpoint, index, query):
        calls.append(query)
        return in_window if len(calls) == 1 else in_scan

    monkeypatch.setattr(at, "_count", fake_count)
    return at._event_node("e", STATEMENT, NEEDS, "deploys", "@timestamp",
                          FOCUS_START, FOCUS_END, SCAN_START, SCAN_END)


def _series(monkeypatch, buckets):
    monkeypatch.setattr(at, "_bucket_medians", lambda *a, **k: buckets)
    return at._series_node("e", "the host or container lost resources", "node metrics",
                           "nodes", "cpu_pct", "@timestamp", FOCUS_START, FOCUS_END,
                           SCAN_START, SCAN_END, 10)


def _ordinary(n=8, value=37.0):
    return [(f"bucket-{i}", value + i * 0.5) for i in range(n)]


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

def test_an_event_inside_the_window_confirms_the_branch(monkeypatch):
    node = _event(monkeypatch, in_window=2, in_scan=6)
    assert node.state is NodeState.CONFIRMED
    assert "2 event(s)" in node.evidence and "6 across the scanned span" in node.evidence


def test_no_event_in_the_window_rules_it_out_only_because_the_source_was_recording(monkeypatch):
    node = _event(monkeypatch, in_window=0, in_scan=6)
    assert node.state is NodeState.RULED_OUT
    assert "the source was recording" in node.evidence


def test_an_empty_source_declines_instead_of_ruling_anything_out(monkeypatch):
    """A quiet system and an unwired index look the same from inside the window."""
    node = _event(monkeypatch, in_window=0, in_scan=0)
    assert node.state is NodeState.NOT_VISITED
    assert "'none happened' from 'none" in node.not_visited_reason
    assert node.probe is None and node.evidence is None


# --------------------------------------------------------------------------
# Series
# --------------------------------------------------------------------------

def test_a_reading_above_everything_else_in_the_span_confirms(monkeypatch):
    node = _series(monkeypatch, _ordinary() + [(FOCUS_START, 91.2)])
    assert node.state is NodeState.CONFIRMED
    assert "outside anything it did" in node.evidence


def test_a_reading_below_everything_else_also_confirms(monkeypatch):
    """Resource loss can read as a collapse as easily as a spike."""
    node = _series(monkeypatch, _ordinary() + [(FOCUS_START, 1.0)])
    assert node.state is NodeState.CONFIRMED


def test_a_reading_inside_the_ordinary_range_rules_the_branch_out(monkeypatch):
    node = _series(monkeypatch, _ordinary() + [(FOCUS_START, 38.0)])
    assert node.state is NodeState.RULED_OUT
    assert "inside the range it occupies" in node.evidence


def test_too_little_history_declines_rather_than_inventing_a_normal(monkeypatch):
    node = _series(monkeypatch, _ordinary(n=at.MIN_BASELINE_BUCKETS - 1) + [(FOCUS_START, 91.2)])
    assert node.state is NodeState.NOT_VISITED
    assert "no ordinary range to compare against" in node.not_visited_reason


def test_a_source_with_no_reading_in_the_window_declines(monkeypatch):
    node = _series(monkeypatch, _ordinary())
    assert node.state is NodeState.NOT_VISITED
    assert "carries no `cpu_pct` reading" in node.not_visited_reason


# --------------------------------------------------------------------------
# Nothing pointed at
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kind", ["events", "series"])
def test_a_branch_with_no_source_stays_unwalked_and_names_what_it_needs(kind):
    node = at._external_node("e", "change", kind, STATEMENT, NEEDS, None, "@timestamp",
                             FOCUS_START, FOCUS_END, SCAN_START, SCAN_END, 10)
    assert node.state is NodeState.NOT_VISITED
    assert node.not_visited_reason == f"needs {NEEDS}"


def test_an_empty_external_mapping_is_the_same_as_none():
    node = at._external_node("e", "change", "events", STATEMENT, NEEDS, {}, "@timestamp",
                             FOCUS_START, FOCUS_END, SCAN_START, SCAN_END, 10)
    assert node.state is NodeState.NOT_VISITED


def test_the_catalog_still_lists_every_branch_it_cannot_answer():
    """Pointing at nothing must not shrink the declared space."""
    keys = [k for k, _, _, _ in at.EXTERNAL_HYPOTHESES]
    assert keys == ["change", "dependency", "host"] or tuple(keys) == ("change", "dependency", "host")
    for _, kind, statement, needs in at.EXTERNAL_HYPOTHESES:
        assert kind in ("events", "series")
        assert statement and needs
