# The analytics bridge: the tool the team already trusts

The Audit found the app reporting behavior to an analytics tool (a GA4
or gtag snippet; a Segment, PostHog, or Amplitude client), or the
session exposes one as a connected tool: that is this file's trigger.

The bridge is two lanes, each one-way, and neither moves what Critical
Rule 2 protects: reports, plan queries, and judgment data stay in the
conversation, the plan file, and the user's cluster. Lane one carries
numbers **in** from the tool. Lane two carries opaque identifiers
**out**, on events the app already sends. Nothing else crosses.

## Naming the tool

The Audit's finding is the app's truth: the snippet in the code is the
tool the team runs. The connected-tool scan is the session's: look for
that tool among the tools this session exposes. When the two agree,
the bridge has its tool. When the session exposes several, or one that
contradicts the code, ask which tool speaks for their traffic; never
settle it by which happens to answer.

## Lane one: numbers read in

Reading the tool is free, like any read (Critical Rule 5). Three reads
earn the lane:

- **The search volume, at Elicit.** Prefer the tool's own search
  events (GA4's `view_search_results`, a tracked site-search event):
  that count is a search volume. A tool holding only sessions gives a
  session figure, and the plan line says which it is
  ([metrics-plan.md](metrics-plan.md) pins both forms).
- **A baseline, while a target is agreed.** Where the tool already
  holds the metric the room is setting a target for, read the number
  while they set it. A target agreed against a read baseline writes
  the baseline's date instead of `no baseline`.
- **The business outcome, on a review visit.** Where the plan's
  `Business outcome:` line names a wall, the tool often holds the
  outcome itself. Read it and put it beside the stand-in row's number,
  dated and sourced. The stand-in stays the row; the tool's number is
  context beside it, never a row of its own.

Every number read from the tool lands dated and sourced, in the plan's
pinned parenthetical or in the conversation. A number with no source
reads later as the room's own, which it never was.

## Lane two: identifiers stamped out

The offer is made once, at Map, and only where the Audit found the
tool. Each vendor event the app already fires on an audited UI action
gains the same `query_id`, `client_id`, and `session_id` the UBI
events carry, as event properties, from the same generation points
Map's identity rule already requires: a third consumer of one set of
identifiers, never a second minting site.

What it buys the team: their own tool segments any funnel by searched
sessions, and a row-level join between the vendor's store and
`ubi_events` becomes possible on `query_id`. That join is the team's
build, not this session's — the same settlement as the attribution
wall in [reachability.md](reachability.md).

The screen: the ids are opaque (Critical Rule 3) and they travel; the
typed text does not. `user_query` never enters a vendor property
through this offer. What the vendor's own search events already
capture is the team's standing choice; this offer adds ids and adds
nothing else.

The gate: an identifier that outlives the visit reaches a third party
only through the gate the Audit found, the same routing Map's
persistence rule gives it. A decliner's vendor events carry the
per-visit ids only, and the lane still works within the visit.

Declining the offer changes nothing, and the offer is not repeated in
the session.

## Landing and verifying the stamp

For Implement's and Verify's checks, an accepted offer counts like an
approved mapping row: Implement's check is not met while the stamp
lacks its emitting change, and Verify reads it back like any row. It
lands beside the client-side emitters: one property set per existing
vendor call, in the app's conventions, and no new vendor calls.
Verify scopes its claim to what it can read
(Critical Rule 4): where the connected tool can query the vendor's
store, read one fresh event back and match its `query_id` to the fresh
pair; where it cannot, the user confirms the property on one fresh
event in the vendor's own event view, and the claim says a human read
it there.

## What the bridge never carries

UBI events keep their own short path to the stores. They never route
through the vendor, a CDP, or a collector on the way to `ubi_events`:
every hop between the emitter and the store is a place for a field to
vanish with nothing erroring, and joinability is the contract. A team
that wants one emission fanned out builds that on their side of the
join, with the stamped ids to build it on.
