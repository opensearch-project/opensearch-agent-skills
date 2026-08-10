# DLS Model Reference

## Core Design

Access control is enforced by OpenSearch's security plugin using
**Document-Level Security (DLS)** with a **Terms Lookup Query (TLQ)**. This means:

- One role definition covers all users - no role per user or per group.
- The filter runs at the shard level, before scoring, before the application sees results.
- The application query is a plain search with no ACL clause - the security layer
  is independent of the application.

## The Two Indexes

### Content index: `<index>` (e.g. `permission-aware-search`)

Holds the actual documents. Each document has an `allowed_users` field:

```json
{
  "_id": "doc-001",
  "title": "Q3 Budget Summary",
  "content": "The Q3 marketing budget is GBP 120,000...",
  "content_vector": [...],
  "allowed_users": ["alice", "GROUP_Finance", "GROUP_Everyone"],
  "path": "/Finance/Q3-Budget.pdf",
  "source_file": "Q3-Budget.pdf"
}
```

`allowed_users` is a flat keyword array. It should contain every principal
(individual user OR group name) that may read this document. Groups are stored
as plain strings (e.g. `GROUP_Finance`, `group:finance`) - the application is
responsible for populating this field correctly at ingest time.

### ACL lookup index: `<index>-acl` (e.g. `permission-aware-search-acl`)

Holds one document per user, keyed by username. Each document lists all principals
the user belongs to (themselves + their groups):

```json
{ "_id": "alice", "allowed_users": ["alice", "GROUP_Finance", "GROUP_Everyone"] }
{ "_id": "bob",   "allowed_users": ["bob",   "GROUP_HR",      "GROUP_Everyone"] }
```

This index is the "lookup side" of the TLQ. When alice queries, OpenSearch fetches
`permission-aware-search-acl/_doc/alice` and uses the `allowed_users` array from it to filter
the content index.

**Update this index whenever a user's group membership changes.**

## The DLS Role

Role name: `permission-aware-search-reader`

```json
{
  "cluster_permissions": [
    "cluster:admin/opensearch/ml/models/search",
    "cluster:admin/opensearch/ml/predict"
  ],
  "index_permissions": [
    {
      "index_patterns": ["permission-aware-search"],
      "dls": "{ \"terms\": { \"allowed_users\": { \"index\": \"permission-aware-search-acl\", \"id\": \"${user.name}\", \"path\": \"allowed_users\" } } }",
      "fls": ["~content_vector"],
      "allowed_actions": ["read"]
    }
  ]
}
```

The two cluster permissions are present only when `embedding.mode` is `local`,
because query-time inference searches for and invokes the embedding model. In
BM25-only mode, `cluster_permissions` is empty.

Three things happen simultaneously:
1. **DLS** - restricts documents to those where `allowed_users` intersects the
   calling user's principal list (looked up from `permission-aware-search-acl`).
2. **FLS** (`~content_vector`) - excludes the raw embedding vector from search
   results. Vectors are large and never needed in the response payload.
3. **Allowed actions** - read-only; query users cannot write or delete.

The role deliberately grants access only to the exact content index. The Security
plugin evaluates the TLQ as part of DLS; query users are not granted direct access
to the `permission-aware-search-acl` alias, its versioned backing index, or other
indexes sharing the content index prefix. This keeps user/group membership data
outside the application's searchable surface.

## Variable Substitution

`${user.name}` resolves to the authenticated username at query time. This is a
built-in OpenSearch security feature - no application code needed. The lookup
uses that value as the `_id` to fetch from the active versioned ACL snapshot.

## Authenticated Query Identity

Every search request must authenticate as the end user whose permissions should be
enforced. OpenSearch derives `${user.name}` from that authenticated identity and
uses it as the ACL lookup document ID. A shared application credential would make
all callers resolve to the same ACL document and must not be used for production
queries. Never use `admin`, which bypasses DLS.

For local demos, create named internal users and map each one to the single reader
role. In production, use an authentication domain such as a trusted proxy or
JWT/OIDC and map its users or backend roles to `permission-aware-search-reader`.
This design still uses one DLS role; it does not require a separate role per user.

## What "Group" Means Here

Groups are not an OpenSearch concept - they are strings in `allowed_users`. The
skill stores group names as plain strings (e.g. `GROUP_Finance`) in both the
content documents and the ACL lookup index. The DLS filter checks set
intersection between the two - it does not distinguish users from groups.

**At ingest time:** `allowed_users` on each document must contain every principal
(individual username OR group name) that may read it.

Document ACLs are not an identity source. The `ingest` command never copies these
principals into user ACL lookup documents because co-readers are not necessarily
members of one another's groups. Populate the lookup index only with `sync-acl` or
`refresh-acl` using an authoritative user-to-principals mapping.

**Keeping group membership current:** when a user's group membership changes in
the source directory, the ACL lookup index must be updated or the DLS filter will
use stale data. Use `refresh-acl` to pull live membership automatically.

## Group Membership and `refresh-acl`

`refresh-acl` connects to a directory source, resolves every user's complete
principal list (username + all groups), and rebuilds the ACL lookup index
using a versioned snapshot:

1. Writes all ACL documents to a new `<index>-acl-<version>` backing index.
2. Refreshes the new index and validates its document count.
3. Replaces the reader role once so its DLS Terms Lookup targets the new complete
   backing index.
