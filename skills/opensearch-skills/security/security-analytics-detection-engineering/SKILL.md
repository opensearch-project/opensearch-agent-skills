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
compatibility: Requires a reachable OpenSearch 2.x cluster with the Security Analytics plugin, plus uv.
metadata:
  author: StressTestor
  version: "1.0"
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

## Prerequisites

- A reachable OpenSearch 2.x cluster (any runtime: native, Docker, Kubernetes,
  or managed). The skill talks HTTP only and does not manage cluster lifecycle.
- `uv` installed.
- Connection via environment variables (never hardcode credentials):
  - `OPENSEARCH_URL` (required), e.g. `https://opensearch.example.com:9200`
  - `OPENSEARCH_USERNAME` / `OPENSEARCH_PASSWORD` (optional basic auth)
  - `OPENSEARCH_SSL_VERIFY=false` only for self-signed dev clusters

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
If the plugin is missing or the user lacks permissions, stop and report.

### Step 2 — Inspect the target index (read-only)

```bash
uv run python scripts/security_analytics.py inspect \
  --index <index> --sigma-file <rule.yml> --log-type windows
```

Reports the index's fields, which Sigma detection fields are present or
missing, and the Security Analytics field-mapping view. For a clean test
index, use `create-index` with the bundled mapping instead:

```bash
uv run python scripts/security_analytics.py create-index \
  --index sa-de-test-<unique> --mapping-file assets/fixtures/test-index-mapping.json
```

Run-created indices must start with the `sa-de-test` prefix so cleanup can
never touch user data.

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
- Sigma field extraction for `inspect` is a lightweight text parse — it
  reports candidate fields, not a full Sigma semantic model.
- No natural-language rule generation, correlation rules, or ATT&CK coverage
  analysis in this slice.
- Findings latency depends on the detector schedule (minimum 1 minute);
  expect roughly 40-90 seconds before a finding appears.
