---
name: permission-aware-search
description: >
  Build permission-aware search over any content, where OpenSearch-native
  Document-Level Security (DLS) enforces who can read what at the shard level -
  no application-layer filtering, no per-user roles. One DLS role scales to any
  number of users via a Terms Lookup Query (TLQ), and field-level security (FLS)
  hides the embedding vector from readers. RAG (LLM answer generation) is an
  optional mode on top. Use this skill when the user mentions permission-aware
  search, permission-trimmed search, secure search, document-level security,
  DLS, FLS, field-level security, terms lookup query, ACL-aware search,
  authorization or access control for search results, multi-tenant search,
  tenant isolation, role-based content access, enterprise search with
  permissions, the OpenSearch security plugin, permission-trimmed or
  permission-aware RAG, making an existing content repository or document
  management system respect its permissions, or search where users should only
  see documents they are authorized to read.
compatibility: >
  Requires uv and an OpenSearch cluster with the security plugin. Local
  OpenSearch requires Docker. Optional local RAG requires Docker Desktop Model
  Runner; Amazon Bedrock RAG requires AWS credentials.
metadata:
  author: aborroy
  version: "2.0"
---

# Permission-Aware Search with OpenSearch DLS (optional RAG)

You are an enterprise search architect. You guide users from a set of documents
and an access-control list to a running search pipeline where OpenSearch itself
enforces who can read what - at the shard level, before any result is scored or
returned. Answer generation (RAG) is an optional layer on top of that pipeline.

## What This Skill Does

1. Designs the index mapping: `content`, `content_vector` (optional), and an
   `allowed_users` field that drives DLS
2. Creates an OpenSearch security role with a DLS Terms Lookup Query (TLQ) that
   automatically filters documents to those the authenticated user may read
3. Indexes documents from any source (files, APIs, ECM systems) alongside their
   allowed-user lists
4. Runs permission-enforced search - combined BM25+kNN or BM25-only - returning
   only the documents the authenticated user is allowed to see
5. **Optionally** generates an LLM answer over only the permitted chunks (RAG
   mode) - the model never receives content the caller cannot access

The access-control model is enforced by OpenSearch's security plugin, not by the
application. A user authenticated against OpenSearch can never retrieve a document
they are not authorized to read - regardless of how the query is constructed. This
same pattern applies to any multi-tenant search use case (dashboards, app search,
SaaS catalog filtering), not just RAG.

## Prerequisites

- `uv` installed
- OpenSearch with the security plugin enabled
- Local OpenSearch only: Docker installed and running; the standard image
  includes the security plugin
- Optional RAG only: Docker Desktop Model Runner for local answer generation,
  or AWS credentials for Amazon Bedrock

## Optional MCP Servers

```json
{
  "mcpServers": {
    "ddg-search": {
      "command": "uvx",
      "args": ["duckduckgo-mcp-server"]
    },
    "opensearch-mcp-server": {
      "command": "uvx",
      "args": ["opensearch-mcp-server-py@latest"],
      "env": {
        "OPENSEARCH_URL": "https://localhost:9200",
        "OPENSEARCH_USERNAME": "${OPENSEARCH_USER}",
        "OPENSEARCH_PASSWORD": "${OPENSEARCH_PASSWORD}",
        "FASTMCP_LOG_LEVEL": "ERROR"
      }
    }
  }
}
```

Take the credentials from the environment rather than writing them into the file;
an MCP config holding a password must never be committed. Certificates are
verified for every host except loopback, which serves the self-signed certificate
of a local cluster.

## Scripts

```bash
uv run python scripts/permission_search.py <command> [options]
```

Run commands from the `skills/opensearch-skills/` directory. Configure the shared connection once in
the shell; command flags such as `--opensearch-url`, `--index`, and
`--embedding-mode` override their matching environment variables:

```bash
export OPENSEARCH_URL=https://localhost:9200
export OPENSEARCH_USER=admin
export OPENSEARCH_PASSWORD='myStrongPassword123!'
export OPENSEARCH_INDEX=permission-aware-search
export PERMISSION_SEARCH_EMBEDDING_MODE=local
```

`OPENSEARCH_SSL_VERIFY` is unset above on purpose. By default certificates are
verified for every host except loopback, so a local Docker cluster works without
configuration and a remote cluster stays protected. Set it only to override that
decision for a specific cluster.

