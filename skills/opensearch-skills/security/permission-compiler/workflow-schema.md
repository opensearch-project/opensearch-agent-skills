# Workflow schema

The compiler accepts a JSON object:

```json
{
  "name": "search-readonly",
  "role_name": "search-readonly-observed",
  "steps": [
    {
      "id": "search-logs",
      "method": "POST",
      "path": "/logs-*/_search",
      "body": {"query": {"match_all": {}}},
      "index_patterns": ["logs-*"],
      "expect": "allow"
    },
    {
      "id": "must-not-delete",
      "method": "DELETE",
      "path": "/logs-2026.07.29",
      "index_patterns": ["logs-*"],
      "expect": "deny"
    }
  ]
}
```

## Fields

- `name`: stable capability-contract name.
- `role_name`: OpenSearch role name to emit.
- `steps[].id`: stable evidence join key.
- `steps[].method`: HTTP method.
- `steps[].path`: root-relative path beginning with `/`; absolute URLs,
  protocol-relative paths, and fragments are rejected.
- `steps[].body`: optional JSON request body.
- `steps[].index_patterns`: intended data boundary. Required whenever evidence
  yields an `indices:*` action.
- `steps[].expect`: `allow` or `deny`.
- `tenant_permissions`: optional, explicitly reviewed tenant grants. Tenant
  permissions are not inferred from transport-action errors.

The format captures a security contract, not a general API test suite.
