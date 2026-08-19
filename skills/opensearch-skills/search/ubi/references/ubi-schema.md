# UBI schema and protocol reference

Pinned against UBI plugin 3.8.0.0 (OpenSearch 3.8.0) and UBI Specification
1.3.0, read from the plugin's source and shipped mappings, 2026-08-06. Where
this file and other UBI documentation disagree, this file follows the source;
the traps below exist because parts of the official docs lag it.

## The two halves

- **Queries (server side):** a search request whose `ext` block contains a
  `ubi` section is captured by the plugin and indexed into `ubi_queries`
  automatically. The application never writes to `ubi_queries`.
- **Events (client side):** the plugin captures no events. The application
  writes event documents into `ubi_events` from its own code at each user
  action. [Emitting events](#emitting-events) is the transport contract; the
  official `ubi.js` collector (single file, in the plugin repo under
  `ubi-javascript-collector/`) is an optional starting point, measured
  against that contract there.

## The `ext.ubi` request block

```json
{
  "ext": {
    "ubi": {
      "query_id": "an id for this exact query execution",
      "user_query": "the text the user actually typed",
      "client_id": "opaque id for this browser/device or visit",
      "application": "which app issued the search",
      "object_id_field": "required: index field with the external result id",
      "query_attributes": { "any": "key/value context, e.g. experiment id" }
    }
  },
  "query": { "…the normal search body, unchanged…": {} }
}
```

Every field is optional to the plugin (the `ubi` section's presence alone
triggers capture; an omitted `query_id` becomes a generated UUID), but treat
`object_id_field` as required, and point it at a **string-typed** field. Its
two failure modes:

- **Omitted: the hit-ID list silently fills with Lucene doc ids.** The
  plugin README says omission falls back to the document `_id`; the source
  writes the shard-local Lucene doc id instead (`String.valueOf(hit.docId())`,
  `UbiActionFilter.java`). Measured: a search whose three hits were `_id`
  `1`, `2`, `3` recorded `["3", "7", "11"]`. Those overlap real ids only by
  coincidence, so the click-to-results join is meaningless with no error
  anywhere: Verify check 3 fails, or falsely passes on a collision. The
  row's own `query` field records the omission (`"object_id_field":null`).
- **Numeric-typed: the application's own search returns HTTP 500.** The
  plugin casts the field's value to `String` without checking the mapping,
  so an `integer` or `long` id throws `class_cast_exception` inside the
  search path and the search returns nothing at all — the one UBI failure
  that is loud and takes the application down with it. Measured 2026-08-13
  on a storefront whose `id` was mapped `integer`; pointing at the `keyword`
  `sku` beside it fixed it outright. An integer primary key is the common
  case and usually the field the Audit surfaces first, so read the
  candidate's mapped type before proposing it; where the natural id is
  numeric, pick the string-typed alternative beside it.

`application` is accepted even though the README's parameter list omits it.
The search **response** echoes back one field, `ext.ubi.query_id`; that echo
is what the app forwards to its event emitters as the join key.

## Emitting events

Everything in this section is the contract this skill holds an application's
emitters to, not plugin behavior: UBI enforces none of it, and nothing
downstream notices when it is wrong.

**A page of results is one write, not one write per result.** Impressions
arrive in bundles by nature (24 rendered cards are 24 events raised in the
same instant), so they travel as a single `_bulk`, action line and document
line per event, the body ending in a newline:

```
POST /ubi_events/_bulk
{"index":{}}
{"action_name":"impression","query_id":"…","user_query":"…", …}
{"index":{}}
{"action_name":"impression","query_id":"…","user_query":"…", …}
```

`_bulk` answers `200` even when every item was rejected; a refused event
appears only as `errors: true` and a per-item `status` in the response body.
Read the body, not the status code.

**The emitter never blocks the action it observes.** The grid paints, the
click navigates, the cart updates; the events travel beside them. But
fire-and-forget loses the event on a click that navigates away, because the
browser cancels in-flight requests on unload. An emitter on a navigating
action needs a transport that survives unload — `navigator.sendBeacon` or a
`fetch` with `keepalive: true` — not an `await` holding the navigation open.
Both cap the body at 64 KiB and `sendBeacon` sets no request headers; that
suits the single-event click, while the page-sized batch belongs on the
impression path, which renders rather than navigates.

**A failed emit is swallowed at the user's surface, and visible to the
developer.** No toast, no error boundary, no blocked interaction:
instrumentation that can break the thing it measures is worse than none. But
route the failure to the console or the app's own logs — an emitter that
fails quietly everywhere is one nobody can debug, and Verify's row-by-row
checks are what prove it works at all.

**Browser-raised events go through the app's own backend.** Writing to
`ubi_events` from browser code ships cluster credentials to every visitor:
scoped to that one index, they still let anyone with the page write whatever
they like into the store the metrics are computed from; scoped like the
app's search credentials (the ones actually at hand), they reach whatever
search reaches. Direct writes also need the cluster's CORS opened to the
app's origin (`http.cors.enabled` is off by default). So the browser posts
to an endpoint the app already serves, and the backend issues the `_bulk`
under the credentials it already holds for search; actions the backend
observes itself need no relay at all. The managed path lands on the same
shape with a second reason on top — SigV4 cannot be signed in a browser
([aws-managed.md](aws-managed.md)) — so it is one contract, not two.

**What `ubi.js` settles, and what it leaves.** Read on `main` 2026-08-13.
It assumes the relay shape (its constructor takes a `baseUrl` commented
*"point to the specific middleware endpoint for receiving events"*) and its
`_post` catches everything into `console.error`, so a failed emit reaches
the developer and never the caller. What it leaves: it documents the relay
without enforcing it (the constructor appends `/ubi_events` to whatever it
is handed, so a cluster address fits the slot as readily as a middleware
one); it POSTs one event per request (`JSON.stringify([event])`, the Data
Prepper array shape — a 24-result page is 24 requests); it offers nothing
that survives unload; and its `UbiEvent` class declares no `user_query`, so
an app emitting its objects unchanged writes rows the Workbench skips (the
every-event rule under `ubi_events` below).

## Store schemas

### `ubi_queries` (written by the plugin, `dynamic: false`)

| Field | Type | Content |
|---|---|---|
| `timestamp` | date (`strict_date_time`) | when the query was captured |
| `query_id` | keyword | the join key |
| `query` | text | the raw query DSL, as a string |
| `user_query` | keyword | the user's typed text |
| `query_response_id` | keyword | unique id of this response |
| `query_response_hit_ids` | keyword | the returned objects' ids, in order |
| `query_attributes` | flat_object | the request's `query_attributes` |
| `client_id` | keyword | as sent in the request |
| `application` | keyword | as sent in the request |

**Naming trap:** the hit-ID list is `query_response_hit_ids`. The plugin
README says `query_response_object_ids` and the docs site says
`query_response_objects_ids`; both are stale, and with `dynamic: false` a
query written against a stale name doesn't error — it matches nothing.

### `ubi_events` (written by the application, dynamic mapping)

| Field | Type | Content |
|---|---|---|
| `application` | keyword | same value the queries carry |
| `action_name` | keyword | what the user did; see standard names below |
| `query_id` | keyword | the join key, from the search response echo |
| `client_id` | keyword | same value the query carried |
| `timestamp` | date | when the event occurred, ISO 8601 |
| `message_type` | keyword | logical bin for actions, e.g. `CONVERSION` |
| `message` | keyword | optional human-readable note |
| `user_query` | keyword | the typed text, carried on the event (required, see below) |
| `event_attributes.object.object_id` | keyword | the external id of the acted-on result |
| `event_attributes.object.object_id_field` | keyword | which index field that id lives in |
| `event_attributes.object.internal_id` | keyword | optional: the OpenSearch `_id` |
| `event_attributes.object.name` / `.description` / `.object_detail` | keyword / text / object | optional object context |
| `event_attributes.position.ordinal` | integer | 1-based rank of the result acted on |
| `event_attributes.position.x` / `.y` / `.page_depth` / `.scroll_depth` / `.trail` | integer / text | optional richer position context |

**Every event row carries `user_query`.** The Search Relevance Workbench's
COEC click model groups clickthrough rates by that string **read off the
event row** — it performs no join to `ubi_queries`. An event without the
field is skipped hit by hit at warn level, with no error and no count of
what was dropped, and the judgment build completes with an empty list.
Measured on a store of 26 events, none carrying it
([judgments.md](judgments.md), which also holds why `position.ordinal`
belongs on every click). The field is `keyword` in the shipped mapping, so
carrying it costs no mapping change and no reindex.

**A custom field must be declared `keyword` before the first event is
written.** The shipped mapping declares exactly the fields above and sets no
root `dynamic`, so anything else an event carries (a top-level `session_id`
or `user_id`, any custom key under `event_attributes`) is typed by
OpenSearch's own rules on arrival, and a string typed that way becomes
`text` with a `.keyword` subfield, never plain `keyword`. Aggregating on it
fails loudly: `terms` and `cardinality` over `text` raise
`illegal_argument_exception`. Filtering fails silently: the analyzer splits
`abc-123` into `abc` and `123`, so `term` on `session_id` matches nothing
and reports no error, while `term` on `session_id.keyword` matches. Every
hyphenated id and every UUID behaves this way; a one-token lowercase value
like `search` matches anyway and hides the trap. Once a field is mapped,
only a reindex changes its type. Novel names are also permanent mapping
entries, so keep attribute names to the approved mapping's set.

### Standard action names (spec 1.3.0 enum)

`impression`, `click`, `view`, `watch`, `add_to_cart`, `purchase`. Free
strings are allowed; these six are what downstream consumers read without a
translation layer. An `impression` is one result shown to the user — one
event per result **per search**, each with its `position.ordinal`; a
`click` is the user selecting a result (`object_id` + `ordinal`); `view` is
examining a result in detail. The spec requires `action_name` and
`timestamp` on every event; joinability additionally demands `query_id`,
and Workbench readability demands `user_query` on every event and
`position.ordinal` on every impression and click.

**Once per result per search is the emitter's job.** A re-render, a route
change back to the results, or a scroll re-entering an already-seen card
re-fires a bare `IntersectionObserver`; the emitter must carry the seen-set
itself, keyed by `query_id`. Measured 2026-08-13: one search accumulated 32
impressions for 24 results, eight of them a single scroll back over the
grid, and the store looked healthy afterwards. Duplicates inflate the
denominator of every rate on the metrics plan, and because the COEC click
model normalizes against a store-wide clickthrough rate at each rank
([judgments.md](judgments.md)), they also drag ratings for pairs nobody
touched. The check is one count against another: impressions under a
`query_id`, versus distinct `object_id`s under it.

### How far the join reaches

`purchase` and `add_to_cart` are in the enum, so a search-attributed
purchase count looks computable and the confirm button genuinely is an
audited UI action. What is weaker than it looks is the join underneath, and
no stored row says which strength you have.

The published model: OpenSearch's docs say the client "indexes all user
events with the specified `query_id` until a new search is performed", with
`sessionStorage` as the carrier — **last-search-wins, sticky, tab-scoped**,
no page boundary, no expiry. On the results page that is exact, because
there the last search and the search that produced the clicked result are
the same event. Past the results page the rule keeps answering anyway, four
ways, all silent:

- A visit that searched once, then browsed to something else and bought it,
  attributes that purchase to the search.
- A cart filled from three searches carries the last one on every line.
- A search in one tab and a checkout in another share no `sessionStorage`:
  an orphan row, or no row at all where the emitter guards on the id being
  present.
- Nothing clears the id at a conversion, so the next one inherits it.

Nothing published demonstrates the far half: the reference storefront has no
product page, cart, or checkout and emits no `purchase`; the docs' worked
journey runs search → purchase under one `query_id` across 136 ms of
generated data; and the collector the docs name as the carrier holds no
session state at all. For contrast, Algolia bounds this same join — a
conversion's query id must fall within an hour of the search, ids older
than four days are rejected, and attributed and plain conversions are
different event types. UBI has neither bound nor split: `query_id` is
optional since spec 1.1.0, and an unattributed conversion is told from an
attributed one only by whether the field happens to be filled.

So the row that joins exactly is the result click, and it is the one
already being mapped. Name a money outcome plainly when the table is
confirmed — the UI action exists, the join back to a search does not — and
put the reachable row nearer the search on the table instead.

**A team that wants the funnel does not need the id to travel.** The
conversion is already a row in the order table, which knows the customer,
the product, and the money this schema has no field for. Attribution is a
read across the two: for each purchased product, the most recent earlier
`click` on that same `object_id` by that same `client_id`; its `query_id`
names the search that earned it. Both fields are already `keyword` in the
shipped event mapping, so it costs no propagation and no mapping change,
and a purchase nobody reached by search finds no click and stays
unattributed — an unattributed remainder the team can print, where a
missing event is only a quiet day. Its limits: credit is last-touch per
product; the two sides must name the customer the same way, which is the
durable-`client_id` choice below and the erasure obligation that comes with
it; and it reaches back only as far as that id survives, so the total is a
deliberate undercount.

Only per-line credit, or attribution across visits, needs the id itself to
travel, and that build is the team's, not this session's: bind the
`query_id` to the **item** when it is chosen from a result set, onto the
cart line and into the order record, never to the visit. (The other
published carrier, a `query_id` in the result link's URL, binds to the item
for free and survives a new tab, but travels wherever the link is pasted or
shared, earning someone else's search a conversion; if used, read it once
at the landing and drop it from what is stored.) Every option here credits
the last search that touched the item; first touch is the same binding with
a never-overwrite rule. Whatever gap is allowed between the search and the
sale is part of the number, and is written down beside it.

### Identity semantics

- `client_id`: the client issuing the query, as an opaque id. Its lifetime
  is a choice, not a schema fact: persisted client-side (a cookie or
  `localStorage`) it is stable across visits; generated per visit (a
  session cookie or `sessionStorage`) it counts visits. Either way it must
  survive navigation within the visit: an id held only in memory dies on
  every full page load, so a multi-page app would mint one per page view.
  Neither store requires the field (spec 1.3.0 requires only `user_query`
  on a query request); the plugin captures normally without it, indexing an
  empty string while the `query_id` join is untouched. What a per-visit id
  costs is every measure that spans visits: retention,
  new-versus-returning, cross-visit conversion, and `cardinality` on
  `client_id`, which then counts visits rather than people and reports no
  error. What a persistent one costs is an obligation: rows traceable to a
  person must be erasable on request — the delete is in
  [cluster-setup.md](cluster-setup.md), beside the retention window that
  decides how long any of these rows live at all.
- `session_id`: one per visit (regenerated per browser session).
- Both must reach queries and events from the same generation points, so
  the values agree across the two stores.

`client_id` is `keyword` in both shipped mappings. `session_id` is in
neither, and the two stores fail it differently. On the event side it
text-maps, with the consequences above. On the query side it never arrives:
the plugin reads only the listed `ext.ubi` keys, and `queries-mapping.json`
is `dynamic: false`, so an unlisted top-level field shows in `_source` and
matches nothing. `query_attributes` is the one channel that carries it, and
only halfway: `flat_object` keeps leaf values whole, so a `term` filter on
`query_attributes.session_id` is exact, but an aggregation on that path
ignores the path and reads the whole object. Measured on a store holding
one distinct session: `cardinality` on `query_attributes.session_id`
answered 12, and `terms` returned `java.lang.Object@70215544` for its
bucket keys — wrong without erroring, the same trap as the event side, one
store over. Agreeing values across the stores takes a deliberate choice on
each side: a `keyword` declaration on `ubi_events`, `query_attributes` on
`ubi_queries`. A session metric that must aggregate belongs on the event
side, where the declared field is exact.

## The shipped mappings

Vendored verbatim from `src/main/resources/` on the plugin repo's `main`,
so no session fetches them at run time: a mapping pulled from a branch
mid-session makes the same setup produce different stores on different
days, and the managed path (which has no initialize endpoint and creates
its stores by hand) would be creating them from whatever `main` happened to
hold. Checked 2026-08-09 against a live 3.8.0.0 store: every field these
files declare matches it, including every `ignore_above`. (The live
`ubi_events` carried two more: the app's own `keyword` declarations, which
is the declare-before-write practice working, not a mismatch.) The store
tables above are these files read as prose.

`queries-mapping.json`:

```json
{
  "dynamic": false,
  "properties": {
    "timestamp": { "type": "date", "format": "strict_date_time" },
    "query_id": { "type": "keyword", "ignore_above": 100 },
    "query": { "type": "text" },
    "query_response_id": { "type": "keyword", "ignore_above": 100 },
    "query_response_hit_ids": { "type": "keyword" },
    "user_query":  { "type": "keyword" },
    "query_attributes": { "type": "flat_object" },
    "client_id": { "type": "keyword", "ignore_above": 100 },
    "application":  { "type":  "keyword", "ignore_above": 100 }
  }
}
```

`events-mapping.json` sets no root `dynamic`, which is the source of
the text-mapping trap above, and declares `event_attributes` explicitly
`dynamic: true`:

```json
{
  "properties": {
    "application": { "type": "keyword", "ignore_above": 256 },
    "action_name": { "type": "keyword", "ignore_above": 100 },
    "client_id": { "type": "keyword", "ignore_above": 100 },
    "query_id": { "type": "keyword", "ignore_above": 100 },
    "message": { "type": "keyword", "ignore_above": 1024 },
    "message_type": { "type": "keyword", "ignore_above": 100 },
    "user_query":  { "type": "keyword" },
    "timestamp": {
      "type": "date",
      "format":"strict_date_time",
      "ignore_malformed": true,
      "doc_values": true
    },
    "event_attributes": {
      "dynamic": true,
      "properties": {
        "position": {
          "properties": {
            "ordinal": { "type": "integer" },
            "x": { "type": "integer" },
            "y": { "type": "integer" },
            "page_depth": { "type": "integer" },
            "scroll_depth": { "type": "integer" },
            "trail": { "type": "text",
              "fields": { "keyword": { "type": "keyword", "ignore_above": 256 }
              }
            }
          }
        },
        "object": {
          "properties": {
            "internal_id": { "type": "keyword" },
            "object_id": { "type": "keyword", "ignore_above": 256 },
            "object_id_field": { "type": "keyword", "ignore_above": 100 },
            "name": { "type": "keyword", "ignore_above": 256 },
            "description": { "type": "text",
              "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } }
            },
            "object_detail": { "type": "object" }
          }
        }
      }
    }
  }
}
```

Either file becomes an index-creation body by wrapping it: `PUT /<store>`
with `{"mappings": <the file>}`. Measured on 3.8.0: the mappings that come
back that way are identical to the ones initialize produces, which is what
lets the managed path build correct stores without the plugin.

## Initialization

`POST /_plugins/ubi/initialize` creates `ubi_queries` and `ubi_events` with
the shipped mappings above. It is safe to re-run and it repairs nothing;
both facts are measured in [cluster-setup.md](cluster-setup.md), where this
write and the probe that follows it live as a re-runnable file in the app
repo rather than an improvised request.

**Malformed-store trap:** the plugin's query-capture path has no
index-existence guard. A UBI-tagged search arriving before initialization
auto-creates `ubi_queries` by dynamic mapping, with wrong types
(`query_attributes` not `flat_object`, loose timestamp), so data flows and
joins fail. Detect: the index exists but its mapping is not the plugin's
(dynamic mapping enabled, `query_attributes` not `flat_object`). **The
repair always ends in a delete, so announce it with what the store holds.**
A correct mapping cannot be created while the malformed index holds the
name — the highest-blast-radius write the session has — and an announcement
that says only "delete `ubi_queries` and initialize" leaves out everything
the user needs to weigh it. Run three reads before the ask, the way
[dashboards.md](dashboards.md)'s import reads the objects it would replace:

- `GET ubi_queries/_count` — how many rows are at stake.
- `GET _cat/indices/ubi_queries?h=store.size,creation.date.string` — how
  large, and how long they have been accumulating. (The settings carry
  `index.creation_date` as epoch milliseconds; `_cat` renders it.)
- `GET _snapshot` — whether anything could bring them back. A cluster with
  no repository registered answers `200 {}`, so "no snapshot to fall back
  on" reaches the announcement as a read, not an assumption.

**Offer the reindex first.** Copying the rows into a side index is one
request, destroys nothing, and turns the delete into a reversible move.
Whether the data is worth keeping stays the user's call, and they answer it
better holding a copy. Rehearsed end to end on 3.8.0 (`_reindex` into
`ubi_queries_salvage`, delete, initialize, `_reindex` back): every row
survived both crossings, and `query_attributes` answered a `term` filter
afterwards where the malformed store had text-mapped it. Where the user
confirms the rows are worth nothing, the delete alone is the repair.

## Availability and install paths

| Cluster | UBI status |
|---|---|
| OpenSearch 3.1+ (standard distribution) | Plugin **bundled** — verified in the distribution build manifest. Still probe the plugin list rather than assume (there is no enable/disable setting for it to be off): a custom or minimal build can lack it, release zips stop at 3.0.0.0, and the route back is building the plugin from source at the tag matching the cluster |
| OpenSearch 2.15 to 3.0, self-managed | **Not bundled, but installable**: release zips through 3.0.0.0 on the plugin repo's releases page |
| Below OpenSearch 2.15 | Below the floor: no plugin exists; the honest stop applies |
| Amazon OpenSearch Service | Plugin **not available**; the docs are explicit. The session takes the **managed path**: branch overlay in [aws-managed.md](aws-managed.md) |
| Amazon OpenSearch Serverless | Plugin not available, and the managed path's tutorial does not sanction Serverless; the honest stop applies |

## Verify failure catalog

Red-row causes, most common first:

- **Event has no `query_id` / a fresh UUID each event:** the app isn't
  forwarding the response echo: it regenerates ids client-side or never
  reads `ext.ubi.query_id` from the response.
- **Event `query_id` matches no query row:** the search path that really
  executed isn't the instrumented one (second search endpoint, cached
  results, autocomplete path), or the `ubi` block was added to a request the
  server rewrites.
