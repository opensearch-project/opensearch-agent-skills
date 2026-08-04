"""The layer that builds a tree out of an index.

Everything else in `tests/` judges a tree that was handed to it. This file
covers the part that produces one, which until now had no test at all: a change
to it went red nowhere.

Two things are faked, and it is worth being precise about which:

- **the transport.** `_percentiles` and `_terms` are replaced with functions
  that return the shapes OpenSearch returns. That covers the decision logic --
  which state a node lands in, what evidence it records, whether a number is
  carried -- and covers it deterministically, which a live cluster does not
- **the neighbouring layers.** For the `assemble` tests, Gate 1 and the node
  builders are stubbed so the assembly rules themselves are what is being read

Neither substitutes for running against a real index, and neither is asked to:
that is what `eval/run_eval.py` does, against a cluster, with the answers known
in advance. A stub written by the same hand as the code it stands in for can
agree with a bug. Two independent checks that both have to pass is the point.
"""

import math
import random

import pytest

import assemble_traversal as at
from premise_audit import Observation, Provenance
from traversal import NodeState


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------

def clean_observation(**overrides):
    """An observation on which every refutation attempt runs and every one fails."""
    base = dict(
        metric="latency_ms", focus_value=450.0, baseline_value=90.0,
        focus_value_alt=440.0, baseline_value_alt=92.0,
        estimator="tdigest", estimator_alt="hdr",
        provenance=Provenance.EXTERNAL_REPORT,
        window_start="2026-08-02T14:20:00Z", window_end="2026-08-02T14:30:00Z",
        reported_at="2026-08-02T14:30:00Z",
        focus_count=200, baseline_typical_count=200,
        focus_composition={"/api/checkout": 0.25, "/api/search": 0.75},
        baseline_composition={"/api/checkout": 0.25, "/api/search": 0.75},
        focus_ingest_lag_p50_s=2.0, baseline_ingest_lag_p50_s=2.0,
        second_clock_field="ingested_at",
        resolved_indices=["logs-000001"], metric_field_types={"logs-000001": "float"},
    )
    base.update(overrides)
    return Observation(**base)


@pytest.fixture
def stub_observation(monkeypatch):
    def install(obs):
        monkeypatch.setattr(at, "build_observation",
                            lambda *a, **k: (obs, {"start": obs.window_start}))
    return install


# --------------------------------------------------------------------------
# The shape reading
# --------------------------------------------------------------------------

def test_a_median_that_moved_with_the_tail_is_confirmed_and_still_explains_nothing(monkeypatch):
    # p50 90 -> 200 while p99 moved 400: the median carries 27% of it.
    def fake(endpoint, index, query, metric, percents):
        return {"50.0": 200.0, "99.0": 490.0} if query == "FOCUS" else {"50.0": 90.0, "99.0": 90.0}
    monkeypatch.setattr(at, "_percentiles", fake)

    node, median_rise = at._shape_node("e", "i", "latency_ms", "FOCUS", "BASE", 400.0)
    assert node.state is NodeState.CONFIRMED
    assert median_rise == pytest.approx(110.0)
    # A restatement of the observation may never carry the effect, or the chain
    # closes on "it got slower because it got slower".
    assert node.explanatory is False
    assert node.magnitude_accounted is None


def test_a_median_that_held_is_ruled_out_as_a_tail_only_event(monkeypatch):
    def fake(endpoint, index, query, metric, percents):
        return {"50.0": 92.0, "99.0": 490.0} if query == "FOCUS" else {"50.0": 90.0, "99.0": 90.0}
    monkeypatch.setattr(at, "_percentiles", fake)

    node, median_rise = at._shape_node("e", "i", "latency_ms", "FOCUS", "BASE", 400.0)
    assert node.state is NodeState.RULED_OUT
    assert median_rise == pytest.approx(2.0)


def test_an_empty_percentile_is_inconclusive_not_zero(monkeypatch):
    monkeypatch.setattr(at, "_percentiles", lambda *a, **k: {"50.0": None, "99.0": None})
    node, median_rise = at._shape_node("e", "i", "latency_ms", "FOCUS", "BASE", 400.0)
    assert node.state is NodeState.INCONCLUSIVE
    assert median_rise is None


# --------------------------------------------------------------------------
# The concentration probe
# --------------------------------------------------------------------------

