---
name: permission-compiler
description: >
  Compile a representative OpenSearch workflow into an evidence-backed,
  observed-minimum Security role candidate. Use when debugging 403 or
  MISSING_PRIVILEGES errors, designing least-privilege roles, validating
  permissions for search, PPL, Dashboards, snapshots, ingest, or automation,
  or replacing broad all_access and security_rest_api_access grants.
compatibility: Requires Python 3.11+ and test-user credentials for an OpenSearch cluster.
metadata:
  author: Eienel
  version: "1.0"
---

# OpenSearch Permission Compiler

Turn what a service must do into a narrow, reviewable role candidate backed by
OpenSearch's own permission decisions.

## Key rules

1. Never claim mathematical least privilege. The output is the minimum observed
   for the representative workflow and evidence supplied.
2. Never infer an index pattern. Require the user or workflow manifest to name
   the intended index boundary.
3. Never execute a mutating probe. Add `perform_permission_check=true` to every
   representative request.
4. Never apply a generated role automatically. Emit a candidate and review
   report for a human administrator.
5. Never derive grants from a negative probe. A denied operation is an
   invariant that must remain denied.
6. Prefer exact actions observed from OpenSearch. Do not replace them with a
   broader action group for convenience.
7. Read credentials from environment variables. Do not write credentials or
   authorization headers into workflow, evidence, or report files.
8. Always verify the TLS certificate chain and hostname. Require a CA
   certificate for private certificate authorities; never disable verification.

## Workflow

### 1. Define the capability contract

Create a JSON workflow containing:

- a stable workflow name and candidate role name;
- one representative request per required operation;
- explicit `index_patterns` for index-scoped operations;
- `expect: "allow"` for required operations;
- `expect: "deny"` for destructive or out-of-scope operations.

Start with [the workflow schema](workflow-schema.md) and the bundled
[Search API example](assets/search-readonly-workflow.json).

### 2. Run safe probes

Use test-user credentials, never an administrator identity. Run commands from
this skill's directory so bundled paths resolve:

```bash
export OPENSEARCH_URL="https://localhost:9200"
export OPENSEARCH_USERNAME="workflow-test-user"
export OPENSEARCH_PASSWORD="..."

uv run python scripts/permission_compiler.py probe \
  --workflow assets/search-readonly-workflow.json \
  --ca-cert /path/to/root-ca.pem \
  --output build/evidence.json
```

The probe adds `perform_permission_check=true`. Write-like requests are checked
for authorization but are not executed.

The probe resolves the target once per request, rejects metadata, link-local,
and other special-use addresses, and pins the connection to a validated IP.
The original hostname remains the TLS verification name and HTTP `Host` value.
Public HTTPS targets work by default. For a private-network or loopback HTTPS
cluster, explicitly add an exact `--allow-private-address` for every resolved
cluster IP; this does not permit cloud metadata or redirect targets. Plaintext
HTTP remains limited to literal loopback addresses for local development.
Redirects fail the probe and are never followed, so credentials are not
replayed to a `Location` target.

### 3. Compile exact observed actions

```bash
uv run python scripts/permission_compiler.py compile \
  --workflow assets/search-readonly-workflow.json \
  --evidence build/evidence.json \
  --output build/candidate-role.json \
  --report build/evidence-report.json
```

Stop if the report contains unknown or conflicting evidence steps, parse
warnings, positive probes that derived no permissions, index actions without a
declared scope, or a negative probe that was allowed. Treat wildcards as a
mandatory review item.

### 4. Review blast radius

For every permission, show:

- the workflow step and evidence source that produced it;
- whether it is cluster- or index-scoped;
- the declared index boundary;
- whether it contains a wildcard;
- which negative probes protect the boundary.

Do not hide raw OpenSearch action names behind a narrative summary.

### 5. Validate after a human applies the candidate

Re-run all positive and negative probes with the test identity:

```bash
uv run python scripts/permission_compiler.py verify \
  --workflow assets/search-readonly-workflow.json \
  --evidence build/post-apply-evidence.json \
  --report build/verification-report.json
```

Success requires every positive probe to be allowed, every negative probe to
remain denied, and no required step to remain unobserved.

### 6. Produce the handoff

Return:

1. candidate role JSON;
2. evidence and coverage report;
3. unresolved gaps;
4. exact commands for a human administrator to review and apply;
5. rollback instructions;
6. a warning that production traffic may use capabilities absent from the
   representative workflow.

## Interpreting evidence

- `missingPrivileges`: use the exact returned actions.
- `security_exception` with `no permissions for [...]`: extract the action list.
- audit category `MISSING_PRIVILEGES`: use `audit_request_privilege`.
- `no permissions for []`: do not invent an action; flag it for investigation.
- Endpoint errors that name an action without returning a supported permission
  evidence shape are unresolved, not grants.

OpenSearch 3.7.0's PPL endpoint can return
`Unexpected exception cluster:admin/opensearch/ppl` under
`perform_permission_check=true` without a reliable `missingPrivileges` array.
Do not convert that response into a permission. Use other supported evidence or
escalate for manual investigation.

## Completion condition

Complete the task only when the candidate is evidence-backed, required probes
pass, forbidden probes remain denied, and remaining uncertainty is explicit.