- **Query row missing / `ubi_queries` empty:** `ext.ubi` never reached the
  cluster: a proxy or client library strips unknown `ext` sections, or the
  instrumented code path isn't deployed to the running instance.
- **Clicks miss `query_response_hit_ids` (or match it only erratically) and
  the row's `query` field shows `"object_id_field":null`:** the field was
  omitted from `ext.ubi`, so the plugin wrote Lucene doc ids, which collide
  with real ids only by accident; see the `ext.ubi` section. When the field
  was sent and only some clicks miss: `object_id_field` disagrees between the
  query request and the event emitter, or the UI renders ids from a different
  field than the one declared.
- **Join query returns nothing despite data in both stores:** the check was
  written against a stale field name; re-read the naming trap above.
- **A `term` or `terms` filter on a custom event field returns zero while
  `_search` shows the value:** the field text-mapped and the name is right.
  Read `GET ubi_events/_mapping` before rewriting the query: a `text` type
  there means the filter needs the `.keyword` subfield, and the durable fix
  is a `keyword` declaration and a reindex.
- **A query runs, returns a number, and counts the wrong rows:** the
  population is wrong, not the syntax, so nothing errors. `exists` on a
  `keyword` field matches the empty string, and a search path that sends
  `ext.ubi` on every request (filter-only browsing included) writes
  `user_query: ""` rows into `ubi_queries`, so "was there a search" counts
  page loads. The honest form adds a `must_not` on
  `{"term": {"user_query": ""}}` beside the `exists`, or filters on the
  attribute that names the metric's own population — an attribute that
  exists only if Map put it on the table. Read the matched rows, not the
  number: `size` a handful and look at them.
