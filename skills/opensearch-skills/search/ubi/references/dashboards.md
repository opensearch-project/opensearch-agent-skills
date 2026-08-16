# Dashboards reference: saved objects from the plan file

Pinned against OpenSearch Dashboards 3.8.0, verified against a live instance
2026-08-09 and extended 2026-08-11. Every shape and trap below was exercised on
that version, not read off documentation — the import API reports most failures
with an HTTP 200, so a doc example that "worked" is not evidence, and neither
is a clean import (see the render trap). The shapes added 2026-08-11 were
rendered as well as imported. The managed path at the end is unverified on
both counts.

Read this when generating dashboards from `ubi-metrics-plan.md`. The plan is
the source: its metric sections carry the queries, and a panel may show only
what its metric's own query computes.

## Read before you import

**Dashboards is its own service on its own host and port.** It is not the
cluster endpoint the Audit found, and the app's config does not hold it (the
app talks to the cluster, never to Dashboards). Ask the user for the address
and read it back — the Audit's fence against guessing an endpoint covers this
one. Settle it now, before the read below: deferred, it lands in the turn that
asks permission to import, and one reply cannot answer both an address and a
permission.

**The first call to that address is a read.** Saved objects live in the
cluster, which has no undo, so list what is already there before importing
over it:

```
GET <dashboards-url>/api/saved_objects/_find?type=visualization&type=dashboard&type=index-pattern&per_page=100&fields=title
```

Ask for the three types unfiltered and match the id prefix yourself. The
`search` parameter matches attributes, tokenized, and answers with an
arbitrary partial set — a plausible subset, worse than an obvious zero.
Measured: against a store holding nineteen of these objects, `search=ubi*`
returned three (two index patterns, one dashboard matched on its description).

**What comes back completes the Critical Rule 5 announcement.** Name the
objects this import will replace, by id and title, then ask for the go-ahead.
Without the read, the announcement can only describe what is being sent — the
half the user already knows. Earlier generations are easy to miss because
saved objects live in Dashboards' own store: resetting the repo and dropping
the UBI stores both leave them standing, so an import announced against an
assumed empty slate promises creations and performs replacements.

**Name the orphans in the same breath.** An object whose id the new file does
not carry is not replaced; it stays on the cluster looking as current as
anything else there. Offer to delete them — keeping them is a fair choice,
but the user's.

## The import call

```
POST <dashboards-url>/api/saved_objects/_import?overwrite=true
Header: osd-xsrf: true
Body:   multipart/form-data, field name `file`, the .ndjson as the file
```

Three things fail the call outright, each with a real HTTP error:

- **A filename not ending `.ndjson`**: `400 Invalid file extension .json`.
  The extension is checked, not the content type.
- **A missing `osd-xsrf` header**: `400 Request must contain the osd-xsrf
  header.` Any value works; `true` is conventional.
- A missing or empty `file` field.

The call is one of the three writes identical on every app, so it belongs in
the repo's setup artifact alongside store initialization and the probe rather
than being typed fresh each visit; the contract, and why the body and not the
status code is the test, are in [cluster-setup.md](cluster-setup.md). The
first import of a session adds the step to the artifact the Preflight gate
already wrote.

**The .ndjson is transport, not an artifact.** Delete it once the attempt
ends — landed, declined, or failed alike; keep it only if the user asks.
Everything else this step produces sits under Critical Rule 2's destination
fence, and the dashboard is what the fence points *at*: a place the team can
already reach.

## The trap: failure arrives as HTTP 200

Everything beyond the three errors above (an object type this Dashboards
cannot build, a reference to a missing index pattern, a malformed attribute)
comes back **200 OK** with a body that says it failed:

```json
{"successCount":0,"success":false,
 "errors":[{"id":"…","type":"visualization",
            "error":{"type":"missing_references",
                     "references":[{"type":"index-pattern","id":"does-not-exist"}]}}]}
```

**Read `success` and `errors`; never the status code.** A curl checking
`%{http_code}` reports a completely failed import as a success. Observed
error types: `unsupported_type` (no factory for that type on this version)
and `missing_references` (an id named in `references` is absent — by far the
likeliest real failure, and the reason index patterns go in the same file as
the objects that use them).

