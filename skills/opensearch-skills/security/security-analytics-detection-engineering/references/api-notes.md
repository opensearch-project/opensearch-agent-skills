# Security Analytics API notes (observed on OpenSearch 2.19.1)

Verified 2026-08-03 against the official OpenSearch 2.19.1 full distribution
(`build_type: tar`) running natively on Linux, security plugin disabled. The
same artifact set ships in the `opensearchproject/opensearch:2.19.1` image.
All paths are relative to the cluster root; base is
`/_plugins/_security_analytics`.

## Ordering invariant (load-bearing)

Detectors are sequence-number based doc-level monitors. They only evaluate
documents indexed **after** detector creation. Pre-existing documents are
never retro-scanned. Consequences:

- A negative control indexed before detector creation is not evidence — the
  detector never evaluated it.
- Verification fixtures (positive AND negative) must be indexed after the
  detector exists and is enabled.
- Observed finding latency on a 1-minute schedule: ~40s.

## Rule lifecycle

Create — the body is the **raw Sigma YAML string**, not JSON, sent with
`Content-Type: application/json`; the category is a query parameter:

```
POST /_plugins/_security_analytics/rules?category=windows
<raw sigma yaml>
```

Response (HTTP 201) wraps the parsed rule and assigns a server-side `_id`:

```json
{"_id": "KrdHyZ8ByTgRlWGlXEzW", "_version": 1, "rule": {"category": "windows", ...}}
```

Use the response `_id` everywhere; the Sigma document's own `id:` field is
metadata only.

Delete: `DELETE /rules/<id>` → 200. If the rule is referenced by a detector,
deletion fails; `DELETE /rules/<id>?forced=true` overrides. Delete detectors
first and forced deletion is unnecessary.

## Field mappings

Before creating a detector, resolve index fields to the rule topic's expected
aliases:

```
GET  /_plugins/_security_analytics/mappings/view?index_name=<idx>&rule_topic=windows
POST /_plugins/_security_analytics/mappings
     {"index_name": "<idx>", "rule_topic": "windows", "partial": true}
```

Observed auto-resolution on a Sysmon-style index: `CommandLine ->
process.command_line`, `EventID -> winlog.event_id`, `Image ->
winlog.event_data.Image`. The `partial: true` call returns
`{"acknowledged": true}`.

## Detector lifecycle

```
POST /_plugins/_security_analytics/detectors
{
  "name": "<unique-name>",
  "detector_type": "windows",
  "enabled": true,
  "schedule": {"period": {"interval": 1, "unit": "MINUTES"}},
  "inputs": [{"detector_input": {
    "description": "...",
    "indices": ["<idx>"],
    "custom_rules": [{"id": "<rule _id>"}],
    "pre_packaged_rules": []
  }}],
  "triggers": []
}
```

Response (HTTP 201) includes `_id`, `detector.enabled`,
`detector.enabled_time`. Minimum schedule granularity observed: 1 minute.
Delete: `DELETE /detectors/<id>` → 200.

## Findings

```
GET /_plugins/_security_analytics/findings/_search?detector_id=<id>&size=100
```

Semantic 404: on a cluster with no detectors, this API returns HTTP 404 with
`"reason": "No detectors found "` — the API exists; treat this as available
during preflight, not as a missing plugin.

Attribution join keys in each finding:

- `queries[].id` — the Security Analytics rule `_id` that matched
- `related_doc_ids` — the matched document `_id`s
- `detectorId` — the detector that produced the finding
- `queries[].query` — the translated Lucene query, e.g.
  `(winlog.event_id: 1) AND (process.command_line: *\-EncodedCommand*)`

Both keys are stable and suitable for programmatic verification.

## Misc

- 512m heap is sufficient for this workload on 2.19.1.
- Preflight rule search: `POST /rules/_search?pre_packaged=true` with a
  `match_all` body → 200 even on a fresh cluster.
- Detector search: `POST /detectors/_search` with `match_all` → 200.

## Rule validation endpoint (2.19.1, observed)

`POST /_plugins/_security_analytics/rules/validate` exists, but it is NOT a
non-mutating content-validation API. Request shape:

```json
{"index_name": "<index>", "rules": ["<existing rule _id>", "..."]}
```

It checks whether already-created rules are applicable (field-mappable) to
the given index and returns `{}` when all supplied rules are applicable.
Rules must already exist — the mutation has already happened — so it cannot
pre-validate raw Sigma YAML. Passing a nonexistent rule id yields an HTTP 500
`index_out_of_bounds_exception`; a nonexistent index yields 404.

Consequence for this skill: pre-creation validation is local static analysis
(`validate-rule`), and OpenSearch acceptance is only proven by an actual
`POST /rules?category=...` (evidence state API_ACCEPTED).

## Permissions and preflight

The rest of these notes were observed on a security-disabled 2.19.1
distribution, so the enforcement described here is derived from the OpenSearch
Security plugin source and docs, not exercised live on that cluster.

Workflow privileges, by role:

- Security Analytics write access for custom rules and detectors, plus findings
  read. The built-in reserved role `security_analytics_full_access` grants this
  (it is defined in the security plugin's `config/roles.yml` as full Security
  Analytics access); a least-privilege role must cover the rule, detector,
  mapping, and findings actions this skill calls.
- Read, search, and write on the target index: mapping inspection, and the
  fixture indexing that `verify` performs.
- Index create/delete only when the workflow creates its own `sa-de-test*`
  index via `create-index`/`cleanup`.

`preflight` is read-only. It confirms the rules, detectors, and findings APIs
answer and fails closed on 401/403, naming the denied family. It does not prove
the caller may create a rule or detector: read and write are authorized
separately, and a denied create surfaces at runtime as a 403 that the CLI
reports as a structured failure without recording anything to the manifest.

### perform_permission_check is not available on 2.19.1

OpenSearch Security has a `perform_permission_check=true` request parameter that
runs a request through privilege evaluation and returns
`{"accessAllowed": ..., "missingPrivileges": [...]}` without executing it, which
would let `preflight` prove write access without creating anything. It is not in
the 2.19 line. On the security plugin's `2.19` branch the
`perform_permission_check` constant and its handling are absent from both
`ConfigConstants.java` and `SecurityRestFilter.java`; the constant is likewise
absent from `ConfigConstants.java` on the `3.0` branch (which defines the
parameter name the filter references). Both appear only on the development line,
where the check lives in the REST/transport privilege filter and is covered by a
plugin-endpoint dry-run integration test. Checked 2026-08-17.

Consequence for this skill on its 2.19.1 target: there is no non-mutating
write-permission probe. `preflight` proves read reachability; the authority on
create permission is the create call itself, which fails closed on a 403.
