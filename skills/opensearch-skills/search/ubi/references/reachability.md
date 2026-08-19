# Reachability: what this cluster can measure, before anything is agreed

Pinned against UBI plugin 3.8.0.0 and opensearch-search-relevance 3.8.0.0 on
OpenSearch 3.8.0. All live measurement behind this file was taken on that
version between 2026-08-09 and 2026-08-15; the version columns below are
therefore not each exercised, but read from the plugins' own availability
tables and from setting literals at the 3.1.0.0, 3.2.0.0, 3.3.0.0 and 3.4.0.0
source tags. A floor here is a well-evidenced claim about where a capability
starts, never a report of this session's behavior on that version. The
managed column is derived the same way, from a tutorial and this skill's own
references, and no leg of it has been run against a live Amazon OpenSearch
Service domain.

**Whether a class of metric can be measured here is knowable before the room
commits to a target.** This file crosses what a room wants to measure with
what the cluster is, so the Preflight gate can say what this install can
carry and Elicit can name a wall while the goal is being chosen, rather than
a session discovering it at Verify with instrumentation already written.

It is not the dependency table in [cluster-setup.md](cluster-setup.md); that
one runs the other way, one row per external dependency, stating which of the
session's own capabilities the cluster carries. This one starts from the
measure and asks whether the stores can hold it. A cell here may point at a
dependency row; it never restates one.

**Every verdict below is either measured on a live cluster at a named tag or
read from the reference that owns it.** Where neither is true the cell says
**unmeasured**: a gap in our evidence, never a wall in the product, and the
two must not be reported as the same thing.

## Before the grid: the shapes that never reach it

Two cluster shapes are settled at the Preflight gate, before any measure is
discussed, so they are not columns:

- **Amazon OpenSearch Serverless.** The plugin is unavailable and the managed
  path's own tutorial does not sanction it, so the honest stop applies and no
  metric question is asked ([ubi-schema.md](ubi-schema.md)'s availability
  table).
- **Below OpenSearch 2.15.** No plugin exists at all; the same honest stop.

One more shape reaches the grid but must be read from the cluster rather than
from its version: **the plugin list is the authority**. A 3.1+ distribution
built custom or minimal can lack `opensearch-ubi`, and release zips stop at
3.0.0.0, so the route back is a source build at the matching tag
([ubi-schema.md](ubi-schema.md)). The gate's check 2 reads the list and
routes the session on it: the three plugin columns assume it came back green,
and the managed column is where a red read on a cluster that cannot take an
install lands.

## The grid

Rows are metric classes, not individual metrics. Columns are cluster shapes.
`✓` reachable, `⚠` reachable with the named wall or floor cleared first, `✗`
out of reach on this shape.

| Metric class | Plugin, 2.15-3.0 | Plugin, 3.1 | Plugin, 3.2+ | Managed domain |
|---|---|---|---|---|
| **SERP rates** (click-through, zero-result, never-clicked) | ✓ | ✓ | ✓ | ⚠ nothing upstream supplies a field the emitter omits |
| **Judgment list** (COEC ratings built from clicks and impressions) | ✗ not in the distribution below 3.1 | ⚠ present but off; one dynamic setting, a Rule 5 write | ✓ on by default | ⚠ its presence is the domain's own question, and unmeasured |
| **Scheduled drift check** (that list re-scored on a cron) | ✗ below the floor | ✗ below the floor | ⚠ from search-relevance **3.4** only, so 3.2-3.3 cannot | unmeasured |
| **The per-intent report** (any row above, read by what people came to do) | ⚠ needs a deployed text-embedding model | ⚠ same | ⚠ same | unmeasured; whether a local model runs is the domain's own question |
| **Cross-visit / return metrics** | ⚠ needs a `client_id` that survives the visit (the room's call, not the cluster's) | ⚠ same | ⚠ same | ⚠ same |
| **Business measures** | ⚠ only where the measure collapses onto a search interaction | ⚠ same | ⚠ same | ⚠ same |
| **RAG chunk-grain behavior** | ⚠ the grain follows the corpus, not the cluster | ⚠ same | ⚠ same | ⚠ same |

**Only two rows are version questions**, and knowing which is the point of
reading the grid rather than guessing at it:

- **The judgment list and the scheduled drift check** are the ones a version
  moves. Everything a version buys in this grid, it buys for those two.
- **SERP rates and the per-intent report** are moved by the plugin-versus-
  managed split and by nothing else: they read the same across all three
  plugin columns.