**And `success: true` is not evidence the object is loadable.** The import
API treats `visState` as an opaque string and does not validate it. Measured:
a visualization typed `this_type_does_not_exist` imported with
`{"successCount":1,"success":true}` and failed at *render* — `Failed to load
the visualization`, `Invalid visualization type`, under a `⚠ Unknown
visualization type` badge. The deciding registry is client-side, so reading
the object back does not catch it either. Only a rendered panel is evidence,
which is what the step's own check asks for.

## The second trap: the first render can be blank

A freshly imported dashboard's first load paints each panel's frame and title
with an **empty body** — no number, no error. Refreshing once the page has
finished loading paints it correctly; entering and leaving edit mode does too.
A refresh fired while the page is still settling does nothing, so this reads
as "refresh does not help" if tried once. The tell that data is not the
cause: the markdown guide panel, which has no query behind it, paints empty
on the same first load. Reproduced on 3.8.0 with saved objects byte-identical
to ones Dashboards itself had written — a render-timing behavior of the app,
not a defect in the generated file.

Two obligations follow:

- **A blank first paint is not evidence the objects are wrong.** Refresh
  before diagnosing, or a correct dashboard gets "fixed" into a broken one.
- **A successful import is not a rendered dashboard, and neither is a first
  paint.** "The dashboard works" is earned by a number appearing in a panel
  after a refresh — the same standard Critical Rule 4 sets for
  instrumentation.

## The third trap: a backgrounded tab renders nothing at all

Two blanks, one observable between them: **a first paint gives the panel
frame and title with an empty body; a backgrounded tab gives a loading
spinner and no frame or title at all.** A spinner is a statement about the
tab, not the objects.

Dashboards holds every panel at that spinner while `document.visibilityState`
is `hidden`. A dashboard opened in a tab that is not the foreground tab of a
focused window waits there indefinitely — no error, nothing in the console.
Refresh does not help (it does not make the tab visible), and overriding the
property from page script does not either: the render is gated on the real
one. Bring the tab to the front and the panels paint within seconds.

Browser automation is the case that hits this, and the step's own check runs
through a browser. The cost is worse than the wait: a panel that never
rendered reads as a panel that rendered blank, and gets reported as a defect
in objects that are fine.

## Object shapes

One JSON object per line, no trailing commas, each
`{"type","id","attributes","references"}`. Omit `migrationVersion`; the
import stamps it (on 3.8.0: `visualization: 7.10.0`, `dashboard: 7.9.3`).

**Derive every id from the plan; never invent it.** Ids are what
`overwrite=true` matches on, and the only thing it matches on. A `ubi-`
prefix plus a slug of the metric row's name gives the same plan the same ids
on every run, which is what makes a regeneration a replacement. Measured:
two runs over one cluster named the same metric `ubi-median-opened-rank` and
then `ubi-b-median-rank`, matched nothing, and left both generations live
side by side — while the index patterns in those same runs, whose ids are
just the store names, matched and were replaced silently.

**An id is not a label.** On a visualization or the dashboard, a title equal
to its id is a defect: the import does not read titles, a slug renders as
readily as a sentence, and the dogfood dashboard headed a group of panels
`ubi-section-find` where the goal's own words belonged. Index patterns are
the exception — a pattern's title *is* its store name, so `ubi_events`
titled `ubi_events` is correct and the shape below depends on it. A
visualization carries its title *twice*, in `attributes` and again inside
`visState`; read both against the id and against each other, in one pass
over the generated file before it is sent. That pass is the only catch: the
import does not complain, and a rendered slug looks like a decision somebody
made.

A goal section header has no metric row to slug and derives its id from the
Goal column instead; the section-header section below pins that shape and
what renaming a goal costs.

**Index pattern**: one per store the panels read, carrying a real `fields`
list read from the store's live mapping. Dashboards populates that list on
first use, but **first use is not import time**: opening a visualization
against a freshly imported pattern with no `fields` redirects to Saved
Objects with `Could not locate that index-pattern-field (id: query_id)`, and
no panel paints. Long-lived patterns carry theirs (the two dogfood ones hold
9 and 22 entries), so this fires on a first run and never again — exactly
the run with no working dashboard to compare against. `fields` is a JSON
*string*, like `visState`.

