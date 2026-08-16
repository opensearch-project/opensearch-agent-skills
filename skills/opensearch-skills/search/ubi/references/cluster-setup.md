# Cluster setup: the writes that are the same on every app

Pinned against UBI plugin 3.8.0.0 on OpenSearch 3.8.0, measured against a live
cluster on 2026-08-09 and extended on 2026-08-13. Read this at the Preflight
gate, before the session's first cluster write.

**Four cluster writes never vary with the application**: initializing the two
stores, the probe that proves they accept writes, the retention pass that
stops the event store growing without bound, and the saved-objects import
that puts the metrics on a dashboard. Same endpoint, same body, same success
test, every app — the retention window is the one number that differs, and it
arrives as a variable rather than as a rewrite. So they are written once into
the repo as a setup script a team re-runs on its next environment, rather
than improvised one request at a time where they can be neither reviewed nor
run again. That file is what this reference governs, and
[Critical Rule 2](../SKILL.md#critical-rules-must-follow) counts it,
alongside the plan file, as what the session leaves in the repo.

The instrumentation never joins it. What an app captures, where its emitters
sit, how its search call is built: all bespoke, and it stays in the app's own
code.

## What the session needs, and at which version

One row per external dependency, floors stated per capability. Everything
past the core session carries its own floor, so a cluster below one loses
that capability rather than the session, and the session names what is
missing instead of degrading quietly.

| Dependency | What it carries | Floor |
| --- | --- | --- |
| The app's own source, in the workspace | the whole session; UBI captures nothing passively | none |
| UBI plugin (`opensearch-ubi`) | the core session: capture, the joins, Verify | in the standard distribution from **3.1**; separately installable from **2.15**. A managed service that cannot run the plugin (an Amazon OpenSearch Service domain today) takes [the managed path](#the-managed-path); Amazon OpenSearch Serverless is not supported |
| OpenSearch Dashboards | the Dashboard step, and the dashboard re-runs after it | saved-objects import surface pinned and verified against **3.8.0** ([dashboards.md](dashboards.md)) |
| `opensearch-search-relevance` | the judgments visit | in the distribution from **3.1**; on by default from **3.2**; on 3.1 present but off until one dynamic cluster setting ([judgments.md](judgments.md)) |
| search-relevance scheduled experiments, plus `opensearch-job-scheduler` | keeping the judgment check running on a cron | search-relevance **3.4**; the job scheduler ships in the standard distribution ([judgments.md](judgments.md)) |
| ml-commons with a text-embedding model | the per-intent report, and nothing else in the session | present and a model deployed; no version floor of its own here ([intent-labels.md](intent-labels.md)) |

**The shared 3.1 arrival is a coincidence, and nothing follows from it.**
`opensearch-ubi` and `opensearch-search-relevance` are separate plugins with
separate entries in the cluster's plugin list; a cluster can carry either
without the other, so look each one up under its own name — one plugin's
presence is never evidence about the other's. And finding an entry is where
that row's floor starts, not where it ends: `opensearch-search-relevance` is
in the list on 3.1 and still off.

## What it covers, and what it refuses

Covered: store initialization, the probe cycle, the retention pass, and the
saved-objects import; on the managed path, the manual store creation that
stands in for initialize, and the pipeline YAML under
`.opensearch/pipelines/`. Three things are left out on purpose:

- **The malformed-store repair.** It always deletes an index, which may hold
  real data, and whether that data is worth keeping is the user's call, never
  the session's. The script detects the malformed store and stops there.
- **The plugin install.** A cluster operation rather than an application one:
  the cluster serves other things, and installing into it is not this repo's
  setup.
- **IAM.** Roles and access policies outlive the app and belong to whoever
  administers the account.

## Where it lives

`.opensearch/ubi-setup.sh` at the app repo's root; `.opensearch/` is the
directory the family already uses for generated pipeline YAML and chunk sets.
Read the project's own context for a convention that overrides that, the way
[Step 5](../SKILL.md#step-5-implement) does before writing instrumentation: a
repo with its own task runner gets the entry point there, and the script
under `.opensearch/` is what the runner calls.

**The path is pinned so a returning session finds the artifact before writing
one** — a second copy somewhere nobody recorded is the duplicate the pin
exists to prevent. Two checks before writing into it: `.opensearch/` must not
be gitignored (a repo that generates chunk sets there often ignores the
directory wholesale, and an artifact Critical Rule 2 calls durable is not
durable if git never sees it; the cheap fix is a negated ignore rule for this
one file), and where the repo genuinely keeps its committed scripts
elsewhere, put it there and say plainly where it went.

## The contract

**It is idempotent.** Running it against a cluster that is already set up
changes nothing and still exits 0. Measured: a second
`POST /_plugins/ubi/initialize` left both index UUIDs and every existing
document untouched. Re-runnable is the whole point of the artifact, so
anything that would only be safe once does not go in it.

**Its success test is the state it produced, never the response it got.**
Both APIs it calls report failure inside a successful-looking answer:

- `POST /_plugins/ubi/initialize` answers `200 {"message": "UBI indexes
  created."}` whether it created anything or not; measured on 3.8.0.0, both
  on a second run and over a store it left malformed (below).
- The saved-objects import answers `200` with `"success": false` in the body
  ([dashboards.md](dashboards.md)).

So each step reads back the thing it claims: the store's own mapping, the
import's `success` field. A script whose test is `%{http_code}` passes on a
cluster where nothing happened.

**No credentials in the file.** It is committed. The endpoint and the
authentication come from the app's own configuration — the environment
variables or config file the Audit found — read at run time; the Dashboards
address comes from configuration too, since the app's config does not carry
it. A script that carries a password is a leak this session created.

**Every step says what it did and what it found, and a failure exits
non-zero.** Silence and success look identical otherwise, which is the
failure mode of all three operations below. A successful run ends with one
closing line naming what it verified (the stores whose mappings it read back,
the probe it cycled): that line is the evidence
[Step 5](../SKILL.md#step-5-implement) quotes before any instrumentation is
written, and pinning it here makes the evidence the script's own output
rather than the session's recollection of having run it. Its wording belongs
to the generated file.

**The Critical Rule 5 announcement covers the file and the run together, and
both wait on it.** Writing the file is a repo change; running it is the
cluster write; either is the user's to refuse, so the announcement opens a
turn of its own — say what the script will do and what will land in the repo,
then stop. Writing it and running it are what the next turn opens with. (A
script is a natural thing to write while explaining it, which is how this
gate gets lost; arriving as a postscript to the Audit's closing questions is
the other way.)

## Initializing the stores

`POST /_plugins/ubi/initialize`, then read both mappings back and check them
against the store tables in [ubi-schema.md](ubi-schema.md): `ubi_queries`
`dynamic: false` with `query_attributes` as `flat_object` and `timestamp` as
`strict_date_time`, `ubi_events` carrying the shipped field set. The read can
answer 404 for a fraction of a second after the initialize returns; retry
briefly before calling it a failure.

**Initialize does not repair.** Measured against a `ubi_queries` that dynamic
mapping had auto-created: initialize returned `200 {"message": "UBI indexes
created."}` and left the store exactly as it found it — still dynamic, still
`query_attributes` as an object with a `text` subfield, joins still broken.
Re-running initialize is the obvious move on a malformed store, and it is the
move that reports success while changing nothing. The script names what it
found and stops; the repair is the session's, with the user, under Critical
Rule 5 and the trap in [ubi-schema.md](ubi-schema.md).

## The probe cycle

Index one document into `ubi_events` at a fixed `_id`, `POST
ubi_events/_refresh`, search for it, delete it, refresh again.

**The refresh is not optional.** Measured: the search finds nothing before it
and finds the document after. Without it, "confirm it is searchable" is
decided by where the write happened to land in the default one-second refresh
interval.

**The probe document carries only fields the shipped mapping declares**:
`application`, `action_name`, `query_id`, `client_id` and `timestamp`, with
values that say plainly this is the probe. This is what makes an improvised
probe expensive. Measured: a probe carrying `probe: true` and
`probe_id: "abc-123"` added both names to `ubi_events`' mapping, `probe_id`
as `text` with a `.keyword` subfield, and deleting the document did not
remove them. A mapping entry is permanent, and only a reindex changes a
field's type, so a one-off probe mutates the store it was testing for good.

**The fixed `_id` is what makes the cycle re-runnable**: a second run
overwrites rather than accumulating, and a probe stranded by an interrupted
run is found and cleared by the next one. This is the single cluster write
Critical Rule 5 exempts, and it earns the exemption by cleaning up after
itself — a property of this cycle rather than of the idea of a probe. It
holds because `ubi_events` is one concrete index and stays one; the Retention
section below is where that stops being an accident and becomes a constraint.

## Retention

The skill instruments impressions, so `ubi_events` takes one document per
rendered result, on the cluster the application searches — and nothing else
in the session says how long any of that lives. The answer is not small.

**Measured**, on a bed holding 501,960 searches against a 1.2-million-document
catalog: 5,596,711 events, of which 5,001,339 were impressions (ten per
search, one per result on a ten-result page), occupying 593 MB beside
`ubi_queries`' 299 MB. Per search that is about **1.8 KB across the two
stores, or 1.8 GB per million searches**, before replicas; the event store
had passed the catalog's own document count more than four times over. It
grows with traffic, and traffic is not bounded by anything the team controls,
which is why the number belongs in front of the room rather than in a month's
disk-usage alert.

### Not ISM, and the reason is the judgment path

Index State Management is the obvious answer and the wrong one here. ISM has
no delete-by-query action (a policy carrying one is refused outright,
`400 Invalid field: [delete_by_query] found in Actions.`) and its `delete`
action removes a whole index, so trimming by age pushes you into rollover:
the store becomes an alias over numbered backing indices.

**That layout breaks Verify check 6.** Measured on 3.8.0 with
opensearch-search-relevance 3.8.0.0: with `ubi_events` an alias over two
healthy backing indices holding 4,260 events, `PUT
/_plugins/_search_relevance/judgments` fails
`500 search_relevance_exception: UBI events index does not exist`. The check
behind it resolves neither the alias nor a wildcard: `ubi_events` and
`ubi_events-*` are both refused, while `ubi_events-000001` and
`ubi_events-000002` are each accepted through the request's `ubiEventsIndex`
field. So the workaround is worse than the failure: naming one backing index
builds a judgment list over one slice of the behavior, the exact opposite of
the accumulation the judgments visit rests on. Both slices here rated the
same 10 query strings, each seeing half the events and neither saying so.

**Rollover is a trap twice over**, and the second one is quieter: it copies
neither the mapping nor the settings of the index it rolls, building the new
backing index from matching index templates alone, and from nothing at all
where none matches. Measured: a rolled `ubi_events-000002` arrived with zero
mapped properties, its first event dynamic-mapped `client_id` and
`user_query` as `text`, and `term` on `client_id` then answered **0 hits with
no error**. Templates fix that one. Nothing fixes the first.

**So the stores stay concrete, and `ubi_events` keeps its name.** Everything
downstream depends on that name: the Workbench reads it, the metrics plan's
queries name it, the dashboard's index pattern is titled after it.

### What retention is instead

A delete by age, run on a schedule the team owns:

```json
POST /ubi_events/_delete_by_query?refresh=true
{"query": {"range": {"timestamp": {"lt": "now-<the agreed window>"}}}}
```

The same call against `ubi_queries`, which grows a row per search rather than
per result and is the smaller of the two. Measured: 2,976 of 4,260 events
removed in 154 ms with no failures, and a judgment list built afterwards
completed over what remained — the same 10 query strings, the same 11 ratings
above zero. **That is the check this design exists to pass**, so run it that
way round: a retention pass, then a build, before anyone believes the pass is
safe.

Two honest limits. Deleted documents leave search immediately but stay on
disk as tombstones until a merge reclaims them, so the space comes back later
than the rows go (`docs.deleted` in `GET ubi_events/_stats` shows it;
`_forcemerge?only_expunge_deletes=true` clears it on demand). And OpenSearch
will not schedule this: ISM cannot express it, and Alerting notifies rather
than writes. The artifact carries the command; the team's own scheduler runs
it, the same way the artifact itself is a file they run rather than a thing
that runs. Say that plainly rather than leaving them to discover that nothing
is calling it.

### The window is the room's

The window is a business decision and belongs to
[Step 4: Map](../SKILL.md#step-4-map), beside the metrics and the
`client_id`'s lifetime. It is not a default: no window lands without a number
the room gave, and the delete is a cluster write like any other, announced
under Critical Rule 5.

**A short window is not a free choice, and the cost is not disk.** Implicit
relevance judgments are built over *accumulated* behavior — impressions
piling up per query-and-document pair, clicks accumulating at each rank,
breadth of distinct query strings ([judgments.md](judgments.md)) — so the
window is a ceiling on how good the judgment list can ever get, and one
nobody meets an error at. A team that keeps 14 days has decided, whether or
not anyone said so, that the visit which turns their clicks into judgments
will always run on 14 days of clicks. Put the two costs side by side when
agreeing: holding it longer costs storage, which is a bill; holding it
shorter costs evidence, which is not recoverable later.

Unlike almost everything else at the gate, this step cannot be written before
the number exists. The artifact gains it when Map settles the window, and a
gate that runs before then writes the file without it, the same growth the
dashboard import already has.

### Erasure

Retention expires everyone at once; erasure is one person, on request. It is
the same mechanism under a different predicate, which is most of why it is
here: `_delete_by_query` on their `client_id` instead of on `timestamp`,
against both stores. Only the app can turn a person into that id, because
Critical Rule 3 keeps the stores' identifiers opaque by design.

That is an obligation a persistent `client_id` creates and a per-visit one
does not: rows nobody can link back to a person are already unlinkable, and
there is nothing to erase against. Which of the two the mapping chose is
settled at Map, so say there which one it is, and where the bridge from
person to id lives if it is the persistent one.

## The saved-objects import

`POST <dashboards-url>/api/saved_objects/_import?overwrite=true`, an
`osd-xsrf` header, the ndjson sent as multipart `file` under a filename
ending `.ndjson`. Success is `"success": true` **in the body**. The object
shapes, the three ways the call fails outright, and the blank first paint are
all in [dashboards.md](dashboards.md); what belongs to the script is that it
reads the body rather than the status line.

**The ndjson is an argument, not a member of the artifact.** Critical Rule 2
makes it transport that does not outlive the attempt: deleted when the import
lands and equally when it fails or the user declines it, so re-running the
import means regenerating it from the plan first. The script is durable; its
input is not. Everything around the call — reading the `ubi*` objects already
on the cluster, the announcement, the gate that reconciles each metric's
query against the stores before any panel exists — belongs to
[Step 7](../SKILL.md#step-7-dashboard). The script performs the call.

## The managed path

A cluster without the plugin has no initialize endpoint, so the two stores
are created by hand: `PUT /ubi_queries` and `PUT /ubi_events`, each body a
`{"mappings": …}` wrapper around the matching mapping vendored in
[ubi-schema.md](ubi-schema.md). Measured on 3.8.0: the mappings that come
back are identical to the ones the plugin's initialize produces. The index
settings are not (the plugin also sets auto-expanding replicas and a recovery
priority), and nothing about the join depends on either.

The pipeline YAMLs under `.opensearch/pipelines/` are part of this artifact
rather than files nothing accounts for. Creating pipelines from them stays
where it is, in [aws-managed.md](aws-managed.md): `aws osis create-pipeline`
is already an exact command, and it bills per OCU-hour for as long as the
pipeline runs, which makes it an announcement rather than a step a script
repeats.

**The probe on this path goes through the queries pipeline** (a JSON array,
SigV4 for service `osis`), and pipeline buffering makes the confirmation a
poll of `ubi_queries` rather than one refresh. The fixed `_id` does not
survive the crossing: the sink in [aws-managed.md](aws-managed.md) names an
index and no document id, so OpenSearch assigns one. Identify the probe by a
field value instead, a `query_id` unmistakably its own, and delete what that
matches. It has to be a *declared* field: `ubi_queries` is `dynamic: false`,
so a marker invented for the probe reaches `_source` and is never indexed
([ubi-schema.md](ubi-schema.md)), and polling for one waits out its timeout
on a record that arrived. A row not yet arrived is not a red check.

**Retention crosses unchanged**, which is the one thing the delete-by-query
design makes easy: the stores are the same two concrete indices,
`_delete_by_query` is an ordinary API call on them, and there is no alias for
a pipeline sink to disagree with. What differs is the scheduler: a domain has
no more cron than a self-managed cluster does, so the call belongs wherever
the team already runs scheduled work against the domain.

## Running it is what turns the gate green

The artifact is written at the Preflight gate, before Implement, and that is
not a breach of Critical Rule 1: the rule fences the *instrumentation* behind
a green preflight, and this is the file whose run turns the preflight green.

**The gate re-runs every session, and an artifact that is already there is
run, not rewritten.** It is a repo file the user may have edited (pointed at
their own configuration, folded into their task runner), and regenerating it
over their changes is the thing Critical Rule 2 refuses for the plan file,
for the same reason. Read it, run it, and raise a difference with them rather
than resolving it silently. What it does not yet cover, it gains: the
retention step lands once Map has agreed a window, and a first dashboard
import adds another, to a file the earlier session left holding two.

**The gate's checks are then satisfied by running it, not by writing it.** A
setup script nobody executed is the same unearned claim Critical Rule 4
refuses everywhere else in this session. Say what it is when it has run: a
file in their repo, taking their configuration, that stands these stores up
on the next environment without this conversation.
