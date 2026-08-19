# The managed path: UBI on Amazon OpenSearch Service

Pinned against the [UBI managed-services tutorial](https://docs.opensearch.org/latest/search-plugins/ubi/ubi-aws-managed-services-tutorial/)
and the Amazon OpenSearch Ingestion (OSIS) docs, fetched 2026-08-08. This file
is an overlay on [ubi-schema.md](ubi-schema.md): the stores, field names, join
semantics, and traps there apply unchanged. What changes is who builds the
query record and how records travel.

## When this branch runs

The gate's check 2 found no `opensearch-ubi` in the cluster's plugin
list, and the cluster is a managed service where the team cannot install
one. **The list is the authority, not the provider's name**: a
managed domain that carries the plugin passes check 2 and takes the plugin
path, and this file never applies to it. Amazon OpenSearch Service
(`*.es.amazonaws.com`, or a domain behind a custom endpoint) is that
no-plugin cluster today, and the provider every claim below is pinned
against. With no plugin, its two jobs move:

- **Query capture moves into the app.** There is no `ext.ubi` and no
  server-side capture: the app builds the query record itself at search time
  and ships it (shape below).
- **Transport is OpenSearch Ingestion.** Two OSIS pipelines (each an HTTP
  source, an OpenSearch sink into its store, and an optional S3 sink for
  long-term retention) carry query records and events into `ubi_queries` and
  `ubi_events`.

Amazon OpenSearch Serverless stays outside this branch: the tutorial
sanctions managed domains only, and this branch claims no more than its
source.

**On a managed provider other than AWS, this file splits in two.** The capture
contract carries: the app builds the query record below, the Implement
deltas' document shapes hold, and `ext.ubi` never leaves the app. The
transport does not: OSIS, SigV4, and the IAM section are AWS's own, so
records reach the stores as direct index writes from the app's backend
instead, under the transport contract in
[ubi-schema.md](ubi-schema.md#emitting-events). No pinned source has run
that leg; name it unmeasured when promising it.

**`ext.ubi` never leaves the app on this branch.** The block belongs to the
plugin; a domain without the plugin has no handler for the section, and a
search carrying it fails: instrumenting the plugin way on a managed domain
breaks the search itself.

## Branch preflight (replaces the gate's checks 3 and 4)

Checks 1 and 2 already ran: credentials resolve, the domain is ACTIVE,
the endpoint answers a SigV4-signed request, and the plugin-list read
that routed here came back without `opensearch-ubi`. Then:

1. **Stores exist with the plugin's shipped mappings.** There is no
   initialize endpoint here: create each index manually, after the
   go-ahead Critical Rule 5 requires, from the pair vendored in
   [ubi-schema.md](ubi-schema.md). Take them from there and not from the
   plugin repo, because a mapping fetched mid-session comes from whatever
   `main` holds that day, so the same setup run twice would build different
   stores. The `PUT` form and the store creation's place in the setup
   artifact are in [cluster-setup.md](cluster-setup.md). Check the result
   against the store tables in ubi-schema.md: `ubi_queries` must be
   `dynamic: false` with `query_attributes` as `flat_object`. The
   malformed-store trap applies identically: an auto-created or
   hand-guessed mapping fails joins silently, forever.
2. **Both pipelines ACTIVE.** `ubi-queries-pipeline` and
   `ubi-events-pipeline` (`aws osis get-pipeline ... --query
   'Pipeline.Status'`). Missing pipelines are created from the YAML below,
   after the user's explicit go-ahead: an OSIS pipeline bills per OCU-hour
   for as long as it runs, minimum one OCU each. Name the cost before
   creating.
3. **The pipelines deliver.** POST one probe query record (JSON array, SigV4)
   to the queries pipeline's ingest endpoint, poll `ubi_queries` until it
   lands, then delete it. Landing is not instant; pipeline buffering is
   normal, not a red check. The branch's form of the probe cycle, and why
   the probe is found by a `query_id` value rather than a fixed `_id`, are
   in [cluster-setup.md](cluster-setup.md).

## IAM

The role mechanics (pipeline role creation, trust policy, domain access
policy) are the family's
[managed-ingestion-service iam-setup](../../../cloud/managed-ingestion-service/iam-setup.md).
The deltas for this branch:

- The pipeline role (trusted by `osis-pipelines.amazonaws.com`) needs
  `es:ESHttpPost`, `es:ESHttpPut`, `es:ESHttpGet`, `es:ESHttpHead` on the
  domain, plus `s3:PutObject` on the bucket only if the S3 sink is kept.
- The domain's access policy must admit that role.
- The identity that POSTs records (the probe, and later the app) needs
  `osis:Ingest` on the pipeline.

## The pipelines

Save each YAML under `.opensearch/pipelines/` (family convention). These files
stay in the repo: they are this branch's part of the setup artifact
([cluster-setup.md](cluster-setup.md)), which is what Critical Rule 2 counts
them under and why nothing here deletes them. Create with:

```yaml
version: "2"
ubi-queries-pipeline:
  source:
    http:
      path: "/ubi/queries"
  sink:
    - opensearch:
        hosts: [ "https://<domain-endpoint>" ]
        aws:
          region: "<region>"
          sts_role_arn: "<pipeline-role-arn>"
        index: ubi_queries
        index_type: custom
```

The events pipeline is the same with three substitutions: name
`ubi-events-pipeline`, path `/ubi/events`, index `ubi_events`. The tutorial's
optional second sink (the same records to S3 as NDJSON for retention) is
offered, not assumed; keep it only if the user wants the archive, and add the
`s3:PutObject` grant with it.

The ingest URL comes from the created pipeline's `IngestEndpointUrls`;
records POST to `https://<ingest-endpoint>/ubi/queries` (or `/ubi/events`)
as JSON **arrays**, SigV4-signed for service `osis`.

## The query record: the app builds what the plugin built

Same fields as the `ubi_queries` table in [ubi-schema.md](ubi-schema.md),
now filled by the app when the search response returns:

```json
[{
  "query_id": "app-generated UUID, the join key",
  "user_query": "the text the user actually typed",
  "query": "the raw query DSL, as a string",
  "query_response_id": "app-generated UUID for this response",
  "query_response_hit_ids": ["the returned objects' ids, in presented order"],
  "query_attributes": {},
  "client_id": "opaque id for this browser/device or visit",
  "application": "which app issued the search",
  "timestamp": "2026-08-08T12:00:00.000+0000"
}]
```

## Implement deltas

- **Server side:** in place of the `ext.ubi` block, the app builds the query
  record above and POSTs it to the queries pipeline when the search returns.
  There is no response echo to forward; the app-generated `query_id` is
  what travels to every event emitter.
- **Client side:** emitters are unchanged in document shape; they POST to the
  events pipeline's endpoint instead of indexing into `ubi_events` directly.
  How those writes travel is the same contract
  ([Emitting events](ubi-schema.md#emitting-events)), with one substitution:
  a page of impressions is one POST carrying the whole JSON array, which is
  this branch's form of the `_bulk`. The backend relay gains a second
  reason on top of the credential one: pipeline endpoints require SigV4,
  which a browser cannot sign. The backend can still emit directly for
  actions it observes itself.
- **The event contract holds here too, and nothing on this path enforces
  it.** Every event row carries `user_query`, every impression and click its
  `position.ordinal` ([ubi-schema.md](ubi-schema.md) for why). On the plugin
  path the server-side capture at least records the typed text on the query
  row; here the app writes both records itself, so an emitter that omits the
  field leaves it nowhere, and nothing upstream will supply it or complain.

## Verify deltas

The four checks run unchanged, with SigV4-signed queries against the domain.
On a red row, work this catalog before the plugin-path one:

- **Row missing but the POST returned 200:** pipeline buffering. Wait,
  `POST /<store>/_refresh`, and re-check before declaring the row red. The
  S3 sink adds its own collection timeout on top; the OpenSearch sink
  flushes sooner.
- **POST returns 403:** the caller lacks `osis:Ingest` on the pipeline, or
  the request was signed for the wrong service or region: the service is
  `osis`, not `es`.
- **The search itself fails after instrumentation:** `ext.ubi` crept into
  the search request; this branch never sends it.
- **Query record rejected with a mapping error:** an epoch-millis timestamp
  reached `ubi_queries`, whose format is `strict_date_time`.

## Step 7: Dashboard

The step runs on a managed domain. What changes about it (the unchanged
import surface, the index patterns pointing at this branch's app-built
records rather than the plugin's stores, and the admission that the variant
has never been run against a live domain) is in the managed-path section of
[dashboards.md](dashboards.md).

One delta belongs here, because it is an access fact rather than a dashboard
one: the domain's Dashboards has its own front door. The address is the
domain's dashboards URL, and reaching it may be governed by Cognito or an
IAM-signed proxy rather than by the credentials the Audit found. Ask for the
address *and* how it authenticates. Where the answer is that nobody in the
room has that access, the step closes honestly and the plan file still holds
every query someone with access can run.

## The judgments hand-off

Verify's judgment row and the judgment visit both assume the
search-relevance plugin; on a managed domain, check its availability before
promising either. Detection, the version floors, and the enable are in
[judgments.md](judgments.md); the row itself runs here unchanged, against the
same stores this branch's pipelines fill.
