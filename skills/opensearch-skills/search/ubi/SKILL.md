---
name: ubi
description: >
  Instrument an existing search application with User Behavior Insights
  (UBI) and verify live that every event joins its query. Use this skill
  when the user wants click tracking, impressions, or search analytics
  for an OpenSearch-backed app, wants to debug UBI events that are
  missing or do not join, or wants to extend or review an existing UBI
  setup (including implicit relevance judgments from clicks). Activate
  even if the user never says UBI or OpenSearch. For evaluating or
  tuning search-result quality use opensearch-launchpad instead.
compatibility: "Requires the search application's code in the workspace, and an OpenSearch cluster. That means either a cluster that runs or can install the UBI plugin (bundled since OpenSearch 3.1, separately installable from 2.15) or a managed service that cannot run it, which takes the plugin-less managed path (pinned for Amazon OpenSearch Service: manually created stores plus OpenSearch Ingestion pipelines, AWS credentials required). Amazon OpenSearch Serverless is not supported."
metadata:
  author: ChrisCraig68
  version: "1.0"
---

# UBI

Take a search application from no behavioral data to **verified joinable events** in one sitting.
The user supplies business goals and approvals. You do the rest: the audit, the cluster checks, the
mapping proposal, the code, the live verification.

**Joinability is the contract.** An event in `ubi_events` joins its query in `ubi_queries` through a
shared `query_id`, and a joined event is usable only when it also carries the attributes its mapping
row requires. Events that flow but do not join are worthless, and no error will ever say so, because
the stores fail silently. The session ends when a real click provably joins a real query, not when
the code lands.

## Critical rules (MUST follow)

1. **Implement only after a green preflight.** Write instrumentation only when every preflight check
   has passed in this session. If the user asks to skip the checks, name the cost (an unchecked
   store can take every event and join none of them) and offer the idempotent run instead: on a
   sound cluster it takes seconds.
2. **Get the mapping approved first, and leave exactly two durable files behind.**
- Approval happens in the conversation, before any instrumentation is written. If the user declined
     the elicitation, propose a mapping from the Audit's findings, mark the cells you chose rather
     than heard, and still get an explicit yes. A one-line yes is approval. A reply that contests a
     row reopens that row. No answer is not approval.
- The repo keeps two durable artifacts. `ubi-metrics-plan.md` holds the why and the targets, which
     code cannot say; never overwrite the user's edits to it. The cluster setup lives under
     `.opensearch/` ([cluster-setup.md](references/cluster-setup.md)). The mapping table itself
     stays in the conversation.
- Delete everything else you create: the questionnaire and the saved-objects ndjson follow their
     references' cleanup rules. The record meant for the team is the dashboard's guide panel (goals,
     targets, and caveats, in a cluster the team already reaches), not a repo file. A repo file is
     the user's to ask for; never read one back as session state.
- Analytical output goes to the conversation, the plan file, and the user's cluster only. Never send
     it to a host outside their infrastructure; publishing it as a web page is exactly the case this
     rule exists for. (The skill collection's feedback channel is outside the rule because it
     carries none of that data.)
3. **Events carry opaque identifiers only.** A `client_id` is a generated UUID; an `object_id` is a
   SKU or ISBN. A value that identifies a person (a name, email, address, account text, or raw
   search input containing any of these) never enters `event_attributes`. Flag PII risk in the
   user's business questions during Map, before it reaches code.
4. **Wired means verified.** Claim that instrumentation works only after Verify's row-by-row live
   checks pass in this session against the running cluster. Only a real user action verifies a path.
   A synthesized event, or a request you posted yourself, shows the path can be *read*; it does not
   *verify* it. Scope every claim to what a real action exercised, and ask the user for the click
   rather than standing in for it. A report that Verify is done — the user's or your own — is read
   against Verify's six checks by number before it is accepted or anything moves on: open your
   reply by naming any check the report leaves out as still open, and never echo the report's
   claim of done while a check is unaccounted for. The judgment-list check is the one such reports
   most often omit.