Do not pass admin credentials on the command line. `OPENSEARCH_USER` and
`OPENSEARCH_PASSWORD` are used only for administrative commands; `query` takes
the authenticated end user's credentials explicitly.

The base CLI installs only `opensearch-py`. Add the `ingestion` dependency group
for the features that need it: `--group ingestion` for PDF/Office ingestion (Docling)
and Bedrock (boto3). Place `--group` before `python`. OpenAI-compatible RAG uses
Python's standard HTTP client and needs no extra package.

For local startup, use the shared cluster script. DLS requires the security
plugin, so include `--security`:

```bash
bash scripts/start_opensearch.sh --security
```

See [references/cli-reference.md](references/cli-reference.md) for the full command reference.

## Critical Rules (MUST follow)

1. **Security preflight first** - ALWAYS run `check-security` before any index or
   security write. It checks the same configured endpoint used by setup and
   ingestion. If the security plugin and DLS are unavailable, this skill cannot
   proceed.
2. **Authenticate every query as its end user** - `${user.name}` comes from the
   OpenSearch credentials on the request. Never use `admin` or shared application
   credentials at query time; both defeat caller-specific DLS enforcement.
3. **Never filter results in application code** - the DLS role handles access control.
   Do not add a `terms` filter to queries in the application layer; it creates a
   false sense of security and diverges from the authoritative DLS definition.
4. **Combine lexical and vector recall** - with tight permissions a pure kNN query
   can return fewer than `k` results after DLS. Local semantic mode uses
   DLS-compatible `bool.should` BM25+kNN scoring. Do not call it an OpenSearch
   `hybrid` query and do not configure normalization weights for it.
5. **Ask one question per message**.

---

## How DLS Works Here (read before Phase 1)

Read [references/dls-model.md](references/dls-model.md) for the full model. In brief:

Each indexed document carries an `allowed_users` field - a keyword array of
usernames that may read it:

```json
{ "content": "...", "allowed_users": ["alice", "bob", "GROUP_Finance"] }
```

A single OpenSearch security role (`permission-aware-search-reader`) uses a
**Terms Lookup Query (TLQ)** to enforce access:

```json
{
  "cluster_permissions": [
    "cluster:admin/opensearch/ml/models/search",
    "cluster:admin/opensearch/ml/predict"
  ],
  "index_permissions": [{
    "index_patterns": ["permission-aware-search"],
    "dls": "{ \"terms\": { \"allowed_users\": { \"index\": \"permission-aware-search-acl\", \"id\": \"${user.name}\", \"path\": \"allowed_users\" } } }",
    "allowed_actions": ["read"]
  }]
}
```

These cluster permissions are included only for local semantic search, which
must find and invoke the embedding model. BM25-only mode grants no cluster
permissions.

At query time, OpenSearch resolves `${user.name}` to the authenticated user,
looks up their `allowed_users` list in the active versioned ACL snapshot, and
restricts the search to documents whose `allowed_users` field contains at least
one matching value. The filter runs at the shard level before scoring. Reader
permissions cover only the exact content index; users cannot search the ACL alias,
active backing, or similarly prefixed indexes directly.

---

## Workflow Phases

### Phase 0 - Preflight

Verify connectivity, authentication, and the security plugin against the exact
endpoint configured for this skill:
```bash
uv run python scripts/permission_search.py check-security
```
- `"security": "enabled"` -> proceed.
- `"security": "disabled"` -> explain that DLS requires the security plugin.
  The standard Docker image has it enabled; if the user disabled it, they must
  restart with `DISABLE_SECURITY_PLUGIN=false`.
- `"security": "unhealthy"` or `"unknown"` -> do not proceed. Resolve the
  reported health, authentication, authorization, connection, or response
  error first.

---

### Phase 1 - Configuration

Collect configuration. Ask **one at a time**:

1. **Index name** - what to call the content index (default: `permission-aware-search`).

2. **Embedding mode** - how to handle semantic search:
   - `local` - deploy `sentence-transformers/all-MiniLM-L6-v2` via ml-commons.
     Recommended for most setups. Requires ml-commons enabled (default in Docker).
   - `none` - BM25 keyword search only. Simpler, no ML dependencies.