def sample_from(groups, seed=7):
    """Documents for one window: {endpoint: (count, median_latency)}."""
    rng = random.Random(seed)
    rows = []
    for value, (n, median) in groups.items():
        for _ in range(n):
            rows.append({"latency_ms": round(rng.lognormvariate(math.log(median), 0.6), 2),
                         "endpoint": value})
    return rows


def _concentration(monkeypatch, sample, removal_p99=None, focus_p99=900.0, truncated=False,
                   baseline=None):
    monkeypatch.setattr(at, "_percentiles", lambda *a, **k: {"99.0": removal_p99})
    return at._concentration_node("e", "i", "endpoint", "the rise is confined to one endpoint",
                                  "latency_ms", {"q": 1}, focus_p99, sample, truncated,
                                  baseline)


def test_a_dimension_with_one_value_cannot_separate_anything(monkeypatch):
    value, node = _concentration(monkeypatch, sample_from({"storefront": (200, 300.0)}))
    assert value is None
    assert node.state is NodeState.INCONCLUSIVE
    assert "only one value present" in node.evidence


def test_subgroups_too_small_to_compare_are_declined_and_named(monkeypatch):
    # Answering here would report subgroup size while appearing to report
    # concentration -- Gate 1's population_shift confound, one gate up.
    value, node = _concentration(monkeypatch, sample_from({"/a": (5, 900.0), "/b": (4, 90.0)}))
    assert value is None
    assert node.state is NodeState.INCONCLUSIVE
    assert "n=5 vs 4" in node.evidence


def test_a_concentration_beyond_the_null_is_confirmed_and_sized_by_removal(monkeypatch):
    value, node = _concentration(monkeypatch,
                                 sample_from({"/a": (50, 600.0), "/b": (150, 80.0)}),
                                 removal_p99=550.0, focus_p99=900.0)
    assert value == "/a"
    assert node.state is NodeState.CONFIRMED
    assert node.magnitude_accounted == pytest.approx(350.0)
    assert "removing it takes the window down by" in node.evidence


def test_a_concentration_that_cannot_be_sized_is_confirmed_without_a_number(monkeypatch):
    # Gate 3 must see NOT_QUANTIFIED here, not a silent zero: "nobody measured
    # this" and "this contributed nothing" are different statements.
    value, node = _concentration(monkeypatch,
                                 sample_from({"/a": (50, 600.0), "/b": (150, 80.0)}),
                                 removal_p99=None)
    assert value == "/a"
    assert node.state is NodeState.CONFIRMED
    assert node.magnitude_accounted is None


def test_one_distribution_under_four_labels_does_not_confirm_anything(monkeypatch):
    # Nothing is concentrated. Whatever gap appears is the gap the labels
    # produce by chance, so it cannot be extreme among those same gaps.
    value, node = _concentration(monkeypatch, sample_from({f"/{c}": (50, 80.0) for c in "abcd"}))
    assert value is None
    assert node.state in (NodeState.RULED_OUT, NodeState.INCONCLUSIVE)
    assert "Redrawing each group" in node.evidence


def test_a_window_whose_median_barely_moved_no_longer_manufactures_a_finding(monkeypatch):
    # The regression this fix exists for. The old probe divided the subgroup gap
    # by the window's own median rise; when that rise was itself noise, any
    # wobble became a large share and got CONFIRMED on an index where nothing
    # happened -- 3 runs in 5, measured. No median rise reaches this probe now.
    for seed in (3, 11, 29, 41, 57):
        value, node = _concentration(
            monkeypatch, sample_from({f"/{c}": (50, 80.0) for c in "abcd"}, seed=seed))
        assert node.state is not NodeState.CONFIRMED, f"confirmed nothing-happened at seed {seed}"
        assert value is None


def test_the_evidence_shows_the_null_it_was_judged_against(monkeypatch):
    _, node = _concentration(monkeypatch, sample_from({"/a": (50, 130.0), "/b": (150, 80.0)}))
    for fragment in ("has median", "Redrawing each group", "p="):
        assert fragment in node.evidence


def test_a_truncated_sample_says_so_rather_than_implying_a_whole_window(monkeypatch):
    _, node = _concentration(monkeypatch, sample_from({"/a": (50, 600.0), "/b": (150, 80.0)}),
                             removal_p99=550.0, truncated=True)
    assert "not on the window" in node.evidence


