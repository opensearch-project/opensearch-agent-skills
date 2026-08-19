# Judgments: the Search Relevance Workbench contract

The Search Relevance Workbench turns the behavior this skill captures into
implicit relevance judgments: per-query ratings of the documents users saw,
computed by its COEC click model (Clicks Over Expected Clicks) from
impressions and clicks alone. This file is the contract that makes that
hand-off work: the event fields the model reads, the calls that build and
read a judgment list, the ways a result fails while looking finished, and
the scheduled check that keeps scoring the app's search against the list.

Pinned against opensearch-search-relevance 3.8.0.0 (OpenSearch 3.8.0): the
contract and arithmetic from the plugin's source at that tag, every call and
error shape measured live against a 3.8.0 cluster (2026-08-13 for
judgments, 2026-08-14 for scheduled experiments). Where this file and the
Workbench docs disagree, this file follows the source and the measurements.

## Availability

The Workbench ships in the standard distribution from OpenSearch 3.1 and is
enabled by default from 3.2. Detect it the preflight way: read the cluster's
plugin list for `opensearch-search-relevance`; never infer from the
version.

- **3.2+:** present and on; no install, no model, no spend.
- **3.1:** present but off by default. The enable is a dynamic cluster
  setting, a Critical Rule 5 write, announced and approved like any other:

  ```json
  PUT /_cluster/settings
  { "persistent": { "plugins.search_relevance.workbench_enabled": true } }
  ```

- **Below 3.1, or the plugin absent from the list:** judgments are not
  available. The honest stop applies: name exactly what is missing.

**The disabled tell (measured):** while the setting is off, every Workbench
endpoint, reads included, answers HTTP 403 with the plain-text body
`Search Relevance Workbench is disabled`. That text is the setting, not the
security plugin; a security-plugin denial is a JSON `security_exception`.

**Upstream's own consumer (talk-sourced, not measured):** from OpenSearch
3.6 a "relevance agent" (hosted on the separately deployed OpenSearch agent
server and wired to an LLM) drives these same Workbench APIs from a chat
panel in Dashboards. It reads the event fields this contract prepares, so it
is a consumer of this skill's output, never a prerequisite for this visit.
Do not install or require it to build judgments: every call this file needs
runs directly, on 3.1+, with no model and no extra service.

## The field contract: what the click model reads

The COEC click model reads each event document in `ubi_events` and fetches
exactly five fields from it:

| Field | Role in the model |
|---|---|
| `user_query` | the grouping key: clickthrough rates are grouped by this string, read from the event |
| `action_name` | only `impression` and `click` count (case-insensitive); every other name is invisible to the model |
| `event_attributes.object.object_id` | the document being rated; ratings are keyed by it |
| `event_attributes.position.ordinal` | both of the model's passes filter on it, `lte(maxRank)` |
| `query_id` | fetched with the rest |

**It performs no join to `ubi_queries`.** Everything the model uses must sit
on the event row itself. Three consequences, each a way for a green-looking
store to produce nothing:

- An event without `user_query` is skipped hit by hit, with a warn-level
  log, no error, and no count of what was dropped. A store whose events
  lack the field completes with an empty list (measured below). This is why
  the typed text is a required event field, not an optional copy.
- An event without `position.ordinal` never reaches the model at all: both
  passes bound the ordinal with `lte(maxRank)`, and a document missing the
  field fails a range filter. A click without its rank is invisible, which
  is why the ordinal is unconditional on clicks, not just impressions.
- A custom click name (`result_selected`, anything outside the standard
  set) is ignored, however faithfully it joins.

**Dead-code warning for anyone reading the source:** `processClickEvents()`
and `processImpressionEvents()`, with their `action_name.keyword` term
filters, are defined but never called. The live path is
`getRankAggregatedClickThrough()` → `getClickthroughRate()` → the COEC
calculation. Do not chase the `.keyword` filter: the live passes filter on
ordinal and date only and read `action_name` from each hit.

The arithmetic, from source: pass one computes the store-wide clickthrough
rate at each rank, clicks over impressions at every ordinal within
`maxRank`, aggregated across all events in the window. Pass two accumulates
clicks and impressions per query-and-document pair. A pair's rating is its
clicks divided by its expected clicks (the rank-average rate at its observed
rank, times its impressions), formatted to three decimals; a pair with no
expected clicks rates `0.000`. Note the asymmetry: pass one needs no
`user_query`, so every impression and click in the window shapes the
normalizer, including events the per-query pass cannot read.