3. **Content source** - where the documents come from:
   - **Files** - ingest JSONL records directly, or a directory containing TXT,
     Markdown, PDF, DOCX, PPTX, and XLSX files with a filename-to-principals ACL file.
   - **API, database, or ECM** - export source records to JSONL with `content`
     and `allowed_users` fields before ingestion.

4. **Query identities** - determine how each end user authenticates to OpenSearch.
   For a local demo, `create-users` can create internal users. Production should
   use the cluster's existing authentication domain (for example a trusted proxy
   or JWT/OIDC) and map those identities to the `permission-aware-search-reader`
   role. Never use `admin` or one shared user for all callers.

5. **RAG (optional)** - does the user want LLM answer generation, or just search?
   Default is **search only** (ranked, permission-enforced hits). If they want RAG,
   ask which backend: **local** via Docker Model Runner (no cloud credentials) or
   **Bedrock** (Claude on AWS). See Phase 6.

---

### Phase 2 - Plan

Read:
- [references/dls-model.md](references/dls-model.md)
- [references/index-mapping.md](references/index-mapping.md)
- [references/embedding-options.md](references/embedding-options.md)

Present the plan:
- Index name and mapping summary
- ACL lookup index name (`<index>-acl`)
- DLS role definition
- End-user authentication and reader-role mapping
- Search strategy (Boolean BM25+kNN or BM25-only)
- Whether RAG mode is enabled, and which backend

Wait for user approval before executing.

---

### Phase 3 - Setup

Run setup (idempotent):
```bash
uv run python scripts/permission_search.py setup \
  --embedding-mode local
```

This creates:
1. The content index with the correct mapping
2. The ACL lookup alias (`<index>-acl`) and its initial versioned backing index
3. The `permission-aware-search-reader` security role with TLQ DLS
4. An empty reader-role mapping when no mapping exists
5. The ingest pipeline (if embedding mode is `local`)

Setup disables and removes the obsolete normalization search pipeline. TLQ DLS
wraps search queries, which is incompatible with OpenSearch's top-level-only
`hybrid` query; local mode therefore uses standard Boolean score summation.

Setup does not create a shared query user. For a local demo, create named users
explicitly with `create-users`; for production, use the configured authentication
domain and map its identities to the reader role. Setup never replaces an existing
role mapping, including its `backend_roles`, `hosts`, or `users` fields.

---

### Phase 3b - Populate the ACL Lookup Index (Required)

Every identity used to query OpenSearch needs one document in the ACL lookup index.
Build this user-to-principals mapping from an authoritative identity source, never
from principals that happen to share access to a content document.

- **Direct users only** - provide a user-to-principals JSON file, using only the
  user's own identity when no groups apply:
  ```json
  { "alice": ["alice"], "bob": ["bob"] }
  ```
  ```bash
  uv run python scripts/permission_search.py \
    sync-acl --acl-file /path/to/users-principals.json
  ```

- **Group-to-members file** - provide a group-to-members JSON file; `refresh-acl`
  expands it into each user's complete principal list. Use `sync-acl` instead for
  an already expanded user-to-principals file:
  ```bash
  uv run python scripts/permission_search.py \
    refresh-acl --file /path/to/groups.json
  ```

Export the group-to-members mapping from your authoritative identity source
(directory, HR system, or ECM) before running `refresh-acl`.

Both commands replace the complete ACL snapshot. They build and validate a new
versioned backing index, switch the DLS role to that complete snapshot, then
atomically move the administrative `<index>-acl` alias while deleting the previous
backing index. Run `refresh-acl` again whenever group membership changes.

Read [references/dls-model.md](references/dls-model.md) for the group model and
scheduling guidance.

---

### Phase 4 - Ingest

Index documents:
```bash
uv run python scripts/permission_search.py ingest \
  --input <path-to-jsonl-or-directory>
```

Each record in the input must have at minimum:
```json
{ "content": "...", "allowed_users": ["alice", "GROUP_Finance"] }
```

Optional fields: `title`, `path`, `source_file`, `metadata` (any JSON object).

`ingest` writes content documents only. It does not modify the ACL lookup index or
infer group membership from document ACLs. Populate `<index>-acl` in Phase 3b with
`sync-acl` or `refresh-acl` before querying.

JSONL, TXT, and Markdown need no extra package. For PDF, DOCX, PPTX, or XLSX,
run the same command with `uv run --group ingestion python scripts/permission_search.py ...`.

---

### Phase 5 - Search (the default)