def test_a_subgroup_that_was_always_slower_is_not_confirmed_as_a_concentration(monkeypatch):
    # The same window read twice: once with the baseline that says `/a` has
    # always run at 600, once without it. The gap is identical in both. Only the
    # second one is entitled to call it a concentration, and before the baseline
    # was read the probe called it one every time.
    focus = sample_from({"/a": (50, 900.0), "/b": (150, 380.0)}, seed=11)
    normal = sample_from({"/a": (400, 600.0), "/b": (1200, 80.0)}, seed=12)

    value, node = _concentration(monkeypatch, focus, removal_p99=550.0, baseline=normal)
    assert value is None
    assert node.state is not NodeState.CONFIRMED
    assert node.magnitude_accounted is None
    assert "from its own level outside this window" in node.evidence

    blind, blind_node = _concentration(monkeypatch, focus, removal_p99=550.0)
    assert blind == "/a" and blind_node.state is NodeState.CONFIRMED


def test_a_dimension_whose_values_have_no_history_says_so(monkeypatch):
    # Nothing in the baseline to measure either value against, so there is no
    # normal to subtract and nothing that can be called a change. Declining is
    # the answer; a gap reported as a change would be the whole defect back.
    value, node = _concentration(monkeypatch, sample_from({"/a": (50, 600.0), "/b": (150, 80.0)}),
                                 baseline=sample_from({"/a": (4, 600.0), "/b": (4, 80.0)}))
    assert value is None
    assert node.state is NodeState.INCONCLUSIVE
    assert "what it normally runs at" in node.evidence


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def test_an_artifact_premise_builds_no_tree_at_all(monkeypatch, stub_observation):
    # The refusal is structural, not cosmetic. A traversal that gets built and
    # then merely goes unprinted is one refactor away from being printed.
    stub_observation(clean_observation(window_start=None, window_end=None))

    def explode(*a, **k):
        raise AssertionError("Gate 2 walked a hypothesis space below an artifact")

    monkeypatch.setattr(at, "_shape_node", explode)
    monkeypatch.setattr(at, "_concentration_node", explode)

    run = at.assemble("e", "i", "latency_ms", "@timestamp", "endpoint", 10, 6)
    assert run.premise.verdict.value == "ARTIFACT"
    assert run.traversal is None
    assert run.concentrations == ()


def _stub_nodes(monkeypatch, per_dim):
    """Replace the node builders with a scripted answer per dimension."""
    monkeypatch.setattr(at, "_sample", lambda *a, **k: ([], False))
    monkeypatch.setattr(at, "_shape_node", lambda *a, **k: (
        at.Node("the whole distribution moved, not just the tail", NodeState.RULED_OUT,
                probe="compared p50 and p99", evidence="the median held", explanatory=False),
        50.0))
    monkeypatch.setattr(at, "_concentration_node",
                        lambda endpoint, index, dim, *a, **k: per_dim[dim])


#: The real statements, so a stub cannot pass a test the shipped wording would
#: fail. A fake that invents its own phrasing is checking itself.
STATEMENTS = dict(at.CONCENTRATION_DIMENSIONS)


def _confirmed(dim, value, magnitude):
    return (value, at.Node(f"{STATEMENTS[dim]} ({dim}={value})",
                           NodeState.CONFIRMED, probe="compared medians",
                           evidence="stubbed", magnitude_accounted=magnitude))


def _ruled_out(dim):
    return (None, at.Node(STATEMENTS[dim], NodeState.RULED_OUT,
                          probe="compared medians", evidence="stubbed"))


def test_every_declared_hypothesis_appears_whether_or_not_it_was_probed(
        monkeypatch, stub_observation):
    # NOT_VISITED means nothing against a space assembled as the tool went. The
    # catalog is fixed, so the unanswerable branches have to be in the tree.
    stub_observation(clean_observation())
    _stub_nodes(monkeypatch, {d: _ruled_out(d) for d, _ in at.CONCENTRATION_DIMENSIONS})

    run = at.assemble("e", "i", "latency_ms", "@timestamp", "endpoint", 10, 6)
    hypotheses = [n.hypothesis for n in run.traversal.nodes()]
    for _, statement in at.CONCENTRATION_DIMENSIONS:
        assert any(h.startswith(statement) for h in hypotheses)

    # With no external source pointed at, every one of them is still unwalked --
    # and still present. Naming a branch you cannot answer is the point.
    unwalked = run.traversal.not_visited
    assert len(unwalked) == len(at.EXTERNAL_HYPOTHESES)
    for node in unwalked:
        assert node.not_visited_reason, "an unwalked branch has to say what it would need"