## The call shapes

Building a judgment list is a **cluster write under Critical Rule 5**: it
runs the model and stores the result as an entity in the plugin's own
`search-relevance-judgment` index. Announce it, alone in its turn, and run
it on the go-ahead. Reading or listing judgments is free.

Create returns immediately; the build runs asynchronously:

```json
PUT /_plugins/_search_relevance/judgments
{
  "name": "a name the team will recognize",
  "type": "UBI_JUDGMENT",
  "clickModel": "coec",
  "maxRank": 20
}
```

```json
{ "judgment_id": "5f45edbd-9444-4338-9d6d-cf96465cd51e" }
```

`name`, `type`, `clickModel`, and `maxRank` are required. `startDate` and
`endDate` (`yyyy-MM-dd`) are accepted beside them and bound the events
window; unset means unbounded. Set `maxRank` above the deepest
`position.ordinal` the store holds (read the max first), for the reason in
the catalog below.

Missing-field errors, measured, so nobody debugs them as server faults: no
`name` → `Invalid name: Text cannot be null`; no `type` → 400
`Invalid or missing judgment type`; no `maxRank` → a raw 500
`null_pointer_exception` (`Cannot invoke "java.lang.Integer.intValue()"…`).
That NPE is a missing request field, not a broken cluster.

Read one by id, or the list without an id; both answer in search shape,
with the entity under `hits.hits[]._source`:

```
GET /_plugins/_search_relevance/judgments/<judgment_id>
GET /_plugins/_search_relevance/judgments
DELETE /_plugins/_search_relevance/judgments/<judgment_id>
```

The entity:

```json
{
  "id": "5f45edbd-9444-4338-9d6d-cf96465cd51e",
  "timestamp": "2026-08-13T17:51:25.597Z",
  "name": "a name the team will recognize",
  "status": "COMPLETED",
  "type": "UBI_JUDGMENT",
  "metadata": { "clickModel": "coec", "maxRank": 20,
                "ubiEventsIndex": "ubi_events",
                "startDate": "", "endDate": "" },
  "judgmentRatings": [
    { "query": "the typed text",
      "ratings": [ { "docId": "SKU-123", "rating": "2.000" } ] }
  ]
}
```

Read `status` before the ratings; the create returning an id proves
nothing. Its values: `PROCESSING`, `COMPLETED`, `TIMEOUT`, `ERROR`. In
`judgmentRatings`, one entry per query string; `docId` is the events'
`object_id`; `rating` is a string, three decimals. It is not a 0 to 1
scale: `1.000` means exactly as many clicks as expected at that rank, and
above it means more. A single click on a single impression measured
`2.000` where the store's rank-average rate was one half.

## Reading the result: the failure catalog

The judgment list has three ways to be wrong that all arrive without an
error, and one that fails loudly. Most common first:

- **`COMPLETED` with `judgmentRatings: []`:** the model could read no
  event. Measured on a store of 26 events, none carrying `user_query`: the
  build completes, nothing errors, the list is empty. Other causes with the
  same face: no `impression` or `click` rows inside the date window, or
  events landed in an index the build was not pointed at (the entity's
  `metadata.ubiEventsIndex` says which one it read). An empty list is a red
  result to debug, never "no data yet": a single joined
  impression-and-click pair carrying the contract fields produces a
  non-empty list (measured).
- **`COMPLETED`, non-empty, every rating `0.000`:** the rank cutoff. With
  `maxRank` below the deepest impression ordinal, the impressions survive
  while the deeper clicks are filtered out, so every surviving pair rates
  zero. A non-empty, entirely-zero list reads as partial success; it is a
  configuration error. The other store shape with the same face: clicks
  missing entirely, from an impression emitter that works while the click
  emitter does not. Tell them apart with one free read: count `click` rows
  in the window, then compare the deepest `position.ordinal` against
  `maxRank`. Either way, this is why a judgment check passes only on **at
  least one non-zero rating**, never on "the list is non-empty".
- **Ratings present, scored against the wrong documents:** no signature in
  the list at all; the pre-fix tell below is the only detector.
- **HTTP 403 at the call:** the Workbench disabled (the plain-text tell
  under Availability, the default on 3.1), or the security plugin
  denying the user (a JSON `security_exception`). A permission problem
  fails loudly at the call; it never wears the face of an empty `COMPLETED`
  list.
