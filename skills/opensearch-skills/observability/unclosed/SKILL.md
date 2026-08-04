---
name: unclosed
description: >
  Audit the premise of a log-based incident before investigating its cause, and
  record the full derivation tree instead of asserting a root cause. Use this
  skill when someone reports that a service got slower, error rates rose, a
  metric spiked, or an incident needs a root cause -- especially when the claim
  comes from a dashboard, an alert, or another agent rather than from direct
  measurement. Activate even if the user says latency spike, p99 regression,
  error rate jump, root cause analysis, RCA, postmortem, incident investigation,
  why is this slow, what caused this, or blameless retro without mentioning
  OpenSearch. Use this BEFORE log-analytics when the question is "is this real
  and what would prove it", and log-analytics when the question is already
  "query the logs for X".
compatibility: >
  Requires a running OpenSearch cluster, with or without the security plugin:
  HTTPS, basic auth and a private CA are all supported, and the password is read
  from $OPENSEARCH_PASSWORD rather than argv. PPL queries require the SQL plugin
  (built-in). No paid, proprietary, or license-restricted dependencies --
  Python standard library only.
metadata:
  author: simpleciki
  version: "0.1"
---

# unclosed

Root-cause analysis for logs that audits its own premise and refuses to name a
cause it cannot close.