def test_only_the_strongest_dimension_keeps_its_number(monkeypatch, stub_observation):
    # Two dimensions that each isolate the window may be isolating the same
    # documents from two angles. Summing them would explain the effect twice.
    stub_observation(clean_observation())
    _stub_nodes(monkeypatch, {
        "endpoint": _confirmed("endpoint", "/api/checkout", 300.0),
        "region": _confirmed("region", "us-east-1", 120.0),
        "service": _ruled_out("service"),
        "status": _ruled_out("status"),
    })

    run = at.assemble("e", "i", "latency_ms", "@timestamp", "endpoint", 10, 6)
    carriers = [n for n in run.traversal.nodes() if n.magnitude_accounted is not None]
    assert [n.magnitude_accounted for n in carriers] == [300.0]

    weaker = [n for n in run.traversal.nodes() if "us-east-1" in n.hypothesis]
    assert weaker[0].state is NodeState.INCONCLUSIVE
    assert "may be the same documents seen from two angles" in weaker[0].evidence


def test_a_downgraded_dimension_is_not_reported_as_a_finding(monkeypatch, stub_observation):
    # `concentrations` is what a grader reads instead of parsing prose. It has
    # to reflect the state after the single-carrier rule, never before it --
    # otherwise the tool gets credit for a confirmation it withdrew.
    stub_observation(clean_observation())
    _stub_nodes(monkeypatch, {
        "endpoint": _confirmed("endpoint", "/api/checkout", 300.0),
        "region": _confirmed("region", "us-east-1", 120.0),
        "service": _ruled_out("service"),
        "status": _ruled_out("status"),
    })

    run = at.assemble("e", "i", "latency_ms", "@timestamp", "endpoint", 10, 6)
    assert run.concentrations == (("endpoint", "/api/checkout"),)


def test_the_observation_travels_with_the_run(monkeypatch, stub_observation):
    # Without it a grader has to re-query for the numbers the run already read,
    # and would then be scoring a second measurement against the first.
    obs = clean_observation()
    stub_observation(obs)
    _stub_nodes(monkeypatch, {d: _ruled_out(d) for d, _ in at.CONCENTRATION_DIMENSIONS})

    run = at.assemble("e", "i", "latency_ms", "@timestamp", "endpoint", 10, 6)
    assert run.observation is obs
    assert run.observed_effect == pytest.approx(360.0)
    assert run.uncertainty == pytest.approx(abs(360.0 - 348.0) / 360.0)


def test_the_sampler_drops_documents_missing_the_metric(monkeypatch):
    """Downstream reads `r[metric]` without a guard, which an automated review
    flagged as a KeyError. The guard exists -- it lives one stage up, in the
    sampler that builds the rows -- so this pins where it lives: a document
    carrying the dimension but not the metric never reaches the value lists."""
    hits = [
        {"_source": {"latency_ms": 100.0, "endpoint": "/a"}},
        {"_source": {"endpoint": "/b"}},                       # metric absent
        {"_source": {"latency_ms": 250.0, "endpoint": "/c"}},
    ]

    def fake(endpoint, path, body=None):
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}}

    monkeypatch.setattr(at, "_request", fake)
    rows, truncated = at._sample("http://c", "i", {"match_all": {}},
                                 "latency_ms", ("endpoint",))
    assert [r["latency_ms"] for r in rows] == [100.0, 250.0]
    assert all("latency_ms" in r for r in rows)
    # And the drop is not silent: a document the sampler could not use counts
    # toward the window's total, so the sample reports itself as truncated.
    assert truncated is True


def test_an_empty_baseline_read_refuses_instead_of_answering_blind(monkeypatch):
    """baseline=[] is a read that happened and found nothing -- different from
    baseline=None, where no baseline exists to read. The blind gap-question is
    only available when there is genuinely no baseline; an empty read names
    the groups it could not normalize and declines."""
    value, node = _concentration(monkeypatch, sample_from({"/a": (50, 600.0), "/b": (150, 80.0)}),
                                 removal_p99=550.0, baseline=[])
    assert value is None
    assert node.state is NodeState.INCONCLUSIVE
    assert "baseline n=0" in node.evidence