5. **Announce every cluster write; reads are free.** The cluster is shared state with no undo.
   Before anything that creates, modifies, or deletes cluster state (store initialization, a repair
   or reindex, a plugin install, a pipeline, a saved-objects import), say in one plain sentence what
   you will do and why. A delete's announcement also states what the store holds now, read live from
   it, never recalled or taken from the user's estimate. Make that sentence the last thing in your
   turn, and run the write in a later turn once the user agrees. A go-ahead given before the
   announcement does not count: the user agreed to something they had not yet seen the cost of, so
   the write still waits for a reply to the announcement itself. The self-cleaning probe document is
   the one exception. If the harness would let the write through without asking, still end the turn.
6. **Take every schema and protocol fact from the references.** The `ext.ubi` block, field names,
   standard action names, and install paths come from [ubi-schema.md](references/ubi-schema.md),
   with [aws-managed.md](references/aws-managed.md) as the overlay on the managed path. Never work
   from memory here: wrong field names index without complaint and fail only at join time.

## The session

Seven steps in fixed order: **Audit → Preflight gate → Elicit → Map → Implement → Verify →
Dashboard**.

**Talking to the user.** Plain language throughout (the Federal Plain Language Guidelines practice):
everyday words, one idea per question, in the app's own domain words from the Audit. Frameworks stay
backstage; name one only if asked. Where a technical term must surface, lead with the plain
phrasing.

- Batch the cheap questions, isolate the approvals: two or three questions per turn, numbered, each
  with your recommended answer marked as yours and grounded in the Audit's facts. A permission turn
  (the mapping approval, a cluster-write go-ahead) asks nothing else. One reply to a two-ask turn
  reads as granting the permission and silently drops the second question.
- Ask about behavior that has already happened, not hypotheticals (the *Mom Test* practice): "what
  do people do today when results go wrong?" over "would people click a feedback button?". Only
  targets and commitments ask about the future.
- An answer settles the question it names and no other: proceed on what is settled, re-ask what the
  user left unanswered, and never settle it yourself, even with your recommendation on the table.
  Silence is never agreement.
- Deliver the obligation on the table before chasing context. When the user's turn asserts or asks
  something this skill obliges you to correct, warn about, or refuse, that correction, warning, or
  refusal leads your reply — missing files, an absent repo, or an unlocated plan never postpone it.
  Name what is missing after the obligation is delivered, not instead of it.
- Keep table rows inside about a hundred characters; longer content goes below the table.

**Re-entry.** Detect where the app actually is and resume there. Observed state decides, not user
recollection. When more than one rule matches, the furthest-along rule wins:

- No capture on the search path (no `ext.ubi`; on the managed path, no query-record send): start at
  Audit.
- Stores present and correctly mapped, no instrumentation in the app: resume at Elicit, after
  re-verifying the Audit's facts against the code.
- A `ubi-questionnaire.md` at the app repo's root: ingest it first
  ([elicit-async.md](references/elicit-async.md)). It is pending input, never skipped by
  furthest-along. Then resume wherever the other rules place the app, extending the approved mapping
  with what the answers add.
- Instrumentation present but never verified, or events reported missing or broken: resume at Verify
  and debug from its checks. The same applies when the cluster holds no judgment list, or none
  rating anything above zero, because that list is the durable record that check 6 once passed.
- Capture this skill never approved (`ext.ubi` and events emitting, but no `ubi-metrics-plan.md` and
  no mapping agreed here): resume at Verify, and make the reconstruction offer below.