> **Hackathon entry.** All three gates are implemented, mutation-verified —
> 65 load-bearing rules each deliberately broken, 0 undetected — and run end to
> end against live clusters with and without the security plugin. Captured runs
> are indexed in [evidence.md](evidence.md); the full harness is in the
> [development repository](https://github.com/simpleciki/unclosed).
> Known limits are measured and stated rather than left to be discovered.

## The problem this addresses

An investigation agent pointed at logs tends to fail in three separate ways:

1. **The premise is never tried.** "p99 spiked at 14:20" is accepted as fact.
   But a spike can be an artifact of the measurement rather than the system --
   and an artifact looks exactly like an incident in a percentile chart.
2. **The search runs one way and stops early.** The agent follows the direction
   the question implies and halts at the first plausible correlate. What it
   found was *a* related signal; what it reports is *the* cause.
3. **The chain never has to close.** An explanation that accounts for 8ms of a
   400ms regression is not an explanation, but nothing forces that arithmetic.

## The contract

**Logs cannot establish causation.** If this skill emitted "the cause is X", it
would be committing the error it exists to catch.

So it never does. The output is the traversal itself:

- which steps have evidence, and what that evidence was
- how much of the observed effect is actually accounted for
- which alternative explanations were checked and not ruled out
- **which branches were never explored** -- recorded explicitly, not skipped
  silently

An investigation that does not close is reported as **not closed**, naming the
missing link. That is a successful run.

## Boundaries

- **Read-only.** This skill never writes to OpenSearch.
- **Does not replace [log-analytics](../log-analytics/SKILL.md).** It runs
  *before* it. log-analytics answers "query the logs for X"; `unclosed` answers
  "is X real, and what would it take to prove it".
- **Reuses [`ppl-reference.md`](../ppl-reference.md)** rather than restating PPL
  syntax.
- **Publishes its own miss rate.**
  [miss-rate.txt](https://github.com/simpleciki/unclosed/blob/main/examples/miss-rate.txt)
  reports what this skill fails to catch, measured against a corpus whose truth
  is known because it was generated — including a case with no discoverable
  cause, a detection floor for the concentration probe, and a defect the
  evaluation found in the skill itself. [evidence.md](evidence.md) carries every
  measured limit.

## Gates

| Gate | Question | Status |
|---|---|---|
| 1 | Is the reported observation real, or an artifact of how it was measured? | implemented |
| 2 | What is the hypothesis space, and which branches were actually traversed? | implemented |
| 3 | Does the accounted-for magnitude add up to the observed effect? | implemented |

### Gate 1

Every check is an **attempt to refute** the observation by telling a specific
story in which nothing actually got worse. An attempt returns `REFUTED`,
`NOT_REFUTED`, or `COULD_NOT_RUN` -- and `COULD_NOT_RUN` must name the input it
lacked, which the constructor enforces.

| Verdict | Requires |
|---|---|
| `ARTIFACT` | any single attempt refuted it. Finding the artifact does not require finishing the sweep |
| `SUBSTANTIATED` | every attempt ran **and** every one failed. A pass is an optimistic claim, safe only because something pessimistic verified it -- the record *is* the pass |
| `UNDECIDABLE` | nothing refuted it, but a line of attack was unavailable. Not knocked down is not the same as cleared |

This precedence makes `UNDECIDABLE` unreachable by mere uncertainty: it needs a
probe that wanted a *nameable* input which was absent. "I am not sure" cannot
produce it.

**The auditor must not author the premise.** Three of the eight attempts examine
the claim rather than the system, because every dataset has a maximum and a tool
that selects its own worst bucket will always find one:

- a report that names **no moment** is `ARTIFACT`, not an open question. Nothing
  can contradict it, so nothing can support it -- and the remedy is the
  reporter, not more data
- a **self-selected** window can never be `SUBSTANTIATED`. It can still be
  refuted: discovering an artifact does not depend on the window having been
  named in advance
- an external report with **no report timestamp** is an unbacked claim. The
  timestamp is what makes provenance checkable rather than typed
- a window **judged before it finished** is an artifact: the reporter and the
  auditor are looking at two different datasets that share a name

**A window judged early is refuted for comparability, and that is the whole of
what it means.** The refutation says the auditor and the reporter are not
holding the same documents. It does not say the reporter's *number* was wrong —
and that is the next sentence every narration wants to write. Left open, it gets
written either way: in the agent evaluation two runs of this skill rebuilt the
same 46-document slice by hand and read different statistics off it. p99 came
back 77% above the settled value and the run called the report untrustworthy;
p50 came back equal to it and the run called the report fine. Both numbers were
real, both runs had read this file, and nothing in it said which reading answers
the question.

So it is computed rather than chosen downstream: **the same statistic the claim
is about**, over the documents an ingest clock places before the report time,
printed in that probe's evidence beside the settled value. Both readings then
exist *in the report* — which is what the narration guard demands of any number
that appears in prose, so a percentile queried by hand afterwards is not in the
report and does not pass.

What the reconstruction is not: what the alert saw. A refresh interval, the
alert's own query lag, and a shard that had not caught up all sit between ingest
order and that screen. It is the closest the index can come, and it is labelled
as that. Where the index carries one clock the reconstruction cannot be done at
all, and the report says the gap is **unquantified** — which is not a synonym for
small.

It never moves the verdict. A reconstruction that happens to match the settled
value does not make two datasets one dataset, and a probe clearable by a
coincidence would be an escape hatch reachable by luck.

**And the range the auditor swept is part of the claim too.** Those four ask who
chose the *focus* window. One question sits outside them: who chose the six
hours it was selected from. The obvious answer — `now - lookback .. now` — hangs
the tool's own premise on an input nobody records, and the agent evaluation hit
both halves of the cost:

- the same command against the same **static** index selected a different focus
  window when it ran a few minutes later. Nothing about the system had changed
- `now` does not land on a bucket boundary, so the left edge cut through the
  oldest bucket and returned the share of it that fell to the right of the cut.
  Read whole, that bucket was n=200 with a p99 *below* baseline; read sliced, it
  was small enough for `sample_size_collapse` to refute the observation on volume
  the query itself had removed

So the range hangs on `--as-of` when a caller names a moment and otherwise on the
newest document in the index — never on the wall clock — and both edges snap
outward to bucket boundaries, so every bucket returned is queried whole. What is
still partial after that is partial in the *data*, which is a fact about the
system and may be judged as one. The resolved range and the clock that fixed it
are printed on the report: a reader cannot otherwise tell whether re-running the
command would examine the same buckets. Captured in
[window-anchor.txt](https://github.com/simpleciki/unclosed/blob/main/examples/window-anchor.txt).

This is recorded rather than probed. By the time any attempt sees an observation
the range has already been chosen, so there is nothing left for a refutation to
bite on — the fix has to be that the choice is reproducible, not that a ninth
probe complains about it afterwards.

**And the ruler is part of the claim.** A percentile from an aggregation is not
a measurement of the data, it is an estimate computed from it, and which
estimator produced it is a choice almost nobody records. The eighth attempt asks
the same window with a second one — `tdigest` and `hdr`, both core to every
OpenSearch distribution, both sub-aggregations of the same request, so neither a
dependency nor an extra round trip.

This is not hypothetical. On this project's fixtures the default estimator reads
**+0.14% to +21.75%** above the true value at n=200, and on the negative control
that error decides *which bucket is selected as the incident* — it picks one
whose true p99 is lower than another's. A single-estimator reading cannot be
separated from the method that produced it, so it may not substantiate anything.

The two kinds of disagreement are not the same finding:

- **about existence** — one ruler sees a 5x jump and the other sees nothing. The
  jump belongs to the ruler, and that is a refutation
- **about size** — both see it, sized differently. Not grounds to discard the
  observation; grounds to stop claiming a precision nobody has. The divergence is
  handed to Gate 3 rather than absorbed

Measured on the fixtures: 2% at n=3, 8% on the real spike, and **11% on the
negative control** — the smaller the effect, the larger the share of it that is
ruler.

### Gate 2

Gate 1 asked whether the observation is real. This gate asks what was actually
looked at on the way to explaining it — and records every branch that was named
and never walked.

A branch is not bought-or-not. Five states divide on **two independent axes**,
and collapsing them into one loses a fact that the reader needs:

| State | Re-running moves it? | Branch disposed of? | Next action |
|---|---|---|---|
| `CONFIRMED` | no | yes | — |
| `RULED_OUT` | no | yes | — |
| `INCONCLUSIVE` | no | **no** | needs different evidence, which may not exist |
| `PENDING` | **yes** | no | wait, then re-run |
| `NOT_VISITED` | **yes** | no | go and look |

The first axis decides **what to do next**; the second decides **whether a chain
may close**. `INCONCLUSIVE` is the only state on both — finished work, branch
still standing — and it is the state that can make a chain *permanently*
unclosable. That case is not a defect. It is the honest answer, and the
evaluation contains one.

A confirmed branch closes nothing while an alternative to it is still standing.
That is the whole gate in one sentence: an explanation is not established by
being found, it is established by the others being disposed of. Reporting the
first plausible correlate is what this looks like when the alternatives are
invisible.

**`PENDING` is guarded, or it becomes the escape hatch** that Gate 1's verdict
precedence exists to close — anything inconvenient gets labelled "not answered
yet" and the tree never has to close. So it must name **what it awaits** and
**the moment its state was read**, and the constructor enforces both. A pending
branch with no timestamp is a claim about a present that has already passed.

**An unverified premise travels with the tree.** An `UNDECIDABLE` verdict from
Gate 1 does not stop the traversal — the branches below are still worth walking
and the evidence found there is still real. But Gate 1's missing inputs are
carried on the tree and keep it open, because otherwise every node can close and
the report reads as complete while resting on a premise nobody checked.

Closure therefore takes four conditions, and this gate owns three:

1. a root-to-leaf path exists on which every node is `CONFIRMED`
2. no decision point on it has a live alternative still standing
3. Gate 1 left no unresolved gap
4. the accounted-for magnitude adds up to the observed effect — **Gate 3's**, and
   Gate 2 deliberately does not claim it

A chain that satisfies all of them is reported as *a path with nothing left open
on it*. It is not a cause, and this skill will not call it one.

Evidence collected on one branch is never invalidated by another branch being
blocked. A traversal that discarded finished work whenever something else was
open would make an incomplete run indistinguishable from a run that found
nothing — which is most runs.

### Gate 3

An explanation that covers 8ms of a 400ms regression is not a small
explanation. It is the wrong one, or a fragment of the right one. Gate 2 passes
it — every step is true and every alternative is disposed of — so only the
arithmetic catches it.

| Verdict | Means |
|---|---|
| `ACCOUNTED` | the size of the explanation matches the size of the effect |
| `UNDER_ACCOUNTED` | the confirmed branches explain far less than what happened |
| `OVER_ACCOUNTED` | they explain far **more** — usually double counting, sometimes a wrong baseline |
| `NOT_QUANTIFIED` | a confirmed branch carries no number, so the arithmetic cannot run. It names the branch |

`OVER_ACCOUNTED` exists because an explanation that overshoots is exactly as
unusable as one that falls short, and nothing in an ordinary investigation looks
for it.

`NOT_QUANTIFIED` is the same discipline Gate 1 applies to `COULD_NOT_RUN`: a
gate that cannot decide must say which input it lacked, or "cannot decide"
becomes the place everything goes to hide. It also blocks the quiet substitution
that this gate is most likely to make — **treating an unmeasured branch as
contributing zero**, which turns "nobody measured this" into "this contributed
nothing", an assertion no one made.

**No double counting, enforced by shape.** "The deploy accounts for 380ms" and
"the query plan under it accounts for 380ms" are one 380ms described at two
depths; summed, they explain 760ms of a 400ms effect. A node whose descendants
already account for magnitude may not account for it too, and the constructor
refuses to build one — so the arithmetic is impossible to write rather than
merely discouraged.

**The residual is always reported**, whatever the verdict. A chain accounting
for 92% of the effect leaves 8% nobody has explained. That is a fact about the
incident, not a rounding error to be absorbed into a pass.

**The tolerance cannot be finer than the ruler.** Gate 1's estimator probe hands
down how much the effect's size depends on which estimator measured it. When
that exceeds the residual tolerance, the tolerance widens to match: an
explanation covering 75% of an effect known only to within 30% has not fallen
short of anything a reader could act on. The widening is printed with its
reason — a pass at a loosened tolerance is a weaker claim and has to read like
one, or the report launders imprecision into agreement.

Gate 3 does no filtering of its own: magnitude may only come from `CONFIRMED`
nodes, and that is enforced upstream at construction. If this gate decided which
numbers to trust, it would be re-litigating Gate 2's verdicts with less evidence
than Gate 2 had.

`closes()` is the only place all four conditions are asserted together. A tree
that satisfies all four is reported as a chain that survived being checked — and
still not as a cause, because the thing that would license that claim, knowing
the counterfactual, is not in the logs.

## Connecting to a cluster

Both entry points take the same connection flags, because the deployment you are
pointed at is almost never the one with security switched off:

| Flag | Why |
|---|---|
| `--endpoint` | Defaults to `http://127.0.0.1:9250`. Deliberately not `9200` — relying on the default is how a hardcoded endpoint gets into the code. |
| `--username` | Basic auth. The **password is read from `$OPENSEARCH_PASSWORD`** and is not accepted on the command line: argv is readable by other processes on the host, and lands in shell history besides. `$OPENSEARCH_USERNAME` also works. |
| `--ca-cert` | PEM bundle to verify the cluster's certificate against. |
| `--insecure` | Skip certificate verification. |

TLS is decided by the scheme, not by a separate flag. Every report prints a
`TRANSPORT:` line naming the endpoint, whether the certificate was verified and
against what, and whether credentials were used — for the same reason the scan
window records which clock chose it. **A run that skipped verification and did
not say so leaves no way to tell whether the cluster reached is the cluster
named**, and `--insecure` is exactly the flag someone sets once and forgets.

Failures are sentences. No credentials, `http` against a TLS port, and an
untrusted certificate each name what to do about them instead of raising a
traceback, because those three are what a user meets before they ever meet a
verdict.

The portability of this is checked rather than asserted: `eval/vendor_neutrality.py`
runs the same audit against a plaintext cluster and a security-enabled one,
seeded identically and pinned to the same `--as-of`, and diffs the two reports.
The only line that may differ is `TRANSPORT:`.

## Building the tree from an index

`assemble_traversal.py` runs Gate 1, and if the premise survives, walks a
hypothesis space against the index and hands the result to Gates 2 and 3.

**The hypothesis space is declared, not discovered.** `NOT_VISITED` means
nothing against a space the tool assembled as it went — "I explored everything I
thought of" is complete only with respect to what it happened to think of. So
the catalog is fixed, every entry appears in the tree whether or not it was
probed, and hypotheses this index *cannot* answer (a deploy landed, an upstream
dependency slowed, the host lost resources) are recorded as unwalked with the
data that would be needed named. On a request-log index those three are the
usual answer, and saying so is more use than a confident tour of the four
questions the logs can answer.

**Unanswerable by this index is not unanswerable.** Most clusters carrying
request logs also carry deploy events, dependency latencies and node metrics — in
*other* indices, which is a different statement from "not available". Point
`--change-events`, `--dependency` or `--host-metrics` at one and that branch is
walked like any other; leave it and the branch stays unwalked and the chain stays
open. An earlier version appended all three NOT_VISITED unconditionally, and on a
cluster that did carry deploy events the printed reason — *needs deploy/change
events* — was false. The events existed and the tool had not looked.

An event branch is ruled out only where the source was recording: an index
holding no events anywhere in the scanned span cannot separate *none happened*
from *none are logged here*, so it declines instead. A series branch asks whether
its median in the focus bucket sits outside the range every other bucket
occupied — non-parametric on purpose, since a fitted threshold here would be a
constant fitted to the data it grades, which this project has already had to
remove once. That rule carries its own false-confirm rate of about 2/37 on a
36-bucket scan, for the same reason reading the highest bar in a chart does.

**Concentration is asked on the median, and that choice is the probe.** Two
wrong ways to ask whether the rise lives in one endpoint or region, both of
which report sample size while looking like they report concentration:

- *remove the value and re-measure the window* — taking 198 of 200 documents out
  moves p99 whatever those documents were
- *compare the value's own p99 to the rest's* — a p99 estimated on n=49 is noisy
  and biased high. On this project's fixtures the aggregation reads **+0.14% to
  +21.75%** above the true value at n=200, and smaller subgroups are worse

Both are Gate 1's `population_shift` confound rebuilt one gate up. The median
survives estimation at these sizes.

**And each value is measured against its own normal, not against the rest.** A
checkout path that writes to a database is slower than a health check in every
window, including the quiet ones. Asked whether its median exceeds the rest's,
the answer is yes, today and every day — so before anything is compared, every
latency has its own group's median from *outside* the focus window subtracted
from it. What is left is how far that group has moved from where it normally
sits. A gap that was always there subtracts out; a gap that is new does not.
Without this step the probe reports *this subgroup is slow* while appearing to
report *this subgroup got slow*, and the evaluation measured it doing exactly
that in 5 runs of 5. A value with too little history to establish a normal is
dropped and named rather than compared against a borrowed one.

**And the change is judged against a null, not a threshold.** Some value always
moved most, so the question is never whether a change exists but whether this one
is larger than a quiet window produces by accident. The window is redrawn a few
hundred times with every group held at one common level, each redraw yielding a
largest-subgroup-change; together they are the distribution of that statistic
when nothing is concentrated, at these subgroup sizes and on this data's own
spread. A change in the top 5% of that distribution is confirmed; one at its
middle is the dimension being ruled out; between them is *elevated, not
established*.

Each group is redrawn **from its own latencies**. Shuffling the labels over the
pooled ones is simpler and was tried first, but it gives every group the average
spread — and a slow subgroup varies more in milliseconds for the same reason it
is slow, so the widest group ends up judged against variation that is not its
own. The null also has to be a null of the **maximum**, because the probe reports
the largest change among several values; comparing a maximum against the null of
a single comparison fires on the most extreme of four groups far more often than
the declared rate, which is the same error as reading the highest bucket in a
chart as though someone had nominated it in advance.

The first version of this was a constant: the gap had to reach 50% of the
window's own median rise. Noise between medians scales with the spread of the
data, so a fixed share is too strict at one scale and too lax at another; the
evaluation caught it being both. Once a concentration stands out from the null,
removal is a fair way to *size* it.

### Known limits

Every limit is measured rather than estimated, and lives in
[evidence.md](evidence.md) with the captured run that produced each figure. The
headlines, because a reader deciding whether to trust a verdict needs them
before deciding to open a second file:

- **Detection floor**: reliable concentration detection begins at a true share
  of **68%** of the window's own median rise; below that the probe reports
  *elevated, not established* and the concentration is missed
- **Per-dimension alpha**: the 5% false-confirmation rate is per dimension and
  four are tested, so a run carries roughly an **18%** chance of confirming
  something somewhere when nothing is concentrated anywhere
- **`IMMATERIAL` closes chains, and only for measured branches**: a branch too
  small to rival the effect (bar = Gate 3's own tolerance) stops blocking
  closure — 0 of 11 runs closed before it, 7 of 11 after, 0 of 11 controls. A
  branch nobody could measure never earns it
- **A multiplicative rise will still read as concentrated** — the one limit
  that is **stated and not measured**; no corpus case tests it
- **Two estimators are not a confidence interval**: their divergence fails to
  cover the primary estimator's actual error in 21 of 35 runs, and the
  narration guard refuses the vocabulary that would imply otherwise

## Reporting a run

Nothing here calls a model. The agent reading this already is one, and that is
the last place the refusal can be undone: three gates spend their whole design
declining to name a cause, and then the summary that reaches a human puts one
back. The final step is the one step this skill does not control.

So it is checked rather than trusted. After writing a summary of a run, pass it
through the guard before showing it to anyone:

```bash
python scripts/provenance_guard.py --report run.txt --narration summary.txt
```

Two rules, and the first is not a matter of taste:

**Every number in the summary must already appear in the report.** Not derivable
from it — present in it. A ratio computed while writing the sentence is exactly
where a fabricated figure hides, and it is indistinguishable from a real one
because it is formatted identically and sits inside a true statement. Rounding
to fewer decimals is fine; stating a number more finely than it was measured is
not. If a derived figure is worth reporting, the derivation belongs in a gate,
where it is tested, mutation-verified, and printed with its inputs.

**Three phrasings are refused**, because each contradicts the report being
summarised: naming a cause, asserting closure when the chain did not close, and
calling the two-estimator divergence a confidence interval or a margin of error.

The numeric half is exact — a number is either in the report or it is not. The
phrasing half is lexical: a floor under the obvious failure, not a proof, and
the guard says so rather than issuing a clean bill of health.

## Evaluation

`eval/` generates indices whose truth is known because it made them, runs all
three gates over each, and scores the answers — misses and false alarms counted
separately and never averaged, several seeds per case because one draw cannot
distinguish a rule that holds from noise that fell kindly. The report ends with
what the evaluation **cannot** see, printed as prominently as the rates. Details
and the reproduce command are in [evidence.md](evidence.md).

## Development fixtures

`scripts/seed_logs.py` generates three scenarios against a local cluster:

| Scenario | Volume in the anomalous bucket | What it is |
|---|---|---|
| `baseline` | normal throughout | negative control -- nothing to find |
| `real-spike` | unchanged (n=200) | genuine regression: the distribution moved |
| `fake-spike` | collapsed (n=3) | artifact: p99 over almost no data |

Both spike scenarios produce a ~5x p99 jump over the same baseline. A threshold
on the ratio alone cannot separate them; a test asserts they stay confusable, so
the gate is never graded against a strawman.