```json
{"type":"index-pattern","id":"ubi_events",
 "attributes":{"title":"ubi_events","timeFieldName":"timestamp",
   "fields":"[{\"name\":\"timestamp\",\"type\":\"date\",\"esTypes\":[\"date\"],\"searchable\":true,\"aggregatable\":true,\"readFromDocValues\":true},{\"name\":\"query_id\",\"type\":\"string\",\"esTypes\":[\"keyword\"],\"searchable\":true,\"aggregatable\":true,\"readFromDocValues\":true}]"},
 "references":[]}
```

Every field a panel filters, aggregates or buckets on needs an entry —
`timestamp` for the trend panels among them. Types come from the store's
live mapping, which Verify has already read once.

**Visualization**: `visState` and `searchSourceJSON` are JSON *strings*
inside the attributes, not nested objects. The index pattern is reached
through a reference, never by id inline: `searchSourceJSON` carries
`indexRefName`, and `references` carries the matching name.

```json
{"type":"visualization","id":"ubi-median-opened-rank",
 "attributes":{
   "title":"Median opened rank",
   "visState":"{\"title\":\"Median opened rank\",\"type\":\"metric\",\"aggs\":[{\"id\":\"1\",\"enabled\":true,\"type\":\"median\",\"params\":{\"field\":\"event_attributes.position.ordinal\"},\"schema\":\"metric\"}],\"params\":{\"type\":\"metric\",\"metric\":{\"percentageMode\":false,\"colorSchema\":\"Green to Red\",\"metricColorMode\":\"None\",\"colorsRange\":[{\"from\":0,\"to\":10000}],\"labels\":{\"show\":true},\"style\":{\"fontSize\":60}}}}",
   "uiStateJSON":"{}",
   "kibanaSavedObjectMeta":{"searchSourceJSON":"{\"query\":{\"query\":\"application:\\\"sundry\\\" and action_name:\\\"click\\\"\",\"language\":\"kuery\"},\"filter\":[],\"indexRefName\":\"kibanaSavedObjectMeta.searchSourceJSON.index\"}"}},
 "references":[{"name":"kibanaSavedObjectMeta.searchSourceJSON.index","type":"index-pattern","id":"ubi_events"}]}
```

**Dashboard**: `panelsJSON` is a JSON string holding one entry per panel,
each pointing at its visualization through `panelRefName` and a matching
reference named `panel_0`, `panel_1`, and so on. The grid is **48 columns**
wide; `gridData.i` and `panelIndex` must agree.

```json
{"type":"dashboard","id":"ubi-metrics",
 "attributes":{
   "title":"UBI metrics",
   "hits":0,
   "panelsJSON":"[{\"version\":\"3.8.0\",\"gridData\":{\"x\":0,\"y\":0,\"w\":24,\"h\":15,\"i\":\"1\"},\"panelIndex\":\"1\",\"embeddableConfig\":{},\"panelRefName\":\"panel_0\"}]",
   "optionsJSON":"{\"hidePanelTitles\":false,\"useMargins\":true}",
   "timeRestore":true,"timeFrom":"now-30d","timeTo":"now",
   "refreshInterval":{"pause":true,"value":0},
   "kibanaSavedObjectMeta":{"searchSourceJSON":"{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[]}"}},
 "references":[{"name":"panel_0","type":"visualization","id":"ubi-median-opened-rank"}]}
```

Set `timeRestore` with a window wide enough to hold the data. A dashboard
opening on the default last-15-minutes shows an empty panel on a store whose
events are hours old, and empty reads as broken.

## Reconcile each metric against the stores first

Run every metric's plan query against the live stores **before** generating
anything, and read what it *matched*, not what it returned. A query can
return a number while counting the wrong rows — the mechanism and the honest
form are the population entry in [ubi-schema.md](ubi-schema.md)'s failure
catalog. Measured on the dogfood dashboard: that entry's exact case put a
denominator at 2 where the metric's own prose said 1, and nothing errored.
Both halves of the step's check agree on a wrong number when the query under
them is wrong, which is why this leg exists.