- **Cross-visit metrics, business measures and RAG chunk grain** are
  identical in every column, and that is the finding rather than a gap in
  the grid: their walls are properties of the measure, not of the cluster,
  so no upgrade, migration or plugin install moves them. A room sent off to
  change its cluster over one of these has been misread.

## Where each row's answer comes from

- **SERP rates.** The core session (capture, the joins, Verify), which the
  UBI plugin (`opensearch-ubi`) carries from 2.15 installed and 3.1 bundled
  ([cluster-setup.md](cluster-setup.md)). The zero-result and never-clicked
  populations are reachable because a search returning nothing still writes
  a query row. The filters that isolate them, and the browse-load exclusion
  both of them need, belong to [return-visits.md](return-visits.md)'s
  no-click inventory and are deliberately not restated here, because a
  filter quoted in two files drifts in one of them. On a managed domain the
  app builds the query record itself and both records travel through
  OpenSearch Ingestion; the field names are the pinned ones and every plan
  query derives the same way, but the server-side capture that records the
  typed text on the plugin path is absent, so an emitter omitting
  `user_query` or `position.ordinal` leaves it nowhere and nothing complains
  ([aws-managed.md](aws-managed.md)).
- **Judgment list.** Availability, the enable setting and the disabled tell
  are [judgments.md](judgments.md)'s; the grid's floors are pinned against
  search-relevance 3.8.0.0 with the enable literal read at the 3.1.0.0 and
  3.2.0.0 tags. On a managed domain its availability is checked before
  either the Verify row or the judgment visit is promised, and that check
  has not been run against a live domain here
  ([aws-managed.md](aws-managed.md)).
- **Scheduled drift check.** This row carries the NDCG-family numbers, since
  what the check watches is those scores drifting against the judgment
  snapshot. Scheduling first ships at search-relevance **3.4**, enabled by
  default from that release, on a scheduler dependency with its own
  [cluster-setup.md](cluster-setup.md) row. That floor was **read at the
  source tags** (the scheduling transport package is absent at 3.3.0.0 and
  present from 3.4.0.0), not measured on a 3.3 cluster; what was measured
  live, on 3.8.0 on 2026-08-14, is the chain end to end
  ([judgments.md](judgments.md)). It therefore sits two minor versions above
  the judgment list it re-scores, which is why the two are separate rows.
- **The per-intent report.** ml-commons with a deployed text-embedding
  model, and no version floor of its own
  ([cluster-setup.md](cluster-setup.md)). The procedure was measured on
  OpenSearch 3.8.0 with `all-MiniLM-L6-v2`; on an Amazon OpenSearch Service
  domain, whether a local model is available is the domain's own question
  (instance types gate it), and the procedure was not measured there
  ([intent-labels.md](intent-labels.md)).