When no rule matches (instrumented, verified, nothing reported broken), the seven steps are done for
what the app has today, and the session is a **return visit** ([Return visits](#return-visits)). One
exception: where the cluster holds no `ubi*` saved objects, Step 7 never ran, so offer it once. The
user's ask picks the visit, never the state; ask about an ambiguous ask rather than guessing.

Wherever the session resumes, read any `ubi-metrics-plan.md` at the app repo's root before anything
else moves. The file as it stands is the plan ([metrics-plan.md](references/metrics-plan.md)); an
app instrumented without one gets the reconstruction offer defined there. The Preflight gate alone
always re-runs: cluster state drifts.

### Step 1: Audit

**Goal:** ground the session in what the application actually is. Locate:

- the search request build site (file and function) and the client or framework that issues it;
- where the endpoint and credentials are configured, and the searched index;
- the document field that naturally identifies a result (the future `object_id`) and its mapped
  type;
- the user-visible UI actions: results rendering, result selection, query refinement (filters,
  facets, sorting), and any richer actions (add to cart, save, preview, paginate).

A RAG assistant (a retriever feeding a model rather than a results page) runs every step through
[rag-assistant.md](references/rag-assistant.md).

Identity is part of the audit. Find what the app already keeps about the person browsing (a cookie,
a stored id, a login) and what governs it (a consent banner, a do-not-track check, a privacy
notice). Ask what that gate covers, and what permits the team to keep data about how people use the
app; behavioral capture is that kind of data even with opaque identifiers. Finding no gate at all is
a finding, not a blocker; Map can only route around what the Audit named.

The tool the team already trusts is part of it too. Find where the app reports behavior to an
analytics tool (a GA4 or gtag snippet; a Segment, PostHog, or Amplitude client) and which audited UI
actions already fire its events. The finding opens the bridge
([analytics-bridge.md](references/analytics-bridge.md)): numbers read in from the tool, identifiers
stamped onto events the app already sends. Finding none closes it.

**Check:** you can state, and the user confirms: the call site, the endpoint and how the app
authenticates, the index, the identifier field and its type, the UI actions, the analytics tool the
app reports to, and what the app stores about the person plus its gate, with "nothing", "no gate",
and "no tool" said rather than left blank. Every item names a real file, field, or component you
read.

### Step 2: Preflight gate

**Goal:** prove this cluster can do UBI, now. Four live checks run against the audited endpoint, and
the second one picks the path:

1. The cluster is reachable and the audited credentials authenticate.
2. The UBI plugin is installed and active. Read the cluster's plugin list for `opensearch-ubi`;
   never infer it from the version or from who hosts the cluster. The grid in
   [reachability.md](references/reachability.md) shows what this cluster shape can then measure. A
   list without the plugin forks below before checks 3 and 4 run.
3. The `ubi_queries` and `ubi_events` stores exist with the plugin's own mappings. A `ubi_queries`
   with auto-created dynamic mappings (the malformed-store trap in
   [ubi-schema.md](references/ubi-schema.md)) must be repaired before any data flows, and the repair
   always deletes an index.
4. The stores accept writes: index one probe document into `ubi_events`, confirm it is searchable,
   remove it.

Checks 3 and 4 run through the setup artifact: write it into the repo and run it
([cluster-setup.md](references/cluster-setup.md)). Only running it turns the two checks green;
writing it proves nothing.

**When check 2 finds no plugin, fork by whether this cluster can take an install:**

- **It can (self-managed, at or above the floor):** recoverable. Guide the install for the cluster's
  version (install paths in the schema reference), wait for the user's go-ahead, re-run the four
  checks, continue.
- **It cannot (a managed service):** the **managed path**: same session, same joinability contract,
  but its own preflight checks, transport, and Implement deltas
  ([aws-managed.md](references/aws-managed.md)). That branch is pinned against Amazon OpenSearch
  Service; its "When this branch runs" section says what holds on another provider in this position.
- **Amazon OpenSearch Serverless, or below the plugin's version floor:** stop honestly. Name exactly
  what is missing and why the session cannot proceed, then end it. The honest stop is the
  deliverable, and it beats a UBI-shaped store of pretend data that no downstream tool can trust.

**Check:** all four checks green in this session (on the managed path, that branch's checks), or the
honest stop delivered with the exact missing capability named.

### Step 3: Elicit

**Goal:** agree the goals, signals, and metrics that will govern every event this session creates,
in a guided conversation.

Open by asking who owns these answers: does the person in the session speak for the business goals,
or should product or analytics weigh in? Ask directly; the user may not volunteer absent
stakeholders. Owners who are not in the room get the elicitation on paper
([elicit-async.md](references/elicit-async.md)). Offer "unsure" beside every recommendation; unsure
cells become the questionnaire's questions. When unsure cells pile up, ask the user plainly whether
to continue or hold for the questionnaire, and never decide that by silence.

One question per turn through Elicit, each settled before the next.

Run a **Goals → Signals → Metrics** elicitation (*Software Engineering at Google*, ch. 7) across
both axes:

| Axis | Elicit | Example |
|---|---|---|
| User | search task → success factor → measure | find images for a project → engagement → saves per searched session |
| Business | business goal → success factor → measure | grow order size → conversion → order size per searched session |

Goals first. Open with the question the room most often asks of analytics and never gets a straight
answer to, in their own words with no framework showing. Then cover the axis the answers missed: if
every goal is user-side, ask what the business wants from search. Backstage, check the goals' spread
against the HEART categories (happiness, engagement, adoption, retention, task success): goals
clustered in one category earn one prompt for the missing kinds — all task-success asks once whether
satisfaction, or people coming back, matters here. Settle the two or three goals this app can carry.
For each goal, derive the observable behaviors that would move if the goal were met or missed. Then
agree how each signal aggregates into a metric:

- Prefer a rate or per-visit average over a raw count; raw counts drift with traffic.
- Attach the numeric target the room commits to now, dated and provisional. A headline or guardrail
  with no target is a vanity number.
- A task-success metric captures the behavior that completes the task, not merely a click.

Compose the questions live from this process and the Audit's facts.

Ask, in its own turn, roughly how many searches a day the app serves, because a target is read
against its traffic. "Unsure" is an answer. If the stores already hold behavior, read the volume
from them instead of asking. Where they hold none but the Audit's analytics tool is connected in
this session, read it from the tool the same way
([analytics-bridge.md](references/analytics-bridge.md) owns that read and what a session-level
figure may claim). The plan records the answer, dated. Where the volume is thin, say while the
target is agreed that thinness costs time: the thinner the stream, the longer before any number can
be read against it. Give no minimum volume and no significance verdict; whether the wait is
acceptable is the room's call.

Three facts constrain the table regardless of goals:

- **This skill captures search behavior only.** Every event it maps hangs off a search, a scope this
  skill chooses rather than one UBI imposes. Say this while goals are chosen: a goal that lives
  where no search happened (a homepage rail, a cart add nobody searched for) has no signal this
  session can reach.
- **Search data has a floor** below which it cannot be interpreted: the captured query, the
  presented ranking (the hit-ID list the `ext.ubi` capture records for free), and clicks carrying
  `position.ordinal`. A click cannot be read or debiased without the ranking it was made against,
  and position cannot be recovered later. The floor is in every mapping; goals only add to it.
- **Impressions feed the click models.** Joined clicks and impressions feed the implicit relevance
  judgments of Verify's check 6 and the judgment visit. A vocabulary that skips impressions leaves
  the Workbench's COEC model without its denominator.

Two constraints bind the table. A signal is in reach only when an audited UI action carries it; the
agreed signals become the `action_name` vocabulary Map turns into event rows. A metric is honest
only when the joined stores can compute it; Verify holds that line by running every plan query live.

When a goal fails either test, say so plainly; that is a normal outcome:

- **No audited action carries the signal**: name the gap in the app's own terms ("nothing here asks
  whether the results helped") and recommend the product feature that would carry it — built only if
  the user explicitly asks, and then through Implement's conventions check.
- **The cluster cannot carry the goal's metric class**: quote the wall the grid in
  [reachability.md](references/reachability.md) names.

**The close.** With the table confirmed, three questions end Elicit. Q1 and Q2 go in one turn, with
your recommendation for both drawn from the table.

- **Q1. Which of these numbers would you watch to know search is delivering what the business wants
  from it?** One row from the table. This is the headline metric the work steers by: a leading
  indicator of that business outcome, or simply their one number where the app serves none. If the
  room names a raw search count or revenue per user, say plainly that either can climb while search
  gets worse, because a failing results page breeds retries and extra ad clicks, and offer sessions
  per user instead: satisfied users come back. The room decides; the plan records the choice dated,
  e.g. `Headline metric: searches per week (named over the warning, 2026-08-16)`.
- **Q2. What must not get worse while it improves?** Rows from the table, however many. These are
  the guardrails; rows that are neither headline nor guardrail are the tracking rows day-to-day
  optimization moves. (Keep the North Star, tracking, and guardrail names backstage.)
- **Q3. What do people come to this app to do?** Free-text, asked once. (The answers become the
  intent labels a later review reports every metric by —
  [intent-labels.md](references/intent-labels.md).)

**Check:** the user confirms a goals → signals → metrics table where:

- there are at least two goal rows, or one settled row plus the floor when the rest went to the
  questionnaire (the minimal path);
- every signal names the audited action that carries it;
- every metric carries its numeric target;
- the search volume is on record, even if the answer was "unsure";
- the room named one headline metric and its guardrails;
- what the business wants from search is either in the table or you named it out of reach.

Every cell was asked, then settled or parked into the questionnaire by the user's explicit choice.
Elicit never ends because the user went quiet; an unsettled cell is the next question, never a blank
you fill yourself.

### Step 4: Map

**Goal:** propose the event mapping and get it approved in conversation. One row per event: goal's
signal → app action → `action_name` → required attributes. Build every row on these practices:

- Use standard action names before custom ones. Go custom only for actions the standard set
  genuinely lacks, in the object-action grammar of tracking-plan practice (`result_expanded`), each
  with a stated purpose: the decision its data would change.
- `query_id` goes into **every** event row. It is the join key; a row without it is unjoinable by
  construction. An action with no search behind it does not become a row; turn it down as out of
  scope rather than diagnosing it as broken wiring. Past the results page, the id an action carries
  is whichever the app last stashed; read
  [ubi-schema.md](references/ubi-schema.md#how-far-the-join-reaches) before mapping any post-SERP
  row.
- Every metric on the approved table must be computable from the mapped rows. Per metric: name the
  field it filters on, the field it groups or aggregates by, and the rows it is about; then check
  that the mapped rows carry them. A field nobody mapped cannot be added once events are written
  (the schema reference's `keyword` rule and the population trap beside it).
- Impressions and clicks all carry `position.ordinal`, unconditionally; a click without it is
  invisible to the Workbench click model. Each impression fires once per result per search: a
  visibility gate settles *when* one fires, never how many times (the re-fire trap is in
  [ubi-schema.md](references/ubi-schema.md)).
- Where a row could be captured more than one way (impressions on render or on real visibility),
  recommend the option that measures its goal validly, not the one that is simplest to build. The
  user decides after hearing what the simpler option would mis-measure: render-fired impressions
  count results nobody saw, and CTR inherits the error.
- Identity is consistent and lives no longer than the agreed metrics need. The same values reach
  both stores from the same generation points. One `session_id` covers one visit. A `client_id`'s
  lifetime is the approved table's decision, not a default: recommend the shortest life that keeps
  every metric honest, because a per-visit `client_id` counts visits, never people (the cross-visit
  row in [reachability.md](references/reachability.md)).
- The proposal names each identifier it will mint, where it is stored, and how long it lasts. Route
  any identifier that outlives the visit through the gate the Audit found. The gate governs only its
  persistence: a decliner still gets a per-visit `client_id`, so the floor metrics keep working. If
  the Audit found no gate, say so plainly and leave the call with the team. A persistent identifier
  is a normal answer when a metric needs one; minting it silently is not.
- Where the Audit found an analytics tool, make the bridge offer, once: the vendor events the app
  already fires on audited actions gain the same `query_id` and identity fields the UBI events
  carry, so the team's own tool can segment by searched sessions. Read
  [analytics-bridge.md](references/analytics-bridge.md) before wording the offer: it pins the
  screen, the gate routing, what an accepted offer obliges, and the decline.
- Settle retention here: how long the stores keep behavior, decided with the volume in front of the
  room and what too short a window costs the judgments built on it
  ([cluster-setup.md](references/cluster-setup.md)).
- `object_id` is the Audit's identifier field, and `object_id_field` names it; events and queries
  agree on both. It must be **string-typed**: the plugin casts without checking, and an integer id
  500s the app's own search. Never omit it, or the hit-ID list fills with internal Lucene ids and
  Verify check 3 fails, or falsely passes on a collision.
- Critical Rule 3 screens every attribute column, and `user_query` with them: Implement puts the
  typed text on every event row, so a search box people type account numbers into leaks into a
  second store. Say so at the table.

**Check:** the user approves the mapping table in the conversation; every metric on it has the
fields it needs among the mapped attributes; and the approval writes the session's durable plan,
`ubi-metrics-plan.md` at the app repo's root, in the pinned format of
[metrics-plan.md](references/metrics-plan.md), read before writing. The mapping table stays in the
conversation: Implement reads it from this approval, Verify reads it again as the checklist. The
plan holds the why and the numbers; the code holds the events.

### Step 5: Implement

**Goal:** land both halves of the instrumentation in the app's own conventions: its language, its
client, its component structure, the style of the code around it.

- **Server side:** the audited search call gains the `ext.ubi` block (shape in the schema reference)
  carrying at minimum `client_id`, `user_query`, and `object_id_field`. The app forwards the
  `query_id` from the search response to wherever events are emitted. The managed path and the RAG
  branch have no `ext.ubi`; follow their references' deltas instead.
- **Client side:** each approved mapping row gets an emitter at its UI action, and its event
  document lands in `ubi_events` with the row's `action_name`, the forwarded `query_id`, the typed
  query text, the identity fields, and the row's required attributes. On the managed path the same
  document is POSTed to the events pipeline instead: same document, different door. The plugin
  records queries only; event emission and its transport are always the app's own code. Read the
  four-point transport contract in [ubi-schema.md](references/ubi-schema.md#emitting-events) first.

Two checks before writing any code:

1. **The gate's evidence.** Quote the closing line of the setup artifact's run from this session
   ([cluster-setup.md](references/cluster-setup.md)). Nothing to quote means it has not run, so run
   it before any code.
2. **The conventions check.** Read the project's own context (CLAUDE.md or AGENTS.md, contributing
   docs, whatever skills or commands the session exposes) for an established way of changing code,
   and route both halves through it. This skill owns *what* to instrument; the project owns *how*
   code gets written. If nothing is found, implement directly and say nothing about the check.

**Check:** every approved mapping row has an emitting code path; the app builds and runs; the diff
contains the instrumentation and nothing else. The cluster setup ran at the gate in this session and
you stated what it reported; it does not run again here.

### Step 6: Verify

**Goal:** prove joinability row by row, with live data. Have the user perform one real search and
one real click in the running app, or drive a browser yourself where the environment provides one.
Then interrogate the stores with live queries, against the approved mapping:

1. The search landed in `ubi_queries`: `query_id` present, `user_query` the real typed text, and the
   hit-ID list populated under the field name the schema reference pins; the stale names in older
   UBI docs match nothing.
2. Every emitted event landed in `ubi_events` carrying the **same** `query_id` the query row holds.
3. The click's `object_id` appears in that query row's hit-ID list: the click provably belongs to
   the results the user saw.
4. Each event row carries every attribute its mapping row requires, with values, not nulls: the
   typed text and `position.ordinal` on every impression and click, identity fields consistent
   across both stores, no result impressed twice under one `query_id`. Then read the store's live
   mapping and confirm every field a metric filters or aggregates on is typed to support it, under
   the `keyword` rule and its failure shapes in [ubi-schema.md](references/ubi-schema.md).
5. Every query in `ubi-metrics-plan.md` runs against the live stores. One search and one click make
   no metric worth reading; the check is that each query executes, finds the fresh pair's events
   wherever they land, and matches the population its own metric's prose names. A query that errors,
   misses data it can see, or answers about the wrong rows gets diagnosed from the schema
   reference's failure catalog and fixed now.
6. The Workbench can read what landed: build a judgment list against the live stores
   ([judgments.md](references/judgments.md)). Building it is a Critical Rule 5 write; so is
   switching on a Workbench that ships disabled. Green is at least one rating above zero. An empty
   list, or one that rates everything zero, is red, never a partial pass. Where the Workbench is
   absent or too old, close the row honestly, naming what is missing.

Debug a red row **in this session**: read its reference's failure catalog (on a branch, the branch's
catalog first, since a buffered row is not a red row), fix the wiring, have the user search and
click again, and re-run the checks on the fresh pair. Repeat until green.

**Check:** checks 1-5 green for every mapping row on a fresh search-and-click after the last code
change, and check 6 green or honestly closed. A claim that Verify is done — the user's or your own —
is read against the six checks by number before anything is written up: a check with no evidence
from this session is named as still open, and check 6 is the one such claims most often skip. Then
tell the user what they now have: behavioral data that joins, and what can read it.

### Step 7: Dashboard

**Goal:** turn the plan's metrics into panels the team can open without running a query, under a
markdown guide panel that says what each one means, handed over as the address to show the team.
Every shape, the handover walkthrough, and every verified trap are in
[dashboards.md](references/dashboards.md).

**Start at the stores, not at the plan.** Run each metric's plan query before generating anything.
What it matched decides whether the metric gets a panel, is published as its parts, or gets none.
Matching nothing is the one outcome that is not a fault, once field names and types are checked.

**Check:** the import's response body reports `success: true` (the status code says nothing); every
metric behind a panel was reconciled before the panel existed; after a refresh, you state each
panel's number beside what its own plan query returns, and a disagreeing pair is red, to be rebuilt
and reimported before the step closes; every object created, replaced, or left off a dashboard is
accounted for; and the dashboard has been read back with the user. A declined dashboard, or no
reachable Dashboards, closes the step honestly.

## Return visits

Teams come back for three things once the seven steps are done:

- **Reviewing the metrics:** run every plan query against the live stores, put each number beside
  its target, and read them goal by goal (and by intent, where the plan names intents), plus the
  no-click inventory (zero-result and never-clicked), ranked by volume.
- **Extending the plan to a new feature:** diff the plan against the app's emitters; propose new
  rows through Map's approval and land them through Implement and Verify.
- **Judging accumulated behavior:** the Search Relevance Workbench turns the team's own clicks into
  a relevance judgment list, reported with the volume it rests on and what it cannot say. On the
  team's ask, it is kept running as a scheduled search-quality check
  ([judgments.md](references/judgments.md)).

All three procedures are in [return-visits.md](references/return-visits.md); a later dashboard ask
re-runs Step 7. None of them is a phase: the user's ask routes into them, never furthest-along-wins.
All three run after the Preflight gate (a red cluster has no numbers to report, no place to land new
events, no judgments to build), and all three read `ubi-metrics-plan.md`. An instrumented app with
no plan file gets the reconstruction offer first. If the user declines it, say plainly that the
visit needs the plan and stop there; the decline rule in
[metrics-plan.md](references/metrics-plan.md) explains why the emitters alone cannot stand in for
the plan.
