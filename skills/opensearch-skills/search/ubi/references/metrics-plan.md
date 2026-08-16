# The metrics plan file: pinned format

`ubi-metrics-plan.md` lives at the app repo's root. Map's approval writes
it; every later session re-reads it as the record of approved intent. The
user may have edited it since and their edits govern, so this format is a
parsing contract, not a style guide: write to it exactly.

## The four-column table

The file opens with the confirmed goals → signals → metrics table under
exactly four pinned columns: **Goal, Signal, Metric, Target**. The signal
names the audited UI action that carries it; the target is the number the
room agreed to. The pinned shape is what lets a later session re-parse
the file after the user has edited it.

Write the table for the terminal it will be read in: keep a row inside
about a hundred characters and put anything longer in the metric's own
section below.

**A metric whose name belongs to the business names its population too.**
`revenue`, `orders`, `signups` are numbers the business already holds, over
every customer it has; the same word in this table means the fraction of
them these stores can see, which is search-attributed sessions and nothing
else. Write `revenue on searched sessions`, never `revenue`: the shorter
name gets read against the business's own figure by someone who was not in
the room, and it is wrong by an unknown factor with nothing erroring. It is
the population trap below, moved one step earlier: there it is about the
filter the query carries, here it is about what the column may be called.

**A target carries the date it was set.** Write `60% (set 2026-08-14, no
baseline)` rather than `60%`. The number is agreed cold, before any joined
data exists, and the practices that license agreeing one cold (SLO and OKR
practice alike) attach the same condition: it is meant to be tightened or
loosened once there is a baseline to read it against. The first stretch of
joined data is what sets that baseline, and that stretch lengthens as
traffic thins, which is what the `Search volume:` line below lets a reader
weigh. The date is what lets a later session ask, and `no baseline` is what
tells it the first number was a judgment rather than a measurement; it is
replaced by the baseline's own date once one exists. The dates are also
the review visit's staleness check: a target still carrying `no baseline`
once the stores hold a stretch long enough to set one, or any dated line
more than six months old, is re-asked with the room rather than silently
trusted.

## Elicit's close: three lines beneath the table

`Headline metric:` names the one row the work steers by; `Guardrails:`
names the rows that must not degrade while it moves. Each is written as
the exact text of its Metric column, with `none` spelled out where the
room named none. These are labeled lines rather than a fifth column
because the four columns are what re-parsing depends on, and a name that
matches no row after a user's edit is a question for the user, never a
row to invent.

The lines are written at Elicit's close and re-asked when the table
changes: an extension visit re-asks the closing question over the whole
table ([return-visits.md](return-visits.md) owns when). Each re-ask dates
them the way `Retention:` is dated: `Headline metric: add-to-cart rate on
searched sessions (re-confirmed 2026-09-02)`, or `(rewritten 2026-09-02)`
where the answer changed. The parenthetical is the visit's record, not
part of the metric's name. A line with no parenthetical is first-run
Elicit's and unwarned, chosen against the table that session saw.