- **Cross-visit / return metrics.** A `client_id` minted fresh each visit
  serves the floor, click-through, position and every within-visit
  conversion metric; user retention, new-versus-returning and cross-visit
  conversion need one that survives the visit, and `cardinality` on a
  per-visit id counts visits rather than people while reporting no error
  ([ubi-schema.md](ubi-schema.md)'s identity semantics). Whether that id
  exists is settled at Map, routed through whatever gate the Audit found,
  and a room may decline it, so this row's wall is a decision, and a browser
  store besides.
- **Business measures.** Reachable exactly where the measure collapses onto
  a search interaction. Four structural walls stand behind that verdict; the
  worked examples are below.
  - **Population.** The stores only ever hold search-attributed sessions,
    so any rate whose denominator is "all customers" is a fraction of the
    business number sharing its name.
  - **Attribution.** `query_id` joins exactly only on the SERP. Past it,
    the settled read crosses the order table with the click store on
    `object_id` and `client_id`; only per-line or cross-visit credit still
    needs the id to travel, a build that is the team's rather than this
    session's.
  - **Identity.** Anything cross-visit inherits the row above.
  - **No money and no sentiment fields.** Revenue and satisfaction have no
    schema home, so they arrive in `event_attributes` as whatever dynamic
    mapping makes of them ([ubi-schema.md](ubi-schema.md)).
- **RAG chunk-grain behavior.** The corpus decides this, not the cluster.
  Chunks written back onto the parent document leave no chunk-level
  identifier in the source, the mapping or the hit, so `object_id` can only
  be the parent and behavior lands at document grain. Chunks that are each
  their own document put the grain at the chunk — and re-chunking then
  orphans every accumulated impression, click and judgment: the joins still
  hold and nothing errors; the rows simply name chunks that no longer exist
  ([rag-assistant.md](rag-assistant.md), measured live on a 3.8.0 plugin
  cluster on 2026-08-14). One cluster fact applies on every column: the RAG
  search never carries `ext.ubi`, because a search whose `ext` holds both
  `ubi` and `generative_qa_parameters` dies whole with a 500, so that leg's
  query record is app-built wherever it runs.

## The business row, worked

The four walls above were tested against the five business measures Tito
Sierra uses as worked examples in *Selecting the RIGHT Measures for Your
Search Product* (Haystack US 2023) — somebody else's list rather than one
picked to flatter the stores. They are paraphrased into this file's
vocabulary; the verdict in each right-hand cell is ours, not his, and his
deck makes no claim about UBI:

| The business measure | Reachable from `ubi_queries` + `ubi_events`? |
|---|---|
| Search-results click-through rate | **Yes, cleanly.** A SERP click joined to its query. Nothing extra needed. |
| Order size per search | **Conditional.** The order table keeps the money (the schema still has no value field), and the settled purchase-to-click read behind the attribution wall above joins it back to the search, last-touch, with an unattributed remainder. |
| Time spent consuming what was found, per search | **No.** Continuous, off-SERP, and no action-name shape fits it. A different instrumentation project. |
| Weekly active search usage | **Conditional.** Needs a `client_id` durable across weeks: the identity wall, consent-gated, and a browser store besides, which people clear and which does not follow them between devices. |
| Search app satisfaction score | **No.** No feedback affordance exists to observe, and subscription or account state lives outside the stores entirely. |

**One of five is cleanly reachable, and it is itself a SERP click-through
rate.** That is the generalization the row states: UBI carries a business
measure exactly when the measure collapses onto a search interaction. It is
also why a business outcome enters Elicit as a question with a reachable
proxy (a leading indicator *of* the outcome, never the outcome), and why
**named out of reach, with the wall and the stand-in written down, is the
normal result for this row rather than the fallback**.

## Standing cluster state: the two gates that are not versions

Two of the walls above are not properties of the distribution at all. They
are state someone set, which someone can unset between one visit and the
next, so they cut across every column instead of belonging to one. That is
why neither is a column, and why **a column is a snapshot of the shape at the
moment it was read, not the shape**:

- **`opensearch-search-relevance` present and enabled** moves rows 2 and 3
  only. Its floors and its disabled tell are stated above and owned by
  [judgments.md](judgments.md); what belongs here is that presence is a
  per-plugin question, and one plugin is never evidence about the other.
  The shared 3.1 arrival that invites that inference is a coincidence, as
  [cluster-setup.md](cluster-setup.md)'s dependency table states.
- **A deployed text-embedding model** moves row 4 only. It survives a node
  restart, so it is state the team keeps rather than a session-scoped probe
  ([intent-labels.md](intent-labels.md)).

Both are free reads. Take them with the gate's own plugin-list read rather
than carrying an assumption into Elicit.

## When this grid lies

Every way a cell here misleads, named rather than left for the room to find:

- **A `✓` says reachable, never meaningful.** It answers whether the stores
  can compute the metric, not whether the answer is worth reading. A metric
  computed on an app serving thirty searches a day is a number without a
  denominator worth the name, and the grid cannot see volume at all. How
  much behavior is enough, and whose call that is, are
  [judgments.md](judgments.md)'s.
- **Floors were read at tags, and tags move.** Every version number here was
  read between 2026-08-09 and 2026-08-15, under the caveat at the top of
  this file. A later release can lower a floor, move a default, or ship a
  capability this grid has no row for, and the file will not know it
  happened. A floor that decides something expensive is worth re-reading at
  the cluster's own version before the room acts on it.
- **`unmeasured` is not `✗`.** It means the derivation is expected to hold
  and has not been demonstrated: a gap in evidence, reported as one. The
  three cells carrying the word are the ones where even the derivation runs
  out; the rest of the managed column is no more exercised than they are, as
  the top of this file says, so a `✓` or `⚠` there is a reading of documents
  and not a report from a domain.
- **The grid informs a call; it never makes one.** Nothing here turns a
  session down, declares a goal unmeasurable, or blocks a step. A wall named
  early is a conversation about a proxy; that conversation is the point, and
  the room decides.
