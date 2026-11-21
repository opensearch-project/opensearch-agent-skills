# permission_search.py CLI Reference

```bash
uv run python scripts/permission_search.py <command> [options]
```

Run examples from the `skills/opensearch-skills/` directory. Set `OPENSEARCH_URL`, `OPENSEARCH_USER`,
`OPENSEARCH_PASSWORD`, `OPENSEARCH_INDEX`, and `OPENSEARCH_SSL_VERIFY` in the
shell. Non-secret connection settings can instead be supplied with
`--opensearch-url`, `--index`, and `--ssl-verify`/`--no-ssl-verify`. Embedding,
chunking, and LLM settings follow the same environment-or-flag pattern;
use `<command> --help` for the complete list.

The base script depends only on `opensearch-py`. Optional features are installed
per invocation:

| Feature | Invocation prefix |
|---|---|
| PDF/Office ingestion | `uv run --group ingestion python` |
| Amazon Bedrock RAG | `uv run --group ingestion python` |

OpenAI-compatible RAG uses the Python standard library and needs no extra package.

## check-security

Verify the security plugin is enabled and DLS is available.

```bash
uv run python scripts/permission_search.py check-security
```

Output:
```json
{ "security": "enabled", "dls_supported": true }
```

The command exits nonzero with `security` set to `disabled`, `unhealthy`, or
`unknown` when the plugin is missing, reports `DOWN`, or cannot be verified.
The `error` field distinguishes plugin, health, credentials, connection,
transport, and malformed-response failures.

## setup

Create indexes and the DLS reader role. Idempotent.

```bash
uv run python scripts/permission_search.py setup
```

Creates:
- Content index with mapping
- ACL lookup index
- `permission-aware-search-reader` security role with TLQ DLS
- Empty reader-role mapping, unless an existing mapping is already configured
- Ingest pipeline (if embedding mode is `local`)

Setup configures no search pipeline. Local semantic mode uses a DLS-compatible
Boolean BM25+kNN query, not an OpenSearch `hybrid` query, so it needs no
normalization processor.

Setup intentionally creates no shared query user. Use existing production
identities or the `create-users` demo helper, then map them to the reader role.
Existing role-mapping `backend_roles`, `hosts`, and `users` are left unchanged.
The demo helper appends only missing usernames with targeted Security API patches.

## ingest

Index documents from a JSONL file or directory of files.

```bash
uv run python scripts/permission_search.py ingest \
  --input /path/to/documents.jsonl \
  --batch-size 50
```

Each JSONL record must have `content` and `allowed_users`. Optional: `title`,
`path`, `source_file`, `metadata`.

`ingest` writes content documents only. It never derives user memberships or
updates the ACL lookup index. Run `sync-acl` or `refresh-acl` separately using an
authoritative user-to-principals source.

Each chunk is indexed under a document id derived from its source, so re-ingesting
the same input overwrites those chunks instead of adding a second copy. Documents
are searchable when the command returns. If any document is rejected, the command
reports it under `index_errors` and exits non-zero rather than reporting the whole
batch as indexed.

Also accepts a directory of `.txt`, `.md`, `.pdf`, `.docx`, `.pptx`, and `.xlsx`
files with a `--acl-file` mapping file. `--acl-file` applies only to a directory:
a `.jsonl` input carries `allowed_users` on each record, so combining the two is
rejected rather than silently ignored.

PDF and Office files are converted by the shared document pipeline, which picks a
conversion profile from the document itself (including OCR for scanned pages),
converts in page batches so peak memory stays bounded, and reports the heading
trail and page number of each chunk. Those land in the `headings` and
`page_number` fields, so an answer can cite where a passage came from. Chunking
comes from the converter, which follows document structure; `--chunk-size` and
`--chunk-overlap` apply to `.jsonl` and plain-text input. `--max-pages` caps the
pages converted per document (default 10).

```bash
uv run --group ingestion python scripts/permission_search.py ingest \
  --input /path/to/docs/ \
  --acl-file /path/to/acl.json
```

ACL file format:
```json
{
  "report.pdf":     ["alice", "GROUP_Finance"],
  "handbook.docx":  ["GROUP_Everyone"]
}
```

Output:
```json
{ "indexed": 142, "skipped": 3 }
```