The question at this gate is whether these are the rows the metric is about,
and the plan's own prose is the specification — it names the population in
the user's words. Read the matched rows back the way that catalog entry
describes, but not with a `terms` aggregation: `query_attributes` is
`flat_object`, an aggregation on a subfield reads the whole object, and the
buckets come back as `java.lang.Object@…`
([ubi-schema.md](ubi-schema.md)).

Three outcomes stop a metric being published as a panel, each reported as
words:

- **The query fails** — and only one of its two failure modes is visible. An
  aggregation on a text-mapped field raises `illegal_argument_exception`; a
  stale field name, or a `term` filter on that same text-mapped field,
  answers zero and reports nothing. The naming trap and the failure catalog
  in [ubi-schema.md](ubi-schema.md) tell the silent pair apart.
- **Nothing matches, and names and types were checked first.** That order is
  not negotiable: a silent failure and an empty store return an identical
  zero, so read the store's live mapping before believing one. Only what
  survives that check is "no data yet" rather than zero — a distinction a
  metric visualization cannot draw, since it renders `0` either way. Then it
  depends on the store: on a first run, one search and one click make
  emptiness the expected state, so generate the panel and have the guide
  name it as awaiting data; on a store that has been collecting, an empty
  answer is a finding — withhold the panel and say so. Measured: the dogfood
  dashboard published `0` for autocomplete-begun searches against a 25%
  target on a store holding no autocomplete row — genuine absence, confirmed
  by the same field answering for its other values.
- **The rows are not the population the metric names.** The query is wrong,
  and wrong in the plan file as much as on the dashboard.

**A wrong query is corrected with the user, never quietly.** Verify fixes a
plan query on the spot because Map had just written it; on a later visit the
file may carry the user's own edits, so name the query, what its prose
claims, what the stores actually hold, and put the correction up for
approval. The panel is built from the query that survived.

This read is also what makes the interpretability floor below bind: a floor
stated in a file that never reads the stores can turn nothing down.

## Turning a plan query into a panel

A metric panel is one index pattern, one filter, and one aggregation. The
plan query's `bool.filter` term clauses become the panel's DQL query string
(`application:"sundry" and action_name:"click"`), and its aggregation
becomes the `visState` agg: `percentiles` to a metric visualization, `terms`
to a bar chart, `cardinality` or `value_count` to a metric.

**Every clause has to make the crossing.** The DQL string is written by hand
from a JSON query, and a dropped clause is invisible afterwards: the panel
renders a plausible number under the right title. Measured on the dogfood
dashboard: a plan query filtering on `add_to_cart` **and** `exists:
user_query` became the DQL `application:"sundry" and
action_name:"add_to_cart"`, and the panel answered 2 where its query
computed 1 — on the same metric whose denominator was already wrong above,
so the two defects are independent and one metric can carry both. Translate
clause by clause, then read the panel's number against the query's own. A
disagreeing pair is a panel to rebuild, not a discrepancy to note. Name both
numbers when reporting; never a bare "they match", which is the sentence
that stops anyone looking.

**Not every metric survives the translation.** A rate whose numerator and
denominator are separate requests — or, as with click-through rate, live in
*different stores* (`ubi_events` over `ubi_queries`) — has no single-panel
form: no aggregation in one visualization divides one index by another. For
those, generate the parts as their own panels and **label each panel as the
part it is**: "searches with a click" and "searches", never "click-through
rate". A panel carrying the numerator under the rate's name is a wrong
number on a screen people will read for months; the honest split lets the
reader do the division knowing what they divided. Where a metric yields no
honest panel at all, say so and leave it out — the plan's query still
answers it in a metrics review.

The parts trend for free (each is an ordinary single-store panel under the
trend section below) except for the target, which a part does not carry:
the target was agreed for the rate, and a 45% threshold drawn across a count
of searches is a wrong number given a line of its own. **The rate itself
does not trend.** Beyond the division problem, the numerator's rows are
stamped at click time and the denominator's at search time, joined only by
`query_id`, so a click and its own search land in different buckets whenever
they straddle a boundary; a rate trend is honest only at intervals
comfortably longer than search-to-click latency, and no visualization type
repairs that. Trend the parts, and let the guide's division instruction
carry the rate.

The interpretability floor governs here exactly as in the review: a metric
whose stores lack the captured query, the presented ranking, or clicks
carrying `position.ordinal` gets no panel, because a panel is the most
durable way to publish a wrong number.

