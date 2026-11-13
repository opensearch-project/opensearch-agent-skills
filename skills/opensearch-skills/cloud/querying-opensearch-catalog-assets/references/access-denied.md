# Access denied (401 / 403)

Goal: name the layer that denied the request, confirm it with read-only calls where you are
allowed to, and propose the smallest read-only grant for this one index. You never apply it.

## 1. Collect the facts

- Status code, the `x-aoss-response-hint` response header (AOSS), and `error.type` / `reason`
  or `Message` from the body.
- `aws sts get-caller-identity`. For an assumed role
  (`arn:aws:sts::<acct>:assumed-role/<role>/<session>`) get the role ARN, path included, with
  `aws iam get-role --role-name <role> --query Role.Arn`. Grants name the role ARN, never the
  session ARN.

## 2. Find the layer

Check signing first: a signing error looks like an access denial.

| Engine | Signal | Layer |
|---|---|---|
| both | 403 with a signature or credential message | Signing: service name (`aoss`/`es`), Region, `x-amz-content-sha256` signed, session token sent, no `:443`, credentials not expired. Fix and retry once. |
| AOSS | 401, hint `X01:network-policy-deny` | Network policy does not allow this source (public, or a VPC endpoint). |
| AOSS | 403, hint `X01:gw-helper-deny` | Data access policy does not grant this principal the operation on `index/<collection-name>/<index>`. |
| AOSS | 403, no hint, signing correct | IAM: the principal lacks `aoss:APIAccessAll` on the collection. |
| AOS | 403 `Message` naming an `es:ESHttp*` action | Domain resource policy or the principal's IAM policy. |
| AOS | 403 `security_exception`, reason starts `no permissions for [` | Fine-grained access control: the principal is not mapped to a role that can read the index. |
| AOS | 401 | Request unsigned or credentials expired. Re-sign. Never ask for a master user or password. |

## 3. Confirm (read-only; each call may itself be denied, which is fine to report)

AOSS:

```bash
aws opensearchserverless list-security-policies --type network
aws opensearchserverless get-security-policy --type network --name <name>
aws opensearchserverless list-access-policies --type data
aws opensearchserverless get-access-policy --type data --name <name>
aws iam simulate-principal-policy --policy-source-arn <role-arn> \
  --action-names aoss:APIAccessAll --resource-arns <collection-arn>
```

Look for a rule whose resource matches `collection/<collection-name>` (network) or
`index/<collection-name>/<index>` (data, patterns allowed) and whose principals include the
role ARN. Data access policies name the collection by name, not ID.

AOS:

```bash
aws opensearch describe-domain --domain-name <name> --query DomainStatus.AccessPolicies
```

With FGAC enabled, `GET /_plugins/_security/authinfo` (Elasticsearch:
`/_opendistro/_security/authinfo`) is allowed for any authenticated user and returns your
`user_name`, `backend_roles` and `roles`. No role that grants read on the index means the
mapping is missing.

## 4. Propose the grant (do not apply it)

Present it as: layer, identity (role ARN), scope (this index only), exact JSON, and who can
apply it (the collection or domain administrator). If the user asks you to apply it, follow
security rule 3 in SKILL.md.

AOSS data access policy rule:

```json
[{"Description": "Read-only access to <index>",
  "Rules": [{"ResourceType": "index",
             "Resource": ["index/<collection-name>/<index>"],
             "Permission": ["aoss:DescribeIndex", "aoss:ReadDocument"]}],
  "Principal": ["<role-arn>"]}]
```

AOSS IAM statement:
`{"Effect": "Allow", "Action": "aoss:APIAccessAll", "Resource": "<collection-arn>"}`

AOSS network policy: do not propose public access. Tell the user the request must come from a
source the policy already allows, or an administrator must add that source's VPC endpoint.

AOS domain access policy statement. Name the read paths, never `<index>/*`: `ESHttpPost` on the
whole index would also allow writes such as `_bulk` and `_update_by_query`.

```json
{"Effect": "Allow", "Principal": {"AWS": "<role-arn>"},
 "Action": ["es:ESHttpGet", "es:ESHttpHead", "es:ESHttpPost"],
 "Resource": [
   "arn:aws:es:<region>:<account>:domain/<domain>/<index>/_search*",
   "arn:aws:es:<region>:<account>:domain/<domain>/<index>/_count",
   "arn:aws:es:<region>:<account>:domain/<domain>/<index>/_msearch",
   "arn:aws:es:<region>:<account>:domain/<domain>/<index>/_mapping",
   "arn:aws:es:<region>:<account>:domain/<domain>/<index>/_field_caps"]}
```

Add `domain/<domain>/_plugins/_sql` or `_plugins/_ppl` only if the user needs SQL or PPL: those
paths are domain-wide, so with FGAC off they reach every index.

AOS FGAC role and mapping (Elasticsearch: `_opendistro` instead of `_plugins`). `PUT` on an
existing mapping replaces it, so tell the administrator to add the backend role to it instead:

```
PUT _plugins/_security/api/roles/<index>-read
{"index_permissions": [{"index_patterns": ["<index>"], "allowed_actions": ["read"]}]}

PUT _plugins/_security/api/rolesmapping/<index>-read
{"backend_roles": ["<role-arn>"]}
```

Add `"cluster_permissions": ["cluster_composite_ops_ro"]` only if you need `_msearch` or `_mget`.

## Another account

AOSS data access policies accept only principals in the collection's account. Cross-account
reads need a role in that account that the user may assume; ask the user for it.
