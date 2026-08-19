# Return visits: the three procedures

The bodies of the three return visits. When each runs, what every visit
requires first (the Preflight gate, `ubi-metrics-plan.md`, the
reconstruction offer), and the rule that the user's ask picks the visit are
in SKILL.md's [Return visits](../SKILL.md#return-visits) section; this file
is the procedure for the visit already chosen. The plan file is re-parsed
under the pinned format of [metrics-plan.md](metrics-plan.md). A dashboard
ask is [Step 7](../SKILL.md#step-7-dashboard), not a visit: it re-runs the
step, under [dashboards.md](dashboards.md).

The review and the extension run unchanged on the managed path: Map already
wrote each metric's query against the records that path actually produces,
and Implement already carries the branch's deltas. Only the emitter diff
reads differently — there is no `ext.ubi` to find, so the query side is the
app's own record-building code ([aws-managed.md](aws-managed.md)).

## Reviewing the metrics

**Goal:** each metric's number beside the target the room agreed, from live
data, in the conversation. Run every metric section's query from the plan
and render one row per metric: the metric, its target, the number now, and
how much data it is drawn from. Reads are free under Critical Rule 5, and a
review touches the cluster no other way — the one write it can carry is the
by-intent report's embedding model below, announced under its own contract.

**Render it goal by goal**, because that is how the ask arrives ("how are
we doing on X") and how the plan's table is organized: a goal carrying
three metrics reads as three metrics, not three unrelated numbers. Name the
headline metric and its guardrails as what they are, from the lines the
plan holds beneath its table ([metrics-plan.md](metrics-plan.md)). A
headline that improved while a guardrail degraded is the one pattern worth
pointing at — the plan recorded the pair for exactly that reading, and
saying it is arithmetic, not advice.

**The numbers are the deliverable.** That, with the drift report and the
no-click inventory below, is the whole honest content of the review. Do not
dress the numbers as insights, strategy, or a recommended next move, and do
not read a trend off a window holding minutes of data. Say how much data
there is and let the room draw the conclusion; what the team does with a
metric is theirs. A number below its target is a number, reported like any
other.

Three things are reported as words, never as figures:

- **Not yet interpretable**: a metric the stores cannot answer, with the
  missing piece named rather than substituted. That covers a store below
  the interpretability floor (no captured query, no presented ranking,
  clicks without `position.ordinal`) and the subtler case met more often:
  rows exist, but not for the searches the metric is about, so a rate
  computed from them describes a different population. A wrong number
  travels further than an absent one. Where the missing piece is the
  cluster rather than the data, name it from the grid in
  [reachability.md](reachability.md), which also says whether a version, a
  setting, or nothing at all would change the answer.
- **No data yet**: a metric whose window holds no matching events, never a
  zero. Zero is a measurement; absence is not.
- **No verdict**: a plan row parked unsettled (no agreed target) is
  reported with its number alone, because there is nothing to read it
  against.

**A plan query that errors, or that the stores contradict, was written
against a stale field name** (the reference's naming trap). Say which query
it is, what it claimed, and what the stores hold, and put the corrected
query to the user: Verify fixed such a query on the spot because Map had
just written it; here the file may carry the user's own edits, and changing
it is theirs to approve.

**The drift report reads the stores back against the plan.** Every check
from Implement through this review starts from the plan's side, so a
well-formed event type nobody declared trips none of them. The reverse read
is one `terms` aggregation on `action_name` in `ubi_events`, set against
the action names the plan's table and metric queries carry, sized past the
store's distinct values — undersized, it fabricates absence in both
directions of the comparison. Three drift classes, each reported as
arithmetic, none as a verdict:

- **Unauthored events**: an action name in the store the plan never
  declared. Name it with its row count and never call it a defect — it may
  be instrumentation the team added deliberately after the session.
  Whether it joins the plan is the room's call, through the extension
  visit's approval path, never by this review writing anything. The count
  is reported either way; why volume in this store reaches ratings for
  query-and-document pairs nobody touched is under *How much behavior is
  enough* in [judgments.md](judgments.md).
- **Dead instrumentation**: a declared action name matching no rows in the
  window the stores hold. Verify catches a row that never fired at setup;
  nothing else catches one that stopped firing since, because "no data
  yet" is said per metric and a row no metric filters on goes quiet
  unremarked. Read the plan's `Retention:` line before reading the zero as
  stopped: a short window and a dead emitter leave the same absence.
- **Type drift**: a field a plan query filters or aggregates on whose live
  mapping no longer supports it — Verify's one-time mapping read, re-run
  on the accumulated stores. The shapes to expect are in
  [ubi-schema.md](ubi-schema.md): the text-mapped custom field answering a
  `term` filter with zero hits and no error, and `dynamic: false` on
  `ubi_queries` swallowing undeclared fields.

**The no-click inventory closes the review**: the searches that ended with
no click, reported as two populations to inspect. Neither is a number to
drive down on sight — a search can end this way and have been answered
correctly, so which of them is a defect is the goals' question, not the
filter's. Abandonment is not uniformly negative (Li, Huffman and Tokuda
put good abandonment at 19-55% in web search, SIGIR 2009), and zero
results are the right answer whenever the catalog does not hold the thing.

- **Zero-result searches** are query rows whose hit-ID list is empty. An
  empty list indexes nothing, so the filter is a `must_not` on `exists`
  over `query_response_hit_ids`, never a match against an empty value.
- **Never-clicked searches** returned results nobody selected: two `terms`
  aggregations on `user_query` in `ubi_events`, one filtered to
  `impression` and one to `click`; the strings in the first list but not
  the second are the population. Size both past the store's distinct query
  strings — a click that falls outside a truncated aggregation reads as
  never having happened. Both populations exclude `user_query: ""` (the
  population entry in [ubi-schema.md](ubi-schema.md)'s failure catalog).

Rank each list by the `ubi_queries` rows its own filter matches —
zero-result rows for one, rows with hits for the other, never impression
counts, which duplicate firing inflates. A string whose searches split
lands on both lists with neither count borrowing the other's rows, and the
team reads both in order of volume.

**Each listed string gets one diagnosis, run and reported**: the user's own
text against the app's own index with the matcher loosened (`operator: or`,
`fuzziness: AUTO`, over the same fields the recorded `query` DSL shows the
app searching). Hits mean the catalog has the thing and the search did not
find it — a retrieval gap. None means it is not there to find — a catalog
gap, the search answering correctly about what it holds. That distinction
is the actionable half, and it is arithmetic, not advice; what the team
does with either answer is theirs. An app whose recorded queries already
carry the loosened form has its answer in the record: its zero-result is
the catalog speaking. The diagnosis is lexical, and stays lexical: the
question is whether the catalog holds the thing, and the loosened matcher
answers it. The evidence is an ablation from this skill's own development,
on its seven-case fixture: a semantic leg lost every case to this matcher,
and its exclusive contribution measured under 1%. Semantic search may still
earn a place in the app's own ranking — a separate change, never this
diagnosis. And the inventory reports what capture saw: a search whose query
row never landed is absent from it, not counted as answered.

**By intent, where the room has named its intents.** A plan carrying an
`## Intents` section can render the same numbers once more per intent: each
distinct query string assigned to its nearest label, and every metric
re-run with a `terms` filter over each label's strings. The procedure, the
embedding it needs, the volume gate that says when there is nothing to
spread yet, and the reading of the assignment table with the room are all
in [intent-labels.md](intent-labels.md) — as is the one cluster write a
review can carry: where the room takes the in-cluster model and none is
deployed, the register-and-deploy is a Critical Rule 5 write, announced
alone in its turn. A plan without the section means the room was never
asked: the one question comes first, and the answer is theirs, landing in
the plan on their go-ahead before anything embeds. The embedding classifies
strings for this report and nothing else; the diagnosis above stays
lexical.

**Where a scheduled check is standing, its latest run's scores are one more
row** beside the plan's numbers (the job list is a free read, so the review
reads it). The schedule itself is the team's standing choice, changed only
on their ask — the third visit's closing section owns the check,
[judgments.md](judgments.md) its contract.

The review renders in the conversation and writes nothing on its own:
neither a file copy nor a plan edit without the user asking.

## Extending the plan to a new feature

**Goal:** a newly shipped feature ends up captured under the same contract
as everything else — through approval, never by writing quietly.

The visit starts in the conversation, not the repository: the goal
question for the new rows and the proposed mapping need only the plan and
what the user has shown, and never wait on code access. Diff the plan
against what is instrumented — the emitters the app's code actually
carries against the rows the plan claims — from the code where it is in
reach, from what the user supplied where it is not, naming what a fuller
read would still check. Drift runs both ways and both are said out loud: an app action with no plan row
(usually the new feature, sometimes an event someone added without
recording why), and a plan row with no emitter (an unfinished setting, or
code that was removed).

New rows are **proposed**, and pass through
[Step 4: Map](../SKILL.md#step-4-map) exactly as first-run rows do, under
every row practice Map pins. A new feature serving a goal the table does
not hold gets the goal first, with a short return to Elicit's questions for
the new rows only. Settled rows are not reopened.

Approval is what moves anything: on it,
[Step 5: Implement](../SKILL.md#step-5-implement) writes the emitters
through its conventions check, the plan file gains the new rows and their
metric sections, and [Step 6: Verify](../SKILL.md#step-6-verify) runs on
the new rows — the existing rows were green already, and a fresh
search-and-click need not re-prove them.

**The visit ends at Elicit's close, not only its questions**: with the new
rows in, re-ask [the close's one question](../SKILL.md#step-3-elicit) over
the whole table, screen included. The headline was chosen against a table
that no longer exists, and a row added today otherwise acquires no role,
neither headline nor guardrail; a raw search count or revenue-per-user
named here draws the same plain warning it would at first run. Where the
answer changed, rewrite the plan's `Headline metric:` and `Guardrails:`
lines, and the `Business outcome:` line where what the headline leads
toward moved with it; where it held, the lines stand. Either way they carry
the visit's date in the form [metrics-plan.md](metrics-plan.md) pins, so a
later session knows which table the close was last read against. "Settled
rows are not reopened" stays true: the rows do not change, only which one
leads.

**Check:** every new row has an emitting code path and joins live, the plan
file matches what the app now emits, and the close's headline and guardrail
lines were re-asked over the changed table, then re-confirmed or rewritten,
dated either way. Nothing reached the file or the app before the user
approved it.

## Judging what they have accumulated

**Goal:** the clicks a team has been collecting become a relevance judgment
list keyed to their own catalog, with the volume it rests on said out loud
and what it cannot answer said beside it. The field contract, the call
shapes, the failure catalog and every measured trap are in
[judgments.md](judgments.md); read it before running this. This file is the
order the visit puts them in, and what it says to the room at each point.

Every step is a free read except the build itself, a Critical Rule 5 write
announced alone in its turn. And the visit as a whole is a read under
Critical Rule 4: it reports what behavior already in the stores can be made
to say. No result of it is evidence the instrumentation works — that claim
is Verify's, made in the session that watched a real user search and click.

**Three questions are settled by reading, before anything is built.**

*Is the Workbench there, and on?* Read the cluster's plugin list for
`opensearch-search-relevance`; never infer from the version (the
Availability section of [judgments.md](judgments.md)). Absent or below its
floor, the visit closes honestly, naming exactly what is missing; present
but disabled, the enable is itself a Rule 5 write.

*Can this behavior be judged at all?* Run the pre-fix tell against
`ubi_queries` first ([judgments.md](judgments.md)): behavior captured with
`object_id_field` omitted is scored against the wrong documents, and the
result carries no sign of it. **A count above zero is said plainly: the
behavior those rows mark cannot produce judgments.** Put the count and the
window its rows span to the room — never dropped silently, never folded in
silently — and bound the build with `startDate` at the first day of
trustworthy behavior. Where every row is marked, there is nothing yet to
build over, and saying so is the visit.

*What will the list be able to cover?* Three reads, put to the room before
the build rather than offered as explanation after it:

- **The plan's mapped action names.** Only `impression` and `click` count;
  a row the room mapped to a custom click name is invisible to the model
  however faithfully it joins.
- **The query strings.** `user_query` is `keyword` in both stores, so a
  `terms` aggregation reads them directly: what people searched for in
  `ubi_queries`, against what the `impression` and `click` rows inside the
  window carry in `ubi_events`. The difference is what the list will be
  silent about — a search whose events never landed is absent from the
  result, not rated low. Exclude the empty string on the queries side: a
  search path sending `ext.ubi` on filter-only browsing writes
  `user_query: ""` rows, and those are page loads
  ([ubi-schema.md](ubi-schema.md)).
- **The deepest `position.ordinal` the window holds.** `maxRank` goes
  above it, or the list returns non-empty and entirely zero.

**Build, then read the result before reporting any of it.** Status first —
the create returns an id immediately and that proves nothing — then the
failure catalog, which tells an empty list from an all-zero one from a
permission failure. An empty list is a defect to debug in this session,
never "no data yet". This is also the visit that meets the nested-objects
limit, because it is the one that runs at real volume: the call that passes
clean on a demo fails loudly here, and raising the limit on the judgment
store is another Rule 5 write.

**The report is three things, and stops there.**

- **What it covers.** How many distinct query strings carry ratings
  against how many the stores hold, and which of the plan's goals those
  searches serve. The plan is where the room wrote down which journeys it
  cares about; a list that rates none of them is a finding, not a detail.
- **What it rests on.** The volumes, read from the stores and reported
  beside the list, because the entity carries none of them (*How much
  behavior is enough* in [judgments.md](judgments.md)): how many events
  the window holds, how many distinct query strings they carry, and how
  many ratings stand on a handful of impressions. Whether it is enough is
  the room's call, made with the volumes in front of them. Where they look
  thin, read the plan's `Retention:` line before saying the team needs
  more traffic: a window doing its job is indistinguishable, in the
  stores, from behavior that never happened, and lengthening it is the
  cheaper of the two answers.
- **What it cannot tell them.** Said whether or not anyone asks, because
  every over-reading of a judgment list starts here. It rates what this
  ranker showed and these users clicked: a document no ranking ever
  presented has no rating, and its absence is not a low score. A click is
  not a verdict; a misleading title earns one. The numbers are not
  relevance on a 0-1 scale, nor stable while the store grows
  ([judgments.md](judgments.md) has the arithmetic). What the list is for
  is measuring a ranking change against what these users chose.

**The visit does not tune a ranker.** Comparing rankers against a judgment
list, and tuning on what the comparison finds, belong to
[opensearch-launchpad](../../opensearch-launchpad/SKILL.md); watching one
configuration's scores drift against the list is monitoring, not tuning,
and stays here. Hand over the list's name and id, say that it refreshes by
being rebuilt as behavior accumulates, and close with the one offer below.

**Keeping the check running.** The handover's offer, made once: the
Workbench can re-run this evaluation on a schedule — the app's own search,
over query strings sampled from what people actually type, scored nightly
against the list their clicks built — so a ranking or catalog change that
buries what users choose shows up as a falling score instead of waiting for
the next review. Two sentences go to the room with the offer, because every
over-reading starts where they are skipped: the check watches the ranking
against a snapshot of what users chose, and its numbers stand still while
behavior accumulates, so refreshing it is the rebuild below; and it does
not watch the plan's targets, which the dashboard already reads live.

Before anything is proposed, three things are settled by reading, each over
the contract in [judgments.md](judgments.md): the `_id` precondition (a
catalog whose `_id` is not the `object_id` value scores every run zero, and
the honest answer is that the check cannot score), the sampler (top-N by
frequency, never the silent default, which carries browse loads into the
set), and the cron, said plainly (five-field, firing on the cluster's
clock, not the room's). The build on the go-ahead is one setup named in one
plain sentence — a query set sampled from their own searches, their search
as a stored configuration, the experiment that scores it, and its schedule
— and it is a Critical Rule 5 write, alone in its turn.

Creating the experiment runs the evaluation once, immediately: read those
first numbers back with the same three-part honesty as the list itself.
That first run, and the job read back with its cron, are what this session
verifies; the schedule *having fired* is tomorrow's fact, and it is not
claimed today.

A later session finds the check by reading, never by memory: the job list
is a free read, and an existing schedule is the team's standing choice —
report it beside the review's numbers and change it only on their ask,
announced as the one move it is. When the room wants the check reading
newer behavior, that is the rebuild: a new judgment list, a new experiment
over it, its own schedule, and the old *schedule* deleted — never the old
experiment, whose deletion takes the accumulated record with it
([judgments.md](judgments.md) has the shapes and the cascade). A falling
score is reported like any other number; acting on it is the work the
boundary above hands to launchpad.

**Check:** the pre-fix tell was read and reported before anything was
built; the build ran on the user's go-ahead; and the list left the session
with its coverage, its volume and its limits stated beside it. Where the
room took the scheduled check, it was built on its own go-ahead and read
back: the job with its cron, and the first run's numbers.

The three word-not-figure rules above govern wherever a number is reported,
including the walkthrough that closes
[Step 7](../SKILL.md#step-7-dashboard) and the volumes the judgment report
puts beside its list. They do not reach the list itself: an empty judgment
list is a defect, never the "no data yet" the second rule licenses, and the
failure catalog is what tells the two apart.