Unsupported extensions are counted as skipped. If a supported document cannot
be converted, the output includes an `errors` entry with its filename,
`conversion_failed` reason, and exception type; raw converter messages are not
returned. The command finishes processing other files, then exits nonzero.

## sync-acl

Replace the complete ACL lookup snapshot from a static users-to-principals file.
Use `refresh-acl` instead when a live directory is available.

```bash
uv run python scripts/permission_search.py sync-acl \
  --acl-file /path/to/users-principals.json
```

Users-principals format:
```json
{
  "alice": ["alice", "GROUP_Finance", "GROUP_Everyone"],
  "bob":   ["bob",   "GROUP_HR",      "GROUP_Everyone"]
}
```

## refresh-acl

Rebuild the ACL lookup index from a group-to-members file and atomically replace
the complete ACL lookup snapshot. Preferred over `sync-acl` when you have group
membership rather than an already expanded user-to-principals mapping.

```bash
# From a group -> members JSON file
uv run python scripts/permission_search.py refresh-acl \
  --file /path/to/groups.json
```

Both ACL commands are authoritative replacements: users absent from the new
mapping and principals removed from a user are revoked in the same role update.
Export the group-to-members mapping from your authoritative identity source
(directory, HR system, or ECM) before running `refresh-acl`.

**JSON file format:**

Group -> member list (inverted automatically):
```json
{ "GROUP_Finance": ["alice", "charlie"], "GROUP_Everyone": ["alice", "bob"] }
```

Use `sync-acl` for an already expanded user -> full principal list.

Output:
```json
{ "status": "ok", "users_refreshed": 42, "source": "file" }
```

## query

Search as an explicitly authenticated end user. OpenSearch resolves
`${user.name}` from these credentials. Prefer the environment variable so the
password does not appear in shell history or process arguments.

```bash
export PERMISSION_SEARCH_USER_PASSWORD='<alice-password>'
uv run python scripts/permission_search.py query \
  --user alice \
  --question "What is the refund policy for enterprise customers?"
```

Use `--rag` for answer generation and `--json` for structured output. Never use
`admin` or one shared credential for multiple callers. Setting
`PERMISSION_SEARCH_LLM_PROVIDER=none` returns a permitted excerpt. Failures from a configured
provider instead produce a sanitized error and exit with status 1; JSON mode
includes `provider`, `category`, and `message` fields. Categories are limited to
`configuration`, `provider`, and `invalid_response`. Bedrock uses the standard
AWS SDK credential chain and requires `bedrock:InvokeModel` for the configured
model; SDK and service details are intentionally omitted from errors.

For RAG, add the provider dependency group before `python`:

```bash
uv run python scripts/permission_search.py query --rag <options>
uv run --group ingestion python scripts/permission_search.py query --rag <options>
```

## eval-dls

Verify DLS enforcement and the effective security context. The command calls
`_plugins/_security/authinfo` as both users, requires the expected reader role,
uses a non-mutating permission check to confirm writes are denied, and verifies
that one user can read the document while the other cannot.

```bash
export PERMISSION_SEARCH_ALLOWED_PASSWORD='<alice-password>'
export PERMISSION_SEARCH_FORBIDDEN_PASSWORD='<bob-password>'
uv run python scripts/permission_search.py eval-dls \
  --allowed-user alice \
  --forbidden-user bob \
  --document-id doc-001
```

Relevant output fields:
```json
{
  "allowed_user_sees_document": true,
  "forbidden_user_sees_document": false,
  "effective_user_checks": [
    {
      "user": "alice",
      "roles": ["permission-aware-search-reader"],
      "expected_role_assigned": true,
      "write_blocked": true
    }
  ],
  "pass": true
}
```

Exits with code 1 if the test fails. Run each query user as `--forbidden-user`
against at least one document they must not read. This tests the complete effective
role set, including configurations where a non-DLS role can override DLS. The
reported role list may include unrelated roles such as `own_index`; access and
write probes determine whether the effective combination is safe for this index.

## benchmark

Measure query latency.

```bash
export PERMISSION_SEARCH_USER_PASSWORD='<alice-password>'
uv run python scripts/permission_search.py benchmark \
  --user alice \
  --queries 20
```

Output:
```json
{ "p50_ms": 310, "p99_ms": 1240, "min_ms": 180, "max_ms": 1890 }
```
