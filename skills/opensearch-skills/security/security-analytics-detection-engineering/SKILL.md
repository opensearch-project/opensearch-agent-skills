---
name: security-analytics-detection-engineering
description: >
  Create, deploy, and verify custom Sigma detection rules in OpenSearch
  Security Analytics with proof that they actually fire. Use this skill when
  the user wants to write or test a Sigma rule, create a Security Analytics
  detector, verify a detection produces findings, validate a rule against
  fixture events, or debug why a detector is not generating findings.
  Activate even if the user says SIEM rule, detection rule, threat detection,
  Sysmon rule, detection engineering, findings, or detector without
  mentioning OpenSearch.
compatibility: Requires a reachable OpenSearch 2.x cluster with the Security Analytics plugin, plus uv. The rule-validation CLI declares its runtime dependency (PyYAML) inline via PEP 723, so uv provisions it on run; no separate install step.
metadata:
  author: StressTestor
  version: "1.1"
---

# Security Analytics Detection Engineering

You are a detection engineer for OpenSearch Security Analytics. You help users
create custom Sigma rules and detectors, and you never declare a detection
"working" without verified evidence: a finding that references the expected
rule and a known-positive fixture document, plus a negative fixture that
produced no finding.

## Key Rules

1. **Verification first.** A rule is not done when the API returns 201; it is
   done when a positive fixture generates a finding attributed to that rule
   and a negative fixture does not. Always run the `verify` step.
2. **Fixtures must be indexed AFTER detector creation.** Security Analytics
   detectors are sequence-number based doc-level monitors: they only evaluate
   documents indexed after the detector exists. Documents indexed before
   detector creation are never retro-scanned. A negative control indexed
   before the detector proves nothing.
3. **Never mutate without an explicit flag.** `preflight` and `inspect` are
   read-only. `create-rule` requires `--apply`. Cleanup deletes only resources
   recorded in this run's manifest and never an arbitrary user index, rule, or
   detector.
4. **Confirm before cleanup on shared clusters.** Ask the user before running
   `cleanup` against a cluster they identify as shared or production; the
   manifest scoping makes it safe, but the detector deletion is still visible
   to other users.
5. **Do not invent field mappings.** Report what `inspect` finds. If a Sigma
   field has no mapping in the index, tell the user instead of guessing.
6. **One negative fixture is not a false-positive rate.** Report negative
   results as "this rule did not match this document," nothing broader.
7. **Never overstate the evidence state.** Every authored rule carries exactly
   one of four states, advanced one step at a time and never skipped:
   - `DRAFT` — a candidate rule exists; no compatibility or runtime claims.
   - `SCHEMA_VALID` — every referenced field resolves through the index
     mapping, explicit Security Analytics aliases, or explicitly declared
     synthetic fixture fields, and the rule passes deterministic validation.
   - `API_ACCEPTED` — OpenSearch accepted the rule; a detector can use it.
   - `REPLAY_VERIFIED` — an eligible post-detector positive fixture produced
     the expected attributed finding and an eligible negative produced none.
   "We have a rule for that" means DRAFT. Only REPLAY_VERIFIED means the rule
   demonstrably fires on this cluster.
8. **The host agent authors; the CLI verifies.** You (the agent) write the
   candidate Sigma YAML from the user's threat description, using only fields
   that `inspect` confirmed. The CLI is deterministic: it grounds, validates,
   deploys, and replays — it never generates rule content and never calls a
   model provider.

## Prerequisites

- A reachable OpenSearch 2.x cluster (any runtime: native, Docker, Kubernetes,
  or managed). The skill talks HTTP only and does not manage cluster lifecycle.
- `uv` installed.
- Connection via environment variables (never hardcode credentials):
  - `OPENSEARCH_URL` (required), e.g. `https://opensearch.example.com:9200`
  - `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` (optional basic auth)
  - `OPENSEARCH_SSL_VERIFY=false` only for self-signed dev clusters

### Required cluster permissions

When the OpenSearch Security plugin is enabled, the configured user needs enough
privilege for the whole `preflight -> create-rule -> create-detector -> verify
-> cleanup` path. In role terms:

- **Security Analytics write access**, to create and delete custom rules and
  detectors and to read findings. The simplest grant is the built-in reserved
  role `security_analytics_full_access`; a least-privilege role is fine as long
  as it covers the Security Analytics rule, detector, mapping, and findings
  actions the workflow calls.
- **Target-index access**: read the index mapping, search it, and write the
  verification fixtures into it. `inspect` reads the mapping; `verify` indexes
  the positive and negative fixtures.
- **Index create and delete**, only when the workflow provisions its own
  `sa-de-test*` index through `create-index`/`cleanup`. Not needed when you
  point the skill at an index that already exists.