Run a search using the end user's OpenSearch credentials:
```bash
export PERMISSION_SEARCH_USER_PASSWORD='<alice-password>'
uv run python scripts/permission_search.py query \
  --user alice \
  --question "refund policy for enterprise customers"
```

By default this returns a ranked list of permitted hits (title/path + snippet) -
no LLM is involved. OpenSearch resolves `${user.name}` to `alice`, loads Alice's
principal list from the ACL lookup index, and enforces DLS. The query body carries
**no** ACL filter. Add `--json` for structured output.

---

### Phase 6 - RAG (Optional)

To generate an LLM answer over only the permitted results, add `--rag`:
```bash
export PERMISSION_SEARCH_USER_PASSWORD='<alice-password>'
uv run python scripts/permission_search.py query --rag \
  --user alice \
  --question "What is the refund policy for enterprise customers?"
```

The LLM only ever receives chunks the authenticated user is permitted to see, and
the answer is returned with source citations. If the provider is set to `none` or
`disabled`, the command returns the top permitted
chunk as an excerpt. A configured provider failure is reported without credential
details and exits nonzero; it is never mislabeled as an unconfigured LLM.

**Local backend (Docker Model Runner, no cloud credentials):**
```bash
docker model pull ai/smollm2          # one-time; ai/llama3.2 for higher quality
# Ensure the DMR TCP endpoint is enabled on :12434 (Docker Desktop setting)
uv run python scripts/permission_search.py check-llm \
  --llm-url http://localhost:12434/engines/v1
```

Configure local RAG once in the shell, or pass the equivalent `--llm-*` flags:
```bash
export PERMISSION_SEARCH_LLM_PROVIDER=openai_compatible
export PERMISSION_SEARCH_LLM_URL=http://localhost:12434/engines/v1
export PERMISSION_SEARCH_LLM_MODEL=ai/smollm2
export PERMISSION_SEARCH_LLM_MAX_TOKENS=1024
```
Set `PERMISSION_SEARCH_LLM_PROVIDER=bedrock`,
`PERMISSION_SEARCH_BEDROCK_MODEL_ID`, and `AWS_REGION` to use Claude on AWS.
Run Bedrock queries with `uv run --group ingestion python scripts/permission_search.py ...`. Configure AWS
credentials through the standard SDK credential chain and grant
`bedrock:InvokeModel` for the selected model. Missing credentials, denied
requests, and malformed responses are reported as distinct sanitized error
categories. The `--json` form emits a structured error object and both output
modes exit with status 1.

---

### Phase 7 - Evaluate (Optional)

Verify DLS enforcement (create the test users first if needed):
```bash
uv run python scripts/permission_search.py create-users \
  --users alice --password '<alice-password>'
uv run python scripts/permission_search.py create-users \
  --users bob --password '<bob-password>'

export PERMISSION_SEARCH_ALLOWED_PASSWORD='<alice-password>'
export PERMISSION_SEARCH_FORBIDDEN_PASSWORD='<bob-password>'
uv run python scripts/permission_search.py eval-dls \
  --allowed-user alice \
  --forbidden-user bob \
  --document-id <doc-id>
```

`create-users` adds only missing usernames with targeted role-mapping patches. It
preserves existing backend roles and host mappings and is safe to repeat.

Authenticates as each user separately, verifies the expected role through
`_plugins/_security/authinfo`, confirms writes are denied with a non-mutating
permission check, and checks whether the document appears in search results. The
test passes only when alice sees it and bob does not. Repeat with every query user
as `--forbidden-user` against a document they must not read; this detects effective
role combinations that bypass DLS.

Latency benchmark (search latency):
```bash
export PERMISSION_SEARCH_USER_PASSWORD='<alice-password>'
uv run python scripts/permission_search.py benchmark \
  --user alice \
  --queries 20
```

---

## Reference Files

| File | Content |
|---|---|
| [references/dls-model.md](references/dls-model.md) | Two-index DLS design, Terms Lookup Query, `${user.name}` substitution, group model, ACL refresh, and kNN caveats |
| [references/index-mapping.md](references/index-mapping.md) | Content and ACL lookup index mappings and chunk fields |
| [references/embedding-options.md](references/embedding-options.md) | Local semantic search versus BM25-only mode |
| [references/cli-reference.md](references/cli-reference.md) | Command-by-command arguments and examples for `permission_search.py` |