## The trend panel: the same metric over time

A metric panel answers *what is it now*; the question a team that agreed
targets actually has is *which way is it going*, and every metric in the
plan carries a target nothing on a metric panel ever draws. So a metric that
earns a panel earns two: its number, and its number over time with its
target on it.

**The trend derives from the plan query; the plan file does not change.**
Keep the metric panel's filter exactly as it is and wrap its aggregation in
a `date_histogram` on `timestamp`. Verified at the cluster: `value_count`,
`cardinality` and `percentiles` all nest under one, and both stores type
`timestamp` as `date`, so no per-metric time field is needed and
`interval:"auto"` takes its window from the time picker. Deriving rather
than adding a plan column is what lets every plan file already written gain
trends with no migration — `ubi-metrics-plan.md` is a parsing contract later
sessions depend on. This is legal under the rule this file opens with: a
time bucket of the same aggregation is the same metric over time, not a
second metric, and the metric panel is already a bucket of one.

**Pin `min_doc_count: 1` and never zero-fill.** Measured over a window whose
middle hour held the only two clicks: with `min_doc_count:0` and
`extended_bounds`, the empty hours answered `cardinality: 0` and
`percentiles[50]: null` out of the same buckets — a plotted zero beside an
honest gap. A flat zero line for "searches with a click" across a week
nobody shopped is what the metrics review forbids in words — *"Zero is a
measurement; absence is not"* ([return-visits.md](return-visits.md)) — and a
chart publishes it far more durably than a sentence.

**Buckets do not sum to the metric panel's number**, `count` excepted: two
buckets each counting 2 distinct `query_id`s may hold 2 between them, and a
median of medians is not a median. The guide panel has to say what a bucket
is, or a reader adds the line up and gets a different answer from the big
number beside it.

### Drawing the target

`thresholdLine` lays the agreed target across the chart as a dashed line —
actual-against-target and direction-of-travel in one panel. It is a scalar
on `params`, one line per chart; `style` takes
`"full" | "dashed" | "dot-dashed"`:

```json
"thresholdLine":{"show":true,"value":40,"width":2,"style":"dashed","color":"#E7664C"}
```

**A threshold outside the data's range is silently not drawn.** The value
axis scales to the data alone, not the data and the threshold together.
Measured: buckets topping out at 1 with `value: 40` — the axis ended at 1,
no line, no warning, no clipped stub. For a higher-is-better metric that
means the target line stays invisible exactly as long as the team is under
target. Pin the value axis's `scale`:

```json
"scale":{"type":"linear","mode":"normal","setYExtents":true,"min":0,"max":45}
```

Measured with that in place: the axis ran 0-45 and the line drew at 40.

**The opposite failure is just as quiet, which makes the maximum a
judgment.** Data above a pinned `max` is clipped, and the series draws flat
along the top as though it had levelled off there. Measured: `max: 0.5`
against buckets reaching 1 rendered a line pinned to the ceiling.

So set `min: 0` and a `max` comfortably above **both** the target and the
largest bucket the data holds. The target is in the plan; the bucket maximum
is not, and the reconcile pass does not supply it either — it runs each
query unbucketed, which for a count answers the *sum* of the buckets, not
the largest. Run the trend's own aggregation once to find it: that request
is the panel's own query, so one round trip settles the axis maximum and
whether this metric has anything to plot yet.

Then say the residue: that maximum is a snapshot of the data on the day it
was generated, so a metric that outgrows it reads as flat at the ceiling
until someone regenerates the dashboard. A visible distortion traded for a
silent absence is the honest trade, not a free one.

### The whole shape

The `visState` of a verified trend panel, shown as the object it is before
being serialized into the string the attributes hold. The rest of the
visualization (`searchSourceJSON` carrying the DQL, the `indexRefName` and
the matching `references` entry) is unchanged from the metric panel above.