**A headline kept over the close's warning is recorded with it**: write
`Headline metric: searches per week (named over the warning,
2026-08-16)`, so a later session reads a decision rather than an
oversight. The warning itself is the close's
([SKILL.md](../SKILL.md#step-3-elicit)); its canonical case is a Bing
ranking bug that served very poor results while distinct queries per user
rose over 10% and revenue per user over 30% (Kohavi et al., KDD 2012),
and sessions per user is the offered alternative because satisfied users
come back. The room hears only the plain sentence, never the paper, and
the warning is a screen, never a veto: what the room chooses is what the
line carries. Each line holds one parenthetical, the latest visit's
record, so a warned headline kept on a later re-ask writes `(kept over
the warning, re-confirmed 2026-09-02)` and the warning survives the
date's refresh.

`Business outcome:` is the third, and it names what the headline metric is
a leading indicator *of*: what the business wants from search, which is
never itself a row in this table. Where the stores can carry that outcome
it is already a row and the line simply names it. Where they cannot, the
line carries the wall that stops it and the row standing in for it. The
walls are the business row of [reachability.md](reachability.md), not
this file's; name them from there rather than re-deriving them:

```
Business outcome: repeat purchases, out of reach (needs identity across
visits); stand-in: add-to-cart rate on searched sessions
```

`Business outcome: none named` is the line for a room that was asked and
holds none (someone's own tool, an internal docs search, an OSS project),
and it is never the line for a room that was not asked. That is the
distinction `Retention:` draws below, and it costs more here: an invented
outcome in this file reads to every later session as approved intent, and
nobody reading it will know it was never said out loud.

## The search-volume line

A fourth labeled line joins the close's three, written directly above
`Retention:`: `Search volume: ~1,200 searches/day (stated 2026-08-16)`.
This is the traffic every target in the table is read against. Elicit asks
it while the targets are agreed, and the number is the room's own rough
figure. The exception is stores that already hold behavior (a return
visit, or an app instrumented before this session): there the volume is
read rather than asked, as a `ubi_queries` row count over the window the
stores hold, said per day, and the parenthetical says so: `(read from the
stores 2026-08-16)`. A second exception is the team's own analytics tool,
connected in the session ([analytics-bridge.md](analytics-bridge.md)): a
number read from it names the tool, `(read from GA4 2026-08-16)`, and
claims only what the tool measured. A search-event count is a search
volume; a session count is not, and the line says which it is:
`Search volume: ~30k sessions/day, search share unknown (read from GA4
2026-08-16)`. The date is what lets a later session ask whether
traffic has moved since.

`Search volume: asked, not known (2026-08-16)` is the honest line for a
room that was asked and did not know. Write it rather than nothing, because
a missing line is indistinguishable from a session that never asked. The
line states a volume and stops there: no floor is attached and no verdict
follows from it, because no sourced threshold exists to read it against.
What a thin volume costs is time (the baseline stretch above arrives later
than the room assumed), and whether that is acceptable for the targets
they set is the room's call, made with the number in front of them.

## Map's close: the retention line

A further line joins them, written when Map settles the window:
`Retention: 90 days (agreed 2026-08-13)`. The number is the room's, and
this file is where it outlives the session that heard it. The delete that
enforces it is in [cluster-setup.md](cluster-setup.md), and the date is
what lets a later session ask whether the window still suits the traffic.

`Retention: none agreed` is the honest line for a room that was asked and
did not settle it, and it is never the line for a room that was not asked:
an unsettled window is the next question, like any other unsettled cell.
Write it rather than a number, though, because a window nobody chose reads
here exactly like one they did, and a later session reading `none agreed`
knows the stores are keeping everything, which is a finding rather than a
blank.

## The intents section, present only when the room named intents

When the room has named what people come to the app to do
([intent-labels.md](intent-labels.md)), the file carries an `## Intents`
section: a dated opening line, `Named by the room 2026-08-14.`, then one
bullet per label. Each bullet is the label in the room's own words,
followed by `(typed like: ...)` holding its seed phrasings separated by
semicolons:

```
- keep the kitchen and pantry stocked (typed like: flour; olive oil;
  trash bags)
```

A second opening line, `Assignment floor: 0.30 (agreed 2026-08-14)`,
is written when a review visit first reads an assignment table with the
room and the room approves the cut; `Assignment floor: none agreed`
before then. An absent section means the room was never asked, and the
review visit that wants to report by intent asks first. Labels and seeds
are the room's words: a later session proposes edits and the user makes
them, exactly as with every other cell in this file.

## Reconstructing a plan for an app that has none

An app that is instrumented but carries no `ubi-metrics-plan.md` predates
the artifact. It gets a reconstruction **offered, never started**; the
offer is the whole of what the session does unprompted.

What is rebuilt is the same four-column table, from two sources: the
events the code actually emits, and a short intent-recovery conversation
about what the code cannot say: which goal each captured event was
serving, and what target the room holds it to. The file is written only
on the user's approval, in the shape above.

Declining changes nothing, and the offer is not repeated within the
session. A reconstruction is a record of what the room agreed, recovered;
a table assembled from the emitters alone would be a guess at that
agreement wearing its format, which is the one thing this file must never
hold.

## One section per metric row

Each metric row gets a section carrying the fenced DSL query that computes
it from the stores this path actually writes: on the plugin path,
`ubi_queries` and `ubi_events` under the pinned field names of
[ubi-schema.md](ubi-schema.md); on the managed path, the app-built records
[aws-managed.md](aws-managed.md) describes. The query honestly reflects
that schema, which differs wherever the app's records do. Anything too
long for its table row lives here too, under its metric's heading.

The query answers for the rows the Metric column names and no others.
Where the stores hold rows that column excludes (browse page loads sitting
among searches, one surface among several), the query carries the filter
that excludes them, or it reports on a population its own metric does not
describe. The trap that makes this easy to get wrong, and the honest form,
are the population entry in the failure catalog of
[ubi-schema.md](ubi-schema.md).