- **The nested-objects limit, at real volume:** the judgment store maps
  `judgmentRatings` as nested inside nested, one nested document per query
  entry and per rating, all inside the single judgment entity. A build over
  real traffic therefore fails with `The number of nested documents has
  exceeded the allowed limit of [10000]` while a 26-event demo passes
  clean. The limit is `index.mapping.nested_objects.limit` on the judgment
  store; raising it is a Critical Rule 5 write. As far as we have found,
  this limit is undocumented.

## The pre-fix tell: behavior whose ids cannot be judged

Queries captured with `object_id_field` omitted got their hit-ID lists
filled with shard-local Lucene doc ids, ids that collide with real
document ids only by coincidence (the `ext.ubi` trap in
[ubi-schema.md](ubi-schema.md)). Ratings are keyed by `object_id`, so a
judgment list built over behavior from that configuration is not empty and
not obviously wrong: it is scored against the wrong documents.

The deterministic tell is on the query rows, which record the omission in
their own `query` field. Before building over accumulated behavior, run:

```json
POST /ubi_queries/_search
{ "size": 0, "track_total_hits": true,
  "query": { "match_phrase": { "query": "\"object_id_field\":null" } } }
```

The `query` field is text-typed, and the phrase matches the recorded
`"object_id_field":null` while a healthy row's `"object_id_field":"sku"`
does not (verified against the live analyzer; a healthy store answers 0).
A count above zero means pre-fix behavior, and its rows' timestamps bound
the affected window.

Behavior from before the fix cannot produce judgments; say so plainly.
Never exclude it silently and never include it silently: put the finding
and the affected window to the room, and once they have heard it, bound the
build with `startDate` at the first day of trustworthy behavior.

## How much behavior is enough

A rating is a ratio of small counts (clicks over expected clicks, per
query-and-document pair), and the three decimals are formatting, not
precision. Concretely: one impression and one click rate a document
`1.000` or more; the next impression halves the rating. Single events swing
a rating across its whole range, and because the normalizer is store-wide,
a pair's rating shifts as the store grows even when the pair itself is
untouched. Store-wide crosses applications, too. Measured: a pair whose
own application held one impression and one click rated `4.000`, not
`1.000`, its expected clicks computed from the whole store's rank curve,
so every surface writing to the stores shapes every other surface's
ratings.

What stabilises a list: impressions accumulating per query-and-document
pair, clicks accumulating at each rank across the store, and breadth of
distinct query strings. The API reports none of these; the entity carries
ratings and nothing about the volume behind them. So read the volumes from
the stores and report them beside the list, in words the room can weigh:
how many events the window holds, how many distinct query strings they
carry, and how many ratings rest on a handful of impressions. A list built
from a day of clicks is noise formatted to three decimals; whether it is
enough is the room's call, made with the volumes in front of them.

## Keeping a check running: scheduled experiments

From search-relevance 3.4 the plugin re-runs an experiment on a cron: a
pointwise evaluation of the app's own search, over query strings sampled from
the team's own `ubi_queries`, scored against the judgment list their clicks
built. Each run's numbers accumulate in a plain index, so a ranking or
catalog change that buries what users choose shows up as a falling score
instead of waiting for someone to look. The API surface is marked
experimental at 3.8 (`@ExperimentalApi` on every scheduling class).

The feature ships on by default
(`plugins.search_relevance.scheduled_experiments_enabled`, a dynamic
setting, `true` from its first release) and needs the
`opensearch-job-scheduler` plugin, which the standard distribution bundles.
Its disabled tell mirrors the Workbench's: every `/experiments/schedule`
endpoint, reads included, answers a plain-text 403
`Scheduled experiments is disabled`. Per the
setting's own contract, disabling refuses new and changed schedules while
experiments already scheduled keep firing. Two more settings bound a run:
`scheduled_experiments_timeout` (default 60m, then the run is canceled) and
`scheduled_experiments_minimum_interval` (default 1s); a cron whose firings
sit closer together than the minimum is rejected at POST.

### The chain: three entities, then the schedule

The schedulable thing is an experiment, and it needs three stored entities.
All four creates are cluster writes under Critical Rule 5, and the visit
announces them as one named setup, run on one go-ahead.

**Query set**, sampled from the captured searches:

```json
POST /_plugins/_search_relevance/query_sets
{ "name": "…", "description": "…", "sampling": "topn", "querySetSize": 20 }
```