```json
{"title":"Searches with a click over time","type":"line",
 "aggs":[
   {"id":"1","enabled":true,"type":"cardinality",
    "params":{"field":"query_id"},"schema":"metric"},
   {"id":"2","enabled":true,"type":"date_histogram",
    "params":{"field":"timestamp","interval":"auto","min_doc_count":1,
              "useNormalizedOpenSearchInterval":true,"scaleMetricValues":false,
              "drop_partials":false,"extended_bounds":{}},"schema":"segment"}],
 "params":{"type":"line","grid":{"categoryLines":false},
   "categoryAxes":[{"id":"CategoryAxis-1","type":"category","position":"bottom",
     "show":true,"style":{},"scale":{"type":"linear"},
     "labels":{"show":true,"filter":true,"truncate":100},"title":{}}],
   "valueAxes":[{"id":"ValueAxis-1","name":"LeftAxis-1","type":"value",
     "position":"left","show":true,"style":{},
     "scale":{"type":"linear","mode":"normal","setYExtents":true,"min":0,"max":45},
     "labels":{"show":true,"rotate":0,"filter":false,"truncate":100},
     "title":{"text":"Searches with a click"}}],
   "seriesParams":[{"show":true,"type":"line","mode":"normal",
     "data":{"label":"Searches with a click","id":"1"},"valueAxis":"ValueAxis-1",
     "drawLinesBetweenPoints":true,"lineWidth":2,"interpolate":"linear",
     "showCircles":true}],
   "addTooltip":true,"addLegend":true,"legendPosition":"right",
   "times":[],"addTimeMarker":false,"labels":{},
   "thresholdLine":{"show":true,"value":40,"width":2,"style":"dashed",
                    "color":"#E7664C"}}}
```

Three cross-references inside it must agree or the chart draws nothing
useful: `seriesParams[].data.id` names the metric agg's `id`,
`seriesParams[].valueAxis` names the value axis's `id`, and the axis whose
`scale` was pinned is the axis the series is assigned to. The metric agg is
the one the plan query specified (`cardinality` here); swapping it for
`value_count` or `percentiles` is the only edit a different metric needs.

### Reconciling a bucketed panel

A line chart has no single number, so the check names **the latest bucket's
value against the plan query restricted to that same interval**: the query
gains a range filter on the bucket's own bounds and changes in no other way.
Read the value off the panel, not inferred — the tooltip gives it on hover,
and the panel's Inspect view gives the response underneath.

The pair is the evidence exactly as for a metric panel, and fails the same
way: a dropped DQL clause draws a plausible line under the right title. What
it does not catch is a clipped axis — a clipped series still reports its
true value in the tooltip, so the pair agrees while the chart misleads. When
the latest bucket's value sits at or above the axis maximum, the axis is
wrong even though the numbers matched.

## One dashboard, laid out by goal

**At this size — two or three goals, a handful of metrics — one dashboard is
correct**, with the goals as sections within it. The convention for more is
hierarchical (an overview with drill-down, split only when the magnitude of
content demands it; Grafana's dashboard best-practices guidance is the
closest thing to an authority).

Splitting per goal would actively damage this skill: the headline metric and
the guardrail bounding it routinely sit under **different** goals, the
skill's own instruction is to read the two together always, and separate
dashboards put a click in the middle of that one mandated comparison.
Critical Rule 2 also names *the* dashboard whose guide panel carries *the*
goals, so a goals-split with no overview makes a Critical Rule literally
false. And there is no dashboard-id derivation rule to split with: the sole
dashboard id is the constant `ubi-metrics`, and a per-goal id would have to
slug the free-form, user-editable Goal column — so renaming a goal would
orphan a whole page by the mechanism the ids paragraph above describes.

### The section header

A section is a markdown panel at the grid's full width above the panels it
introduces, carrying the goal in the plan's own words and the targets agreed
for it. Order the sections as the plan's table orders its goals, so the page
and the file read side by side.

**The goal goes in the body as a `###` heading, and the panel's own title is
hidden.** Measured on 3.8.0: a chrome panel title renders in the same
element and weight as every other panel's title, and setting the title *and*
the heading printed the goal twice and clipped the targets line at `h:4`.
The judgment that follows: a goal set at the weight of the panel labels
around it reads as one more panel, not as the break between two groups —
which is a header's whole job. The `title` attribute is still the goal
verbatim: it is what the Saved Objects screen lists the panel under, and the
ids paragraph says why it may never default.