4. Uses one atomic alias transaction to attach the administrative `<index>-acl`
   alias to the new snapshot and delete the previous backing index.

Searches therefore see either the complete old snapshot or the complete new one,
never a partially updated mixture. Removed users and groups disappear at the same
role update as new grants become visible. If snapshot construction or validation
fails, the role remains on the previous complete snapshot and the candidate is
removed. The role switch is the authorization commit point: if later alias cleanup
fails, the new snapshot remains active and the command reports the cleanup error
without restoring revoked access. The error identifies the active backing index
and stable alias so an administrator can repair the alias without deleting the
authorization target. If a pre-commit candidate cannot be deleted after a failed
build or role update, the command reports its exact name for manual cleanup. The
same replacement behavior applies to `sync-acl`.

The Security plugin does not resolve an index alias used inside this DLS Terms
Lookup, so the role must name the active concrete backing index. The stable alias
is retained for administrative inspection and lifecycle management; query users
have no permissions on either target.

Cleanup uses the OpenSearch [Manage Aliases API](https://docs.opensearch.org/latest/api-reference/alias/aliases-api/),
which applies all actions in a request as one atomic transaction.

`refresh-acl` reads a static JSON file that maps each group name to its complete
member username list, and inverts it into each user's principal list. Export this
file from your authoritative identity source (directory, HR system, or ECM) on
whatever cadence membership changes. Use `sync-acl` for an already expanded
user-to-principals mapping.

```bash
# From a group -> members JSON file
uv run python scripts/permission_search.py refresh-acl \
  --file /path/to/groups.json
```

**Scheduling:** run `refresh-acl` on whatever cadence group membership changes in
the source system - hourly is a reasonable default for most enterprise directories.
The command is safe to run repeatedly; it is fully idempotent.

## DLS and kNN (Vector Search)

OpenSearch DLS is applied as a pre-filter wrapping the entire query, including kNN
sub-queries. However, there is a known nuance: when using the `knn` query type with
`ef_search`, the DLS filter is applied after the kNN candidate set is retrieved.
This means in large indexes with tight permission boundaries, a user might receive
fewer than `k` results even when more eligible documents exist.

Local semantic mode combines a BM25 `multi_match` clause and a kNN clause in
`bool.should`, with `minimum_should_match: 1`. OpenSearch uses standard Boolean
score summation for this query; no normalization pipeline or fixed clause weights
are applied. DLS wraps and restricts the combined query, so inaccessible lexical
and vector matches are excluded.

OpenSearch's `hybrid` query is deliberately not used. It must remain the top-level
query, but TLQ DLS runs at filter level and wraps the request query. A secured
cluster returns `hybrid query must be a top level query` for that combination.
Use a different authorization model, such as attribute substitution without TLQ
filter-level rewriting, before adopting a normalization-based hybrid query.

References: [OpenSearch hybrid query](https://docs.opensearch.org/latest/query-dsl/compound/hybrid)
and [TLQ DLS evaluation modes](https://docs.opensearch.org/latest/security/access-control/document-level-security/#use-term-level-lookup-queries-tlqs-with-dls).

## Security Plugin Requirement

DLS requires the OpenSearch security plugin. The standard Docker image
(`opensearchproject/opensearch:latest`) ships with it enabled by default.

If the security plugin is disabled (`DISABLE_SECURITY_PLUGIN=true`), DLS cannot be
configured and this skill cannot proceed. Explain that the plugin must be enabled
and stop; `check-security` fails for exactly this reason.

Do not substitute an application-layer `terms` filter on `allowed_users`. Any
caller that can reach the cluster can omit that filter, so it enforces nothing
while looking like access control. Enabling the security plugin is the only
supported path.

## Authentication Is Independent Of Authorization

How a user proves identity and how the ACL index is populated are separate
concerns from the DLS authorization core, which is unchanged by either.

DLS resolves `${user.name}` to whatever principal the security plugin
authenticated, regardless of the authentication method. OIDC/Keycloak, JWT, SAML,
and proxy auth therefore work with no change to the DLS role or the ACL model:
configure the authentication domain on the cluster, then map those identities (or
their backend roles) to `permission-aware-search-reader`.

What matters is that the identity reaching OpenSearch is the end user's own. A
shared service account resolves `${user.name}` to the service, not the caller, so
every user would see that account's documents. Passing the username in an
application header does not help, because DLS reads the authenticated identity
rather than request headers. Use direct end-user authentication or a trusted
proxy/JWT domain that establishes the caller as the OpenSearch user.

The `query` CLI authenticates with HTTP Basic, so it drives clusters using
username and password. Applications are not restricted to that: they authenticate
their own way and need only the role mapping plus current ACL data.

## Adding An ACL Synchronization Source

`lib/group_resolver.py` defines a `DirectoryBackend` Protocol
(`get_all_user_principals() -> {user: [principals]}`) and `build_resolver`
dispatches on a `source` string. The static `file` backend ships today; another
source (a directory service, an HR export, a custom identity store) is a
self-contained extension:

1. Implement the `DirectoryBackend` Protocol (one method).
2. Add a `source` branch in `build_resolver`.
3. Add its flags and environment variables in
   `permission_search._directory_config` and the `refresh-acl` subparser.
4. Add an optional dependency group in `pyproject.toml` if it needs a library,
   and surface the import failure through `_optional_dependency_error`.
5. Add unit tests mirroring the existing `FileBackend` tests.
