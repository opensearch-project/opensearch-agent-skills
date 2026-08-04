"""Tests for the scenario seeder.

Per the OpenSearch Agent Skills DEVELOPER_GUIDE, tests must not require a
running OpenSearch cluster. Everything here exercises pure functions against
generated documents -- no network, no container.
"""

from datetime import datetime, timezone

import seed_logs


NOW = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
SEED = 20260801


def _stats(scenario):
    docs, spike_start = seed_logs.build_documents(scenario, SEED, NOW)
    return docs, seed_logs.summarize(docs, spike_start)


def test_baseline_has_no_spike_bucket():
    """The negative control must stay flat. A gate that flags everything is not a gate."""
    docs, stats = _stats("baseline")
    assert stats is None
    assert len(docs) == seed_logs.BUCKETS * seed_logs.NORMAL_VOLUME


def test_real_spike_keeps_its_volume():
    """A genuine regression: the distribution moved, the traffic did not."""
    _, stats = _stats("real-spike")
    assert stats["spike_n"] == seed_logs.NORMAL_VOLUME
    assert stats["spike_p99"] > 4 * stats["baseline_p99"]


def test_fake_spike_is_a_sample_size_collapse():
    """The artifact: p99 explodes only because almost all the data vanished."""
    _, stats = _stats("fake-spike")
    assert stats["spike_n"] == seed_logs.COLLAPSED_VOLUME
    assert stats["spike_p99"] > 4 * stats["baseline_p99"]


def test_both_spikes_look_identical_to_a_naive_percentile_read():
    """The premise of this project.

    If a naive p99-ratio read could already separate these two, there would be
    nothing for Gate 1 to do. This test is what makes the fixture honest: it
    fails the moment the scenarios stop being confusable, which would mean the
    gate is being evaluated against a strawman.
    """
    _, real = _stats("real-spike")
    _, fake = _stats("fake-spike")

    real_ratio = real["spike_p99"] / real["baseline_p99"]
    fake_ratio = fake["spike_p99"] / fake["baseline_p99"]

    assert real_ratio > 4 and fake_ratio > 4
    # Same order of magnitude: no threshold on the ratio alone can split them.
    assert 0.5 < (real_ratio / fake_ratio) < 2.0


def test_timestamps_are_utc_and_bucket_aligned():
    """Synthetic buckets must line up with span(@timestamp, 10m).

    Misaligned buckets split the collapsed bucket across two reported buckets,
    which quietly hides the very collapse the fixture exists to demonstrate.
    """
    docs, _ = _stats("fake-spike")
    for doc in docs[:50]:
        assert doc["@timestamp"].endswith("Z")


def test_seeding_is_deterministic():
    """Captured gate verdicts stay reproducible for reviewers."""
    first, _ = seed_logs.build_documents("fake-spike", SEED, NOW)
    second, _ = seed_logs.build_documents("fake-spike", SEED, NOW)
    assert first == second