`ubiQueriesIndex` beside them points the sampler at a non-default store.
**The default sampler carries browse loads (measured):** `sampling`
defaults to `pptss`, which samples match-all over the first 10,000 query
rows, so on a store where filter-only browsing writes `user_query: ""`, the
empty string lands in the set as a runnable "query". `topn` (most frequent
strings, empties screened) and `random` (empties excluded) both filter it.
Prefer `topn` for a monitoring set (the check should watch the searches
people actually make, weighted by how often they make them), and never
leave the sampling to the default silently.

**Search configuration**, the app's own audited query DSL as a string,
with `%SearchText%` where the typed text goes:

```json
PUT /_plugins/_search_relevance/search_configurations
{ "name": "…", "index": "products",
  "query": "{\"query\":{\"multi_match\":{\"query\":\"%SearchText%\",\"fields\":[…]}}}" }
```

**Experiment**, whose create runs the evaluation immediately and so is
also the check's first data point:

```json
PUT /_plugins/_search_relevance/experiments
{ "querySetId": "…", "searchConfigurationList": ["…"],
  "judgmentList": ["…"], "size": 10, "type": "POINTWISE_EVALUATION" }
```

**Schedule**, five-field UNIX cron only; nightly at 2am is `0 2 * * *`:

```json
POST /_plugins/_search_relevance/experiments/schedule
{ "experimentId": "…", "cronExpression": "0 2 * * *" }
```

`GET …/experiments/schedule` lists every job (`/{id}` reads one);
`DELETE …/experiments/schedule/{id}` unschedules and touches nothing else.
One job per experiment and the job id is the experiment id. The cron fires
on the cluster node's clock, not the caller's; the job records the node's
zone, UTC in a stock container.

Failure shapes, measured: a Quartz six-field cron is a 400 whose message
ends `For example, "12 * * * *"`; a missing `experimentId` is a 400; an
experiment id that matches nothing is a **500** `Failed to find experiment`,
not a 404. Re-POSTing to change a cron is a 500
`version_conflict_engine_exception`; the API never overwrites a schedule.
A change runs as a DELETE then a POST, announced as the one move it is.

### The `_id` precondition: scores join on the document id

The evaluation records each search hit by its **`_id`**
(`SearchResponseProcessor` maps `SearchHit::getId`; nothing points it at
another field), while the judgment list keys ratings by **`object_id`**.
Where the catalog's `_id` is not the same value the app maps as
`object_id`, every metric of every run is `0.0` with nothing errored.
Measured both ways: ids disjoint scored all-zero; the same store with `_id`
equal to the SKU scored NDCG@10 0.63 from the same judgment list. Settle it
by reading before anything is built: one search hit's `_id` against the same
document's `object_id` field value. If they are misaligned, the check
cannot score and the honest answer is to say so. The after-the-fact tell on
a check someone already built is an all-zero history whose evaluation
`documentIds` and judgment `docId`s share no values.

### Reading the runs, and what the check actually watches

Each firing re-fetches the experiment and re-runs it **with the same query
set, search configuration and judgment list**, writing one row per run into
`.search-relevance-scheduled-experiment-history` (`id`, `experimentId`,
`timestamp`, `status`, per-query `evaluationId`s) and the per-query metrics
(`Coverage@k`, `Precision@k`, `Recall@k`, `MAP@k`, `MRR`, `DCG@k`,
`NDCG@k`) into `search-relevance-evaluation-result`, each row carrying the
original experiment's id and the run's own timestamp. No API reads the
history index; read it, and the whole time series, by searching the
indices directly: the series is one query on
`search-relevance-evaluation-result` filtered by `experimentId`, sorted by
`timestamp`.

**The metrics are normalized against the judged set, never the catalog.**
`NDCG@k`'s ideal ranking is built from the query's whole rating list —
every judged document, sorted by rating, truncated to `k` — not from the
page the engine returned; the calculator is handed the returned ids and
never reads them. On a list their own clicks built, the judged set is the
documents behavior has already touched, so `1.000` means the search
returned the best-rated of *those* in the best order — and a document no
ranking ever showed is missing from the ideal as well as from the ratings,
so never returning it costs the score nothing. **Read `Coverage@k`
first**: the share of the returned page carrying any rating at all is what
says how much a high score means, because a high score over a thinly
judged page is the same arithmetic saying less. There is no
reliable-coverage line to quote — the plugin's source marks its own
threshold undecided and names UBI data as the case it worries about — so
report the coverage beside the score, as the volumes are reported beside
the list.