Hide the title on the panel, not the dashboard: `hidePanelTitles` in a
panel's `embeddableConfig` overrides the dashboard's setting. Verified
against a dashboard whose `optionsJSON` carried `"hidePanelTitles":false` —
the overriding panels rendered no title and the rest kept theirs. The
dashboard-wide setting stays `false`, because every other panel on the page
is read by its title.

```json
{"type":"visualization","id":"ubi-section-find-the-right-thing",
 "attributes":{
   "title":"Find the right thing",
   "visState":"{\"title\":\"Find the right thing\",\"type\":\"markdown\",\"aggs\":[],\"params\":{\"markdown\":\"### Find the right thing\\n\\nTargets: ≥60% of text searches get a click · median clicked rank ≤3\",\"openLinksInNewTab\":false,\"fontSize\":12}}",
   "uiStateJSON":"{}",
   "kibanaSavedObjectMeta":{"searchSourceJSON":"{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[]}"}},
 "references":[]}
```

Its entry in the dashboard's `panelsJSON`, full width and carrying the
override. **The two are a pair**: the visualization alone, dropped onto a
panel without this `embeddableConfig`, is the shape that prints the goal
twice. `y` is wherever the group above ended — 50 here, because the guide
panel is `h:50`.

```json
{"version":"3.8.0","gridData":{"x":0,"y":50,"w":48,"h":4,"i":"2"},
 "panelIndex":"2","embeddableConfig":{"hidePanelTitles":true},
 "panelRefName":"panel_1"}
```

**`h:4`, not `h:3`.** Measured with a `###` heading and one line of targets:
`h:3` cut 16px off the targets line while the heading sat perfectly — the
shape that reads as a finished header while silently missing half its
content; `h:4` cleared the line by 16px. A `##` heading renders at 32px
against `###`'s 23px and leaves the same line 2px short at `h:4` — a row
spent for nothing. All heights were measured with a targets line that fits
on one row; a line long enough to wrap (which the window decides as much as
the plan does) needs a row above whatever fits, and was not measured.

The id is `ubi-section-` plus a slug of the Goal column — the only text a
section has, and the user's own free-form wording, so renaming a goal
orphans its header: one stale heading over a live group of panels. The read
that opens this file is what surfaces it.

## The guide panel

Every generated dashboard carries one markdown panel — the only place the
page can explain itself to someone who opens it months from now with no
transcript: rates are published as their parts, the targets live in a file
in a repo, and withheld metrics are simply absent. The division instruction
in particular has nowhere else to live.

The shape is a visualization with no aggregation and no index pattern, so it
carries no `references` at all — verified by import on 3.8.0:

```json
{"type":"visualization","id":"ubi-guide",
 "attributes":{
   "title":"How to read this dashboard",
   "visState":"{\"title\":\"How to read this dashboard\",\"type\":\"markdown\",\"aggs\":[],\"params\":{\"markdown\":\"### How to read this\\n\\n| Goal | Metric | Target | Panel | How to read it |\\n| --- | --- | --- | --- | --- |\\n…\",\"openLinksInNewTab\":false,\"fontSize\":12}}",
   "uiStateJSON":"{}",
   "kibanaSavedObjectMeta":{"searchSourceJSON":"{\"query\":{\"query\":\"\",\"language\":\"kuery\"},\"filter\":[]}"}},
 "references":[]}
```

`params.markdown` is the body — headings, bold, lists **and tables** all
render (tables with bold centred headers, cell borders and row separators;
`**bold**`, em dashes, `→`, `≥` and `≤` render inside a cell). It is a
string inside the `visState` string, so its newlines are escaped twice, and
it is the only load-bearing part: `fontSize` (points), `openLinksInNewTab`,
`uiStateJSON` and `kibanaSavedObjectMeta` all import cleanly when omitted.
Give the panel the grid's full width and the top row: it is read first or
not at all.

**A single newline does not break a line** — markdown joins consecutive
lines into one paragraph. Measured: the `Headline metric:` and `Guardrails:`
lines rendered as one run-on line, the second label buried mid-sentence.
End the first line with two spaces, or put a blank line between them; both
were measured, and the blank line reads more clearly.

