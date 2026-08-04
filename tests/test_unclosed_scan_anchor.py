"""Which clock chose the window.

Gate 1 asks who chose the *focus* window and whether they chose it before or
after seeing the data. One level out sits a question it never asked: who chose
the **range that was swept** to find that window. Until this file existed the
answer was "whenever the command was typed", and two defects followed from it.

- **The verdict moved with the wall clock.** The same command against the same
  static index, run ten minutes apart, swept a different six hours. The agent
  A/B run hit this twice independently: a self-selected focus window that
  changed between runs over data that had not changed.

- **The oldest bucket was sliced by the query.** `now` does not land on a
  bucket boundary, so the left edge cut through the first bucket and returned
  whatever fraction of its documents fell to the right of the cut. Read whole
  that bucket was n=200 with a p99 *below* baseline; read sliced it was small
  enough for `sample_size_collapse` to refute the observation on volume the
  query itself had removed.

The fix is not a smaller tolerance. It is that the range is anchored on
something in the data -- the newest document, or a moment the caller names --
and both edges are snapped outward to bucket boundaries. What is still partial
after that is partial in the data, which is a fact about the system and may be
judged as one.

The wall clock is not faked here. It is simply not reachable: the anchor is put
far enough in the past that a reintroduced `datetime.now` would land the window
in the current year and fail these assertions loudly rather than drift.
"""

from datetime import datetime, timedelta, timezone

import pytest

import audit_window as aw
from premise_audit import Observation, audit

BUCKET_MIN = 10
LOOKBACK_H = 6
INTERVAL_S = BUCKET_MIN * 60

#: Mid-bucket on purpose (14:23:47 is not a 10-minute boundary), and far enough
#: in the past that no wall clock could produce it.
INDEX_MAX = datetime(2020, 3, 1, 14, 23, 47, tzinfo=timezone.utc)


class FakeCluster:
    """Answers the two shapes this module asks for, and records what it was asked."""

    def __init__(self, max_ts=INDEX_MAX):
        self.max_ts = max_ts
        self.ranges = []

    def __call__(self, endpoint, path, body=None):
        if body and "newest" in body.get("aggs", {}):
            value = None if self.max_ts is None else self.max_ts.timestamp() * 1000.0
            return {"aggregations": {"newest": {"value": value}}}
        rng = body["query"]["range"]["@timestamp"]
        self.ranges.append((rng["gte"], rng["lt"]))
        return {"aggregations": {"per_bucket": {"buckets": []}}}


@pytest.fixture
def cluster(monkeypatch):
    def install(max_ts=INDEX_MAX):
        fake = FakeCluster(max_ts)
        monkeypatch.setattr(aw, "_get", fake)
        return fake
    return install


def _resolve(as_of=None):
    return aw.resolve_scan_window("e", "logs-*", "@timestamp", BUCKET_MIN, LOOKBACK_H, as_of)


# --------------------------------------------------------------------------
# Where the range comes from
# --------------------------------------------------------------------------

def test_the_window_is_anchored_on_the_newest_document_not_on_the_wall_clock(cluster):
    cluster()
    gte, lt, anchor, source = _resolve()

    assert anchor == INDEX_MAX
    assert "newest `@timestamp`" in source
    # The load-bearing assertion: a wall clock cannot produce 2020.
    assert (gte.year, lt.year) == (2020, 2020)


def test_an_explicit_as_of_overrides_the_index_and_records_that_it_did(cluster):
    cluster()
    gte, lt, anchor, source = _resolve(as_of="2021-06-05T09:07:00Z")

    assert anchor == datetime(2021, 6, 5, 9, 7, tzinfo=timezone.utc)
    assert "--as-of" in source
    assert lt == datetime(2021, 6, 5, 9, 10, tzinfo=timezone.utc)


def test_an_index_with_no_timestamps_refuses_rather_than_falling_back_to_now(cluster):
    cluster(max_ts=None)
    with pytest.raises(SystemExit) as exc:
        _resolve()
    assert "no `@timestamp` values" in str(exc.value)


# --------------------------------------------------------------------------
# Whole buckets
# --------------------------------------------------------------------------

def test_both_edges_land_on_bucket_boundaries(cluster):
    cluster()
    gte, lt, _, _ = _resolve()

    assert lt == datetime(2020, 3, 1, 14, 30, tzinfo=timezone.utc)
    assert gte == datetime(2020, 3, 1, 8, 30, tzinfo=timezone.utc)
    assert lt - gte == timedelta(hours=LOOKBACK_H)


@pytest.mark.parametrize("offset_s", [0, 1, 59, 61, 299, 301, 599])
def test_no_anchor_offset_can_produce_an_edge_that_cuts_a_bucket(cluster, offset_s):
    """The defect was a property of *where inside a bucket* the anchor fell."""
    anchor = datetime(2020, 3, 1, 14, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_s)
    fake = cluster(max_ts=anchor)
    gte, lt, _, _ = _resolve()

    assert gte.timestamp() % INTERVAL_S == 0
    assert lt.timestamp() % INTERVAL_S == 0
    # The newest document's own bucket is inside the range, so it is read whole
    # rather than truncated at the right edge.
    assert lt >= fake.max_ts


def test_an_anchor_already_on_a_boundary_is_not_pushed_into_an_empty_bucket(cluster):
    cluster()
    _, lt, _, _ = _resolve(as_of="2021-06-05T09:10:00Z")
    assert lt == datetime(2021, 6, 5, 9, 10, tzinfo=timezone.utc)


def test_the_scan_query_asks_for_exactly_the_resolved_edges(cluster):
    """The range that was reasoned about is the range that was sent."""
    fake = cluster()
    gte, lt, _, _ = _resolve()
    aw.bucket_stats("e", "logs-*", "@timestamp", "latency_ms", BUCKET_MIN, gte, lt)

    assert fake.ranges[-1] == ("2020-03-01T08:30:00Z", "2020-03-01T14:30:00Z")


def test_the_same_index_returns_the_same_range_on_every_run(cluster):
    cluster()
    first = _resolve()[:2]
    cluster()
    assert _resolve()[:2] == first


# --------------------------------------------------------------------------
# Saying so
# --------------------------------------------------------------------------

def _observation(**overrides):
    base = dict(
        metric="latency_ms", focus_value=450.0, baseline_value=90.0,
        scan_window_start="2020-03-01T08:30:00Z", scan_window_end="2020-03-01T14:30:00Z",
        scan_anchor="2020-03-01T14:23:47Z",
        scan_anchor_source="newest `@timestamp` in logs-*",
    )
    base.update(overrides)
    return Observation(**base)


def test_the_report_says_which_clock_chose_the_window():
    text = audit(_observation()).to_text()

    assert "SCAN: 2020-03-01T08:30:00Z -> 2020-03-01T14:30:00Z" in text
    assert "newest `@timestamp` in logs-*" in text
    assert "2020-03-01T14:23:47Z" in text


def test_a_report_built_without_a_recorded_scan_says_nothing_rather_than_guessing():
    text = audit(_observation(scan_window_start=None, scan_window_end=None,
                              scan_anchor=None, scan_anchor_source=None)).to_text()
    assert "SCAN:" not in text