The frozen references are the design's honest limit: the check watches
**ranking drift against a snapshot of what users chose**. Its numbers move
when the search or the catalog moves; they do not move as behavior
accumulates, because a judgment list is immutable, a rebuild returns a new
id, and `PATCH /experiments/{id}` updates name and description only.
Pointing the check at fresher behavior is therefore: build a new judgment
list, create a new experiment over it, schedule that experiment, and delete
only the old **schedule**. Never delete the old experiment to "clean up".
**Deleting an experiment cascades (measured): its schedule, its entire run
history, and every evaluation row go with it.** The experiment entity is
custodian of the record; the record dies with it.

## Sources

- Plugin source, tag 3.8.0.0:
  [opensearch-project/search-relevance](https://github.com/opensearch-project/search-relevance):
  `judgments/clickmodel/coec/CoecClickModel.java` (the five fetched
  fields, both ordinal filters, the date window, the dead code, the rating
  arithmetic), `model/Judgment.java` and `model/AsyncStatus.java` (entity
  fields, status values), `mappings/judgment.json` (the nested-in-nested
  ratings shape behind the volume trap). For scheduling:
  `rest/RestPostScheduledExperimentAction.java` and `utils/CronUtil.java`
  (body fields, UNIX cron type, both 403 gates),
  `scheduler/ScheduledExperimentRunnerManager.java` (a firing re-runs the
  stored experiment with its stored references),
  `executors/SearchResponseProcessor.java` (hits recorded by
  `SearchHit::getId`, the `_id` precondition),
  `rest/RestPatchExperimentAction.java` (name and description only),
  `transport/experiment/DeleteExperimentTransportAction.java` (the cascade),
  `ubi/ProbabilityProportionalToSizeQuerySampler.java`,
  `ubi/RandomQuerySampler.java`, `ubi/TopNQuerySampler.java` (which
  samplers screen the empty string), and
  `settings/SearchRelevanceSettings.java` (the three settings and their
  defaults). Feature floor read at the tags: the `scheduledJob` transport
  package is absent at 3.3.0.0 and present from 3.4.0.0, with the enable
  setting's literal `true` from 3.4.0.0.
- Plugin source for the normalization. `metrics/calculator/Evaluation.java`
  read at every tag 3.1.0.0 through 3.8.0.0: `calculateIDCG` reads
  `judgmentScores.values()` and never the `docIds` it is handed (two file
  revisions across the range, identical in this respect). Upstream's
  `EvaluationTests` at 3.8.0.0 pins the flavour without a cluster, asserting
  `NDCG@5` `0.51` and `NDCG@8` `0.40` over 20 judged documents of which only
  the first five were returned; the `0.77` a local ideal gives on that same
  data is derived here, not asserted there. `metrics/EvaluationMetrics.java`
  at 3.8.0.0 for the `Coverage@k` fraction and the undecided
  reliable-coverage threshold, in the source's own `TODO`. Recall, MRR and
  DCG arrive at 3.6.0.0, which also adds the dynamic Precision/MAP
  threshold, so those three do not compare across that boundary; NDCG takes
  no threshold and is unaffected.
- Live measurements 2026-08-13 against OpenSearch 3.8.0 with
  opensearch-search-relevance 3.8.0.0: every call, response, and error
  shape quoted above; the empty-list and populated results; the disabled
  tell; the pre-fix tell query against a healthy store.
- Live measurements 2026-08-14, same cluster: the scheduling chain
  end-to-end (three on-the-minute firings, each writing a history row and
  fresh evaluation rows); the default sampler carrying `user_query: ""`
  into a query set while `random` and `topn` excluded it; all-zero metrics
  with `_id` disjoint from `object_id` and NDCG@10 0.63 from the same
  judgment list once they matched; both plain-text 403 tells; every failure
  shape quoted above; the version conflict on re-POST; and the cascade:
  deleting the experiment emptied the jobs, history, and evaluation indices
  in one call. All probe entities and the probe index were deleted after.
- Docs: [Search Relevance Workbench](https://docs.opensearch.org/latest/search-plugins/search-relevance/using-search-relevance-workbench/)
  and the judgments subpage. Bundling floor: the standard-distribution
  manifests, where the OpenSearch-side `search-relevance` plugin first
  enters at 3.1.0. (The Dashboards-side `dashboards-search-relevance`
  ships from far earlier; it is not the plugin that builds judgments.)
  Default-enable floor read from the setting's own literal at each release
  tag (`SearchRelevanceSettings.java`: `false` at 3.1.0.0, `true` from
  3.2.0.0). The Javadoc above the setting still claims it defaults off;
  read the `boolSetting` literal, never the comment.