- **Attributes null:** the emitter fires before the data it needs exists in
  scope (e.g. ordinal computed after render), or a field name typo landed as
  a fresh dynamic field.

## Sources

- Plugin: [opensearch-project/user-behavior-insights](https://github.com/opensearch-project/user-behavior-insights):
  `src/main/resources/queries-mapping.json`, `events-mapping.json`,
  `src/main/java/org/opensearch/ubi/ext/UbiParameters.java`,
  `UbiActionFilter.java`, `ubi.initialize.json` REST spec,
  `ubi-javascript-collector/ubi.js`. `UbiSettings.java` (branches `3.1` and
  `3.6`) declares only `ubi.dataprepper.url`: no enable/disable setting
  exists. No funnel machinery exists anywhere in the repo: `purchase`,
  `checkout`, `conversion`, and `referring_query_id` occur in no source file
  or schema.
- Specification 1.3.0: [o19s/ubi](https://github.com/o19s/ubi), files
  `schema/1.3.0/event.schema.json` and `query.request.schema.json`.
  `query_id` was `required` on an event in 1.0.0 and dropped in 1.1.0.
- Docs: [User Behavior Insights](https://docs.opensearch.org/latest/search-plugins/ubi/index/)
  and subpages; managed-service statement from the AWS tutorial subpage. The
  propagation rule quoted from `schemas.md`, its `sessionStorage` carrier
  and `getQueryId()` helper from `ubi-javascript-collector.md`, the
  five-event journey (timestamps spanning 136 ms) from `sql-queries.md`;
  all read 2026-08-16 in
  [opensearch-project/documentation-website](https://github.com/opensearch-project/documentation-website).
  `ubi.js` itself contains no session storage, local storage, cookie, or
  `getQueryId`: the docs name a carrier the reference client does not
  implement.
- Reference storefront:
  [o19s/chorus-opensearch-edition](https://github.com/o19s/chorus-opensearch-edition):
  reads its id with `sessionStorage.getItem('query_id')`, guards emission on
  presence, clears it at module scope on every load. Its application source
  emits no `purchase` and has no checkout; the six `purchase` rows in its
  `sample-data/` are seeded fixtures no code path produces.
- Bundling floor: `opensearch-build`, file
  `legacy-manifests/<version>/opensearch-<version>.yml` (released versions
  live there, not under `manifests/`, which 404s for them). First
  `user-behavior-insights` entry: **3.1.0** (`ref: tags/3.1.0.0`), absent
  from 3.0.0 and every 2.x manifest. Two published figures are both wrong
  about bundling: the docs' bundled-plugins table says 3.0.0, and the
  **Introduced 2.15** label dates the specification and the separately
  installable plugin, not entry into the distribution.
- Algolia's bounds, for the contrast only: `guides/sending-events/`. An
  event needing a query id must be "within an hour of the related search or
  browse request", "the queryID can't be from a search event older than
  four days", and the after-search event variants take a query id where the
  plain variants do not.