What the panel carries, in the room's own language (the vocabulary of
whatever framework produced the goals stays backstage here as everywhere),
in a shape a reader takes in without scrolling: **one table and a footer of
one-liners**, each fact one cell or one line, the reasons staying in this
file and in the handover. A guide written as paragraphs was the dogfood
failure: some 2,400 characters at `h:13`, and it scrolled — the single
thing a read-first panel must never do.

**The table** — one row per metric in the plan, none skipped, under the
plan file's pinned columns ([metrics-plan.md](metrics-plan.md)) minus
Signal, which stays in the file, plus the two facts only the dashboard
knows:

| Goal | Metric | Target | Panel | How to read it |

Goal, Metric and Target in the plan's own words, so the page and the file
read against each other without translation — a reader who cannot get from
a panel back to its goal has a number and no reason for it. Panel names the
panel or panels that answer the metric, or `—` for a metric that got none.
"How to read it" is one clause, only where a metric needs one:

- published as parts: the division written out — which panel over which
  panel. A reader who does not know to divide reads a numerator as a rate.
- an exclusion in the definition: named — "autocomplete picks excluded" is
  the difference between a median the team trusts and one someone quietly
  recomputes.
- no panel: the reason — below the floor, no honest single-panel form, or
  withheld at the gate. Absence without a reason reads as an oversight, and
  the withheld metrics are exactly the ones someone will go looking for.
- a plain panel with no caveat: an empty cell, not a filler sentence.

**The footer** — one line each, separated per the newline trap above:

- The headline metric and its guardrails, from the plan's lines beneath its
  table ([metrics-plan.md](metrics-plan.md)), named as what they are — a
  page of equal-weight panels reads as seven priorities.
- An empty panel means no data in the window, not zero; a trend bucket is
  the metric over that interval alone and buckets do not add up to the big
  number beside them for anything but a count; the dashed line is the
  agreed target, and a panel published as one part of a rate carries none.
- The page says what happened, never why — correlations, not causes
  (Grimes, Tang and Russell, WWW 2007); a why read off a panel is a story
  the reader brings ([return-visits.md](return-visits.md)).
- The identity choice Map settled: what the instrumentation mints and what
  that rules out — a per-visit `client_id` counts visits, never people, so
  no retention or returning-visitor number will ever come off this page.
- The plan's dated `Search volume:` line, carried as the plan carries it;
  where it is thin, say so and stop — whether it is enough is the room's
  call ([return-visits.md](return-visits.md)).
- Where the plan lives — `ubi-metrics-plan.md` at the app repo's root, as a
  path, because a link would point at a repo this cluster cannot reach —
  and the one control the reader has: the time picker sets the window every
  panel answers for.

Give the panel the height this needs — height is the one dimension nothing
here pins, and the one that bites. Measured: a table costs *more* height
than the same content as prose, not less — a two-row table with the
headline and guardrail lines beneath it clipped at `h:10`. The table earns
its height by being scannable, so budget for it: when content overflows,
the answer is a taller panel, never a dropped row. The handover below is
where the user says whether the guide reads correctly to someone who was
not there.

## Handing it over

A successful import does not close the step. Read the dashboard back with
the user, panel by panel, every division said out loud — the person in the
session is the last one who can cheaply catch a numerator being read as a
rate. Say which metrics got a number and a trend, which were published as
parts, and which got no panel at all, because absence without a reason reads
as an oversight.

Then ask the question the guide panel exists to answer: does it read to
someone who was not in this session? Only the user can answer it, and a
guide nobody checked is the failure the panel is built against.

Close by handing over the address as the thing to show the team, and say
what they can come back and ask: how a goal is progressing, whether the
numbers are on target, what their accumulated clicks now say about
relevance. Those are the return visits, and this is where the user learns
they exist.

## The managed path

Amazon OpenSearch Service domains ship OpenSearch Dashboards, and the import
surface above is unchanged. What differs is what the panels read: there is
no plugin, so the index patterns point at the app-built record indexes
described in [aws-managed.md](aws-managed.md), and the panels come from that
path's own plan queries, which already reflect that schema wherever the
app's records differ from the plugin's.

**This variant is not verified.** Everything above was exercised against a
self-managed 3.8.0 cluster; no dashboard has been imported into a real AOS
domain. Say so rather than implying the same evidence covers both.
