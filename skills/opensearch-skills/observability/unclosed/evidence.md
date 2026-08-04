# unclosed — measured limits and evaluation

Reference file for [SKILL.md](SKILL.md). Everything here is **measured rather
than estimated** — each figure names the captured run that produced it, and the
one limit that is stated without measurement says so in bold. The captures live
in the development repository, because the skill directory ships judgment and
this file ships the evidence for it:

| Capture | What it shows |
|---|---|
| [miss-rate.txt](https://github.com/simpleciki/unclosed/blob/main/examples/miss-rate.txt) | The evaluation: 8 cases x 5 seeds + a 35-run sweep, misses and false alarms counted separately |
| [gates-on-real-data.txt](https://github.com/simpleciki/unclosed/blob/main/examples/gates-on-real-data.txt) | All three gates end to end against a live 2.19.3 cluster, five runs |
| [window-anchor.txt](https://github.com/simpleciki/unclosed/blob/main/examples/window-anchor.txt) | The wall-clock anchor defect reproduced, and the fix holding |
| [closure-ceiling.txt](https://github.com/simpleciki/unclosed/blob/main/examples/closure-ceiling.txt) | Why chains could never close, in four measured stages |
| [agent-ab.txt](https://github.com/simpleciki/unclosed/blob/main/examples/agent-ab.txt) | The skill against not having it: 18 runs, and the headline did not favor the skill |
| [mutation-verification.txt](https://github.com/simpleciki/unclosed/blob/main/examples/mutation-verification.txt) | 69 load-bearing rules each broken on purpose; 0 survived undetected |
| [vendor-neutrality.txt](https://github.com/simpleciki/unclosed/blob/main/examples/vendor-neutrality.txt) | The same audit on a security-off and a security-on cluster, reports diffed |

## Known limits

**The concentration probe is under-powered, and was made more so on purpose.**
Reliable detection begins at a true concentration of **68% of the window's own
median rise**, measured across a graded sweep with five independently generated
datasets at each strength. Below that, a genuine concentration is reported as
*elevated, not established*: at 47% it is found in 2 runs of 5, at 24% in 1, and
at 14% in none. The 47% rung was found in 4 of 5 by an earlier null that shuffled
group labels; that null also confirmed a concentration that did not exist, and
the power was given up to stop it. A miss costs a finding; a false confirmation
costs the reason to believe the findings that remain.

**A branch is judged against the effect it would have to explain, and not only
against chance.** The null answers *is this larger than noise*. Closure asks *is
any rival account still standing*, which is a question about size — and for a
long time the two were never connected. A subgroup gap of 13ms sat in the upper
half of its own null while the rise being explained was 1900ms, so it read as
`INCONCLUSIVE` and kept the chain open. Against chance it is elevated; against
the thing it would have to account for it is **0.7%** of it, and no confidence
about a 0.7% wobble makes it a rival.

The cost of not asking was total: **0 of 11 runs closed**, because three innocent
dimensions each had to land in the lower half of their own null by luck — 0.5³ ≈
12.5% at best, and 12 of 33 measured. Closure was a constant, and a gate that
never opens is a wall.

`IMMATERIAL` is the state for a branch that was **measured** and is too small to
be the answer. The bar is Gate 3's own `RESIDUAL_TOLERANCE`, widened the same way
when the two estimators disagree — not a new constant, and deliberately the same
one used to accept an explanation, so nothing can be too small to be an answer
and large enough to block one. With it, on the same pre-registered runs:
**7 of 11 closed, 0 of 11 controls.** See
[closure-ceiling.txt](https://github.com/simpleciki/unclosed/blob/main/examples/closure-ceiling.txt).

It is not a softer `INCONCLUSIVE` and not a quiet `RULED_OUT`:

| | says |
|---|---|
| `INCONCLUSIVE` | we could not establish whether the effect lives here |
| `IMMATERIAL` | we measured how big this is, and it is too small to be where it lives |
| `RULED_OUT` | it sits at the middle of its null; this is what noise does |

**A branch nobody could measure never becomes `IMMATERIAL`.** *Too small to
matter* is a finding, not something to say when you did not look — a dimension
with one value present, or too few documents to compare, stays `INCONCLUSIVE` and
still blocks. That rule is the one that keeps this state from being the escape
hatch the rest of the design exists to refuse, and it is where the mutation
verification aims.

The alternative considered and **not** taken was redefining `RULED_OUT` as *not
distinguishable from the null* (p > alpha). Measured the same way it closed 4 of
8 — worse — and it contradicts this project's own rule that failing to knock
something down is not the same as clearing it. The four runs that still do not
close now fail on **magnitude**, which is Gate 3 working: one is genuinely
under-accounted at 71% of its effect, and the others report `NOT_QUANTIFIED`
because a confirmed branch carried no number. An event index can say a deploy
landed and cannot say how many milliseconds it explains, so a run where a deploy
really did land in the window still cannot close. That is not obviously wrong — a
strong lead you cannot size *is* an open chain — and it is left as it stands.

**A rise that is multiplicative rather than additive will still read as
concentrated.** Each group's normal is subtracted in milliseconds, because the
observation being explained is in milliseconds. If everything genuinely doubles,
a slow subgroup gains more absolute milliseconds than a fast one and this probe
will call that a concentration. No case in the corpus tests it, so unlike every
other figure here this limit is **stated and not measured**.

**A group that varies far more than the rest is judged more loosely.** The null
redraws each group from its own latencies, and that spread is estimated from one
window — around 50 documents in these fixtures. The wider a group is relative to
the others, the noisier both the statistic and its threshold become. The fixture
covering this runs one endpoint about six times slower than the rest before the
rise, and is clean in 5 runs of 5; nothing measures what happens further out.

**The 5% is per dimension and four are tested**, so a run carries roughly an 18%
chance of confirming something somewhere when nothing is concentrated anywhere.
This is the source of every false confirmation left in the corpus.

Two earlier versions of the concentration probe were caught by the same harness.
The first used a constant instead of a null — the excess had to reach 50% of the
window's own median rise — and failed in both directions at once, including
confirming a concentration on an index where nothing had happened in 3 runs of
5. The second had a null but no baseline, so it asked whether a gap was larger
than chance produces and never whether the gap was *new*: on a fixture where one
endpoint is permanently slower and everything then rises by the same amount, it
confirmed a concentration in **5 runs of 5**. Both are now measured at 5 of 5
correct.

**Two estimators are not a confidence interval.** The eighth probe establishes
that the reading is not an artifact of one particular method. It does not bound
the error — both estimators can be wrong in the same direction, and on these
fixtures they are. Measured: the divergence between the two rulers fails to
cover `tdigest`'s actual distance from the exact value in **21 of 35** runs, most
sharply where `tdigest` reads 75% high while the two rulers differ by 43%. What
the probe rules out is the failure where the whole effect belongs to the
estimator. What it does not provide is a measurement uncertainty — and the
narration guard refuses the vocabulary that would imply otherwise.

## Evaluation

`eval/` generates indices whose truth is known because it made them, runs all
three gates over each, and scores the answers. Misses and false alarms are
counted separately and never averaged: this skill's position is that it would
rather miss than claim, and one accuracy figure would hide the trade.

```bash
python eval/run_eval.py --out examples/miss-rate.txt
```

Each case is run against several independently generated datasets. One draw
cannot distinguish a rule that holds from noise that fell kindly — and the
over-claim documented above appears in roughly half of runs, which a single-draw
evaluation reports as a clean sweep.

The report's last section is what the evaluation **cannot** see, printed always
and printed as prominently as the rates. Every case here is generated, indexed,
audited once and deleted, so no index is ever read twice or at a moment it did
not choose — and a defect that only appears between runs cannot land in any
category, including the ones printed as zero. The wall-clock window anchor was
exactly that defect: found by an agent run that read one index at two moments,
and scored a clean sweep by this harness on both sides of the fix. Seeds vary
the data; nothing here varies the clock. A category reading 0 because nothing
triggered it is indistinguishable from one reading 0 because nothing could, so
the gap is named rather than left to be rediscovered.

## Against not having it

The most honest number in this file is the one that did not favor the skill.
An 18-run A/B — same model, same cluster, same incidents, with and without the
skill — found the unaided arm fabricated nothing on the cases the corpus can
score: six of six correct either way. The measured difference was phrasing (2 of
9 unaided runs used language the narration guard refuses; 0 of 9 aided) and the
experiment surfaced six defects, two of them in this skill. Full runs, verbatim,
including the ones that make the skill look unnecessary:
[agent-ab.txt](https://github.com/simpleciki/unclosed/blob/main/examples/agent-ab.txt)
and [agent-ab-answers/](https://github.com/simpleciki/unclosed/blob/main/examples/agent-ab-answers/).