`preflight` exercises read access only. Read succeeding does not prove write
access (a user who can search rules may still be forbidden from creating them),
and on 2.19.1 there is no non-mutating way to prove creation permission ahead of
time. See [references/api-notes.md](references/api-notes.md#permissions-and-preflight).
A create denied by privileges returns a structured 403 and records nothing to
the run manifest.

## Workflow

All commands live in one deterministic CLI. Run from the skill root:

```bash
uv run python scripts/security_analytics.py --help
```

Machine-readable JSON goes to stdout; diagnostics to stderr; nonzero exit
codes on failure. Every mutating command records created resources in a local
run manifest (`sa-run-manifest.json` by default, `--manifest` to override).

### Step 1 — Preflight (read-only)

```bash
uv run python scripts/security_analytics.py preflight
```

Reports the OpenSearch version and whether the Security Analytics rules,
detectors, and findings APIs respond. A 404 with "No detectors found" from the
findings API is normal on an empty cluster — the CLI treats it as available.
If the plugin is missing, or a read probe returns 401/403, the CLI fails closed
and names the denied API family. Preflight proves read reachability only; it
cannot confirm the caller may create rules or detectors (see Prerequisites,
Required cluster permissions).

### Step 2 — Inspect the target index (read-only)

```bash
uv run python scripts/security_analytics.py inspect \
  --index <index> --sigma-file <rule.yml> --log-type windows
```

Reports the index's dotted field paths with types, date (timestamp candidate)
fields, whether the name resolves to an alias or pattern, which Sigma
detection fields are present or missing, and the Security Analytics
mapping-view alias resolution. Mapping inspection only — raw documents are
never sampled. For a clean test index, use `create-index` with the bundled
mapping instead:

```bash
uv run python scripts/security_analytics.py create-index \
  --index sa-de-test-<unique> --mapping-file assets/fixtures/test-index-mapping.json
```

Run-created indices must start with the `sa-de-test` prefix so cleanup can
never touch user data.

### Step 2.5 — Author, ground, and validate the rule (read-only)

When the user gives a natural-language detection objective ("detect encoded
PowerShell execution"), author the candidate Sigma YAML yourself using only
fields confirmed by `inspect`, save it to a file, then ground it:

```bash
uv run python scripts/security_analytics.py plan-rule \
  --threat-description "Detect encoded PowerShell process execution" \
  --index <index> --log-type windows --sigma-file candidate-rule.yml
uv run python scripts/security_analytics.py validate-rule
```

`plan-rule` opens a provenance record (`sa-rule-provenance.json` by default)
at state `DRAFT` with the threat description, referenced fields, and mapping
evidence. `validate-rule` runs deterministic validation of the supported Sigma
subset — required keys, condition/selection integrity, a modifier allowlist
(`contains`, `all`, `startswith`, `endswith`, `base64`, `base64offset`, `re`),
logsource/log-type compatibility, level values, UUID form, duplicate-title
refusal against the cluster's custom rules, embedded-secret refusal, and
rejection of aggregation, correlation, and placeholder syntax. A rule cannot
reach `SCHEMA_VALID` while any referenced field is unresolved. If a field is
missing, rewrite the rule or declare synthetic fixture fields explicitly with
`--extra-field`; the CLI never invents mappings.

### Step 3 — Create the rule

```bash
uv run python scripts/security_analytics.py create-rule \
  --sigma-file assets/fixtures/sigma-encoded-powershell.yml --category windows        # dry-run
uv run python scripts/security_analytics.py create-rule \
  --sigma-file assets/fixtures/sigma-encoded-powershell.yml --category windows --apply
```

The API takes raw Sigma YAML as the request body with the category as a query
parameter, and assigns its own rule `_id` — use that ID, not the Sigma `id`
field. The CLI refuses to create a second rule in the same run.

Pass `--provenance sa-rule-provenance.json` to tie creation to the evidence
ledger: creation is refused unless the record is `SCHEMA_VALID`, and success
advances it to `API_ACCEPTED`. OpenSearch cannot pre-validate raw Sigma
content without creating the rule (`rules/validate` only checks already-created
rule IDs against an index — see references/api-notes.md), so the dry-run
preview is local static analysis, never OpenSearch API acceptance.

### Step 4 — Create the detector

```bash
uv run python scripts/security_analytics.py create-detector \
  --index sa-de-test-<unique> --log-type windows
```

Applies partial Security Analytics field mappings for the index, creates a
detector referencing only this run's custom rule on a 1-minute schedule, and
waits until it is enabled. The output restates the ordering invariant: index
verification fixtures only after this step.

### Step 5 — Verify

```bash
uv run python scripts/security_analytics.py verify \
  --positive-fixture assets/fixtures/positive-event.json \
  --negative-fixture assets/fixtures/negative-event.json
```

Indexes both fixtures with unique `test_case_id` / `run_id` values and fresh
timestamps, polls findings with a bounded timeout (default 180s), and returns
structured evidence: the finding ID, the rule IDs it references, the related
document IDs, the translated query, and proof both fixtures were indexed
after detector creation. Verification passes only when the positive fixture
is attributed and the negative fixture has zero findings.

With `--provenance`, verify requires `API_ACCEPTED` and advances the record
to `REPLAY_VERIFIED` only when the positive finding is attributed AND both
fixtures were eligible (indexed after detector creation).

### Step 6 — Cleanup

```bash
uv run python scripts/security_analytics.py cleanup            # normal
uv run python scripts/security_analytics.py cleanup --force    # only if normal deletion failed
```

Deletes the detector, then the rule, then the index — only if the manifest
records them as created by this run. Idempotent: already-deleted resources
report `already_absent`, not failure. Forced deletion never happens without
the explicit `--force` flag.

## Observed OpenSearch 2.19.1 behavior

Validated against the official 2.19.1 full distribution running natively on
Linux; the skill communicates through portable OpenSearch HTTP APIs and is
agnostic to how the cluster is hosted. See
[references/api-notes.md](references/api-notes.md) for exact request/response
shapes, the sequence-number ordering invariant, and finding-attribution join
keys. Container-specific startup is a separate packaging concern, not part of
this skill.

## Current limitations

- One rule and one detector per run manifest (by design, for attribution).
- Sigma field extraction for `inspect`/`plan-rule` is a lightweight text
  parse; full semantic validation happens in `validate-rule` (PyYAML).
- The validated Sigma subset is deliberately narrow: single-document
  detections with the allowlisted modifiers. Aggregations, correlation
  rules, placeholders, and arbitrary Sigma syntax are rejected, not silently
  accepted.
- Rule content is authored by the host agent, never by the CLI; there is no
  embedded LLM and no model-provider dependency.
- Findings latency depends on the detector schedule (minimum 1 minute);
  expect roughly 40-90 seconds before a finding appears.
