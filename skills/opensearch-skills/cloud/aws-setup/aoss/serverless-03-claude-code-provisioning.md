---
name: aoss-nextgen-provisioning
description: Use when provisioning or deprovisioning OpenSearch Serverless collections, creating collection groups, setting up AOSS NextGen, or tearing down AOSS resources
---

# OpenSearch Serverless NextGen Provisioning & Deprovisioning

## Overview

Guided wizard for provisioning and deprovisioning Amazon OpenSearch Serverless (AOSS) NextGen collections. Handles the full orchestration: security policies, collection groups, and collections — in the correct dependency order.

## When to Use

- Customer wants to create an OpenSearch Serverless collection
- Customer wants to set up AOSS NextGen
- Customer wants to delete/deprovision AOSS resources
- Customer mentions "collection group", "opensearch serverless", "AOSS"

## Key Constraints

- `"standbyReplicas": "ENABLED"` is MANDATORY for all NextGen collection groups (never allow DISABLED)
- `"generation": "NEXTGEN"` is REQUIRED for NextGen collection groups. This field is not yet in the botocore model, so `create-collection-group` MUST use `--endpoint-url "https://aoss.<region>.amazonaws.com"` to bypass client-side validation. All other commands use `--cli-input-json` normally.
- AWS credentials must be pre-configured; check first and stop if missing
- Execute commands directly — do not generate scripts for the user to run
- Collections must be in ACTIVE status before they can be deleted. NextGen collections typically take ~30 seconds; standalone collections can take 3-5 minutes.
- OCU capacity limits must be: 1, 2, 4, 8, 16, or any multiple of 16

## Quick Reference

| Action | Flow | What it creates |
|--------|------|-----------------|
| New NextGen collection (defaults) | Simple | enc policy + net policy + group + collection |
| New NextGen collection (customized) | Advanced | enc policy + net policy + group (with limits) + collection |
| New standalone collection (v1) | Standalone | enc policy + net policy + collection |
| Add collection to existing group | Add to Group | collection (+ policies if needed) |
| Delete resources | Deprovision | Removes collections → group → policies |

### Naming Convention (Auto-Generated)

| Resource | Name Pattern |
|----------|-------------|
| Collection | `<user-provided-name>` |
| Collection group | `<name>-group` |
| Encryption policy | `<name>-enc-policy` |
| Network policy | `<name>-net-policy` |
| Data access policy | `<name>-access-policy` |

---

## Entry Point

### Step 1: Credential Check

Run:
```bash
aws sts get-caller-identity
```

If this fails, tell the user: "AWS credentials are missing or expired. Please configure credentials (e.g., `aws configure` or set environment variables) and try again." Then STOP.

### Step 2: Mode Selection

Ask the user:

```
What would you like to do?

1. Provision (Simple) — New NextGen collection group + collection with defaults
2. Provision (Advanced) — Preset-based setup with full parameter control
3. Provision standalone collection — Collection without a collection group (classic)
4. Add collection to existing group — Create a collection in an existing collection group
5. Deprovision — Tear down collection(s) and/or collection group
```

Proceed to the corresponding flow section below.

---

## Flow 1: Simple Provisioning

### Inputs

Collect from the user (one at a time):
1. **Collection name** — 3-32 chars, lowercase letters, numbers, hyphens. Must start with a letter. Pattern: `[a-z][a-z0-9-]+`
2. **Collection type** — SEARCH, TIMESERIES, or VECTORSEARCH
3. **Region** — AWS region (e.g., us-east-1, us-east-2, us-west-2)

### Execution

Run these commands in order. Stop and report if any command fails.

**1. Create encryption policy:**
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "encryption",
  "name": "<name>-enc-policy",
  "policy": "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AWSOwnedKey\":true}"
}' --region <region>
```

**2. Create network policy (public access):**
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "network",
  "name": "<name>-net-policy",
  "policy": "[{\"Description\":\"Public access for <name>\",\"Rules\":[{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/<name>\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AllowFromPublic\":true}]"
}' --region <region>
```

**3. Create collection group (NextGen):**
```bash
aws opensearchserverless create-collection-group \
  --name <name>-group \
  --standby-replicas ENABLED \
  --generation NEXTGEN \
  --endpoint-url "https://aoss.<region>.amazonaws.com" \
  --region <region>
```

**4. Create collection:**
```bash
aws opensearchserverless create-collection --cli-input-json '{
  "name": "<name>",
  "type": "<TYPE>",
  "collectionGroupName": "<name>-group"
}' --region <region>
```

**5. Optional — Data access policy:**

Ask: "Would you like to set up a data access policy now? This grants an IAM principal access to the collection. You can also do this later."

If yes, collect the IAM principal ARN (role or user ARN), then run:
```bash
aws opensearchserverless create-access-policy --cli-input-json '{
  "type": "data",
  "name": "<name>-access-policy",
  "policy": "[{\"Rules\":[{\"Resource\":[\"collection/<name>\"],\"Permission\":[\"aoss:*\"],\"ResourceType\":\"collection\"},{\"Resource\":[\"index/<name>/*\"],\"Permission\":[\"aoss:*\"],\"ResourceType\":\"index\"}],\"Principal\":[\"<principal-arn>\"]}]"
}' --region <region>
```

### Success Output

After all commands succeed, report:
- Collection group name and ID
- Collection name, ID, and ARN (from create-collection response)
- Region
- Remind user: "Your collection will be ACTIVE in 1-2 minutes. You can check status with: `aws opensearchserverless batch-get-collection --ids <id> --region <region>`"

---

## Flow 2: Advanced Provisioning

### Step 1: Preset Selection

Ask the user:
```
Choose a preset:

1. Standard — Auto-scaling OCUs, public access, AWS-owned encryption key
2. Prod — Explicit OCU limits, VPC-only access, customer-managed KMS key
```

### Step 2: Preset Values

Display:

| Parameter | Standard | Prod |
|-----------|----------|------|
| Standby replicas | ENABLED | ENABLED |
| Min indexing OCUs | (auto) | 4 |
| Max indexing OCUs | (auto) | 16 |
| Min search OCUs | (auto) | 4 |
| Max search OCUs | (auto) | 16 |
| Network access | Public | VPC |
| Encryption | AWS-owned | Customer CMK |
| Vector acceleration | DISABLED | DISABLED |

Note: Standby replicas is always ENABLED for NextGen and cannot be overridden.
Note: OCU values must be 1, 2, 4, 8, 16, or any multiple of 16.
Note: Vector acceleration requires account-level enablement — if it fails with "not supported for account", proceed without it.

Ask: "Would you like to override any of these values? If so, tell me which ones and the new values."

Overridable parameters:
- Capacity limits (min/max indexing/search OCUs — valid values: 1, 2, 4, 8, 16, 32, 48, 64, 80, 96)
- Network access (Public or VPC)
- Encryption (AWS-owned or Customer CMK ARN)

### Step 3: Collect Required Inputs

Collect:
1. **Collection name** — 3-32 chars, lowercase, alphanumeric + hyphens, starts with letter
2. **Collection type** — SEARCH, TIMESERIES, or VECTORSEARCH
3. **Region** — AWS region
4. **VPC endpoint ID** — only if network access = VPC
5. **KMS key ARN** — only if encryption = Customer CMK

### Step 4: Execution

**1. Create encryption policy:**

If AWS-owned key:
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "encryption",
  "name": "<name>-enc-policy",
  "policy": "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AWSOwnedKey\":true}"
}' --region <region>
```

If Customer CMK:
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "encryption",
  "name": "<name>-enc-policy",
  "policy": "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AWSOwnedKey\":false,\"KmsARN\":\"<kms-key-arn>\"}"
}' --region <region>
```

**2. Create network policy:**

If Public access:
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "network",
  "name": "<name>-net-policy",
  "policy": "[{\"Description\":\"Public access for <name>\",\"Rules\":[{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/<name>\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AllowFromPublic\":true}]"
}' --region <region>
```

If VPC access:
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "network",
  "name": "<name>-net-policy",
  "policy": "[{\"Description\":\"VPC access for <name>\",\"Rules\":[{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/<name>\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AllowFromPublic\":false,\"SourceVPCEs\":[\"<vpc-endpoint-id>\"]}]"
}' --region <region>
```

**3. Create collection group:**

If Standard preset (no capacity limits):
```bash
aws opensearchserverless create-collection-group \
  --name <name>-group \
  --standby-replicas ENABLED \
  --generation NEXTGEN \
  --endpoint-url "https://aoss.<region>.amazonaws.com" \
  --region <region>
```

If Prod preset or with capacity overrides:
```bash
aws opensearchserverless create-collection-group \
  --name <name>-group \
  --standby-replicas ENABLED \
  --generation NEXTGEN \
  --capacity-limits '{"minIndexingCapacityInOCU":<min-idx>,"maxIndexingCapacityInOCU":<max-idx>,"minSearchCapacityInOCU":<min-srch>,"maxSearchCapacityInOCU":<max-srch>}' \
  --endpoint-url "https://aoss.<region>.amazonaws.com" \
  --region <region>
```

**4. Create collection:**
```bash
aws opensearchserverless create-collection --cli-input-json '{
  "name": "<name>",
  "type": "<TYPE>",
  "collectionGroupName": "<name>-group"
}' --region <region>
```

**5. Optional — Data access policy:**

Same as Flow 1 (ask if user wants to set up data access policy, collect principal ARN if yes).

### Success Output

Same as Flow 1 — report group ID, collection ID, ARN, region, and status check command.

---

## Flow 3: Standalone Collection (Classic)

For customers who want a collection without a collection group (v1-style, no NextGen features).

### Inputs

Collect from the user:
1. **Collection name** — 3-32 chars, lowercase, alphanumeric + hyphens, starts with letter
2. **Collection type** — SEARCH, TIMESERIES, or VECTORSEARCH
3. **Region** — AWS region

### Execution

**1. Create encryption policy:**
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "encryption",
  "name": "<name>-enc-policy",
  "policy": "{\"Rules\":[{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AWSOwnedKey\":true}"
}' --region <region>
```

**2. Create network policy (public access):**
```bash
aws opensearchserverless create-security-policy --cli-input-json '{
  "type": "network",
  "name": "<name>-net-policy",
  "policy": "[{\"Description\":\"Public access for <name>\",\"Rules\":[{\"ResourceType\":\"dashboard\",\"Resource\":[\"collection/<name>\"]},{\"ResourceType\":\"collection\",\"Resource\":[\"collection/<name>\"]}],\"AllowFromPublic\":true}]"
}' --region <region>
```

**3. Create collection (no collection group):**
```bash
aws opensearchserverless create-collection --cli-input-json '{
  "name": "<name>",
  "type": "<TYPE>"
}' --region <region>
```

**4. Optional — Data access policy:**

Same as Flow 1.

### Success Output

Report collection name, ID, ARN, region. Remind about status check command.

---

## Flow 4: Add Collection to Existing Group

### Steps

**1. Collect region:**

Ask the user for their AWS region.

**2. List existing collection groups:**
```bash
aws opensearchserverless list-collection-groups --region <region>
```

Display the `collectionGroupSummaries` array as a numbered list showing: group name, ID, numberOfCollections, and capacityLimits. If no groups exist, inform the user and suggest using Flow 1 or Flow 2 instead.

**3. User selects group:**

Ask which collection group they want to add the collection to.

**4. Check policies:**

Before creating the collection, verify that encryption and network policies exist that cover the new collection name.

First list policies:
```bash
aws opensearchserverless list-security-policies --type encryption --region <region>
```

Then for each policy, get its details to check the resource pattern:
```bash
aws opensearchserverless get-security-policy --cli-input-json '{
  "type": "encryption",
  "name": "<policy-name>"
}' --region <region>
```

Check if any policy's `Resource` array includes `collection/<new-collection-name>` or a wildcard pattern like `collection/*` that matches. Repeat for network policies (type `network`).

If no matching policies exist, warn the user and offer to create them (same commands as Flow 1 steps 1-2).

**5. Collect inputs:**

- **Collection name** — 3-32 chars, lowercase, alphanumeric + hyphens, starts with letter
- **Collection type** — SEARCH, TIMESERIES, or VECTORSEARCH

**6. Create collection:**
```bash
aws opensearchserverless create-collection --cli-input-json '{
  "name": "<name>",
  "type": "<TYPE>",
  "collectionGroupName": "<selected-group-name>"
}' --region <region>
```

**7. Optional — Data access policy:**

Same as Flow 1.

### Success Output

Report collection name, ID, ARN, which group it was added to, and status check command.

---

## Flow 5: Deprovision (Teardown)

### Steps

**1. Collect region:**

Ask the user for their AWS region.

**2. List existing resources:**
```bash
aws opensearchserverless list-collection-groups --region <region>
aws opensearchserverless list-collections --region <region>
```

Display all collection groups (with numberOfCollections) and collections as a numbered list.

**3. User selects teardown scope:**

Ask:
```
What would you like to delete?

1. A specific collection only
2. A collection group and all its collections
3. Full teardown (all groups + collections + associated policies)
```

**4. If deleting a specific collection:**

Ask which collection. Then:
```bash
aws opensearchserverless delete-collection --cli-input-json '{
  "id": "<collection-id>"
}' --region <region>
```

**5. If deleting a collection group (and its collections):**

First, identify collections in that group from the `list-collections` output (check `collectionGroupName` field).

Show confirmation:
```
The following resources will be deleted:
  - Collection group: <group-name> (id: <group-id>)
    - Collection: <coll-name> (id: <coll-id>)
    [... for each collection in the group]
  - Encryption policy: <name>-enc-policy (if exists)
  - Network policy: <name>-net-policy (if exists)

Type the collection group name to confirm deletion:
```

Wait for user to type the exact group name. If it doesn't match, abort.

Then execute in order:

a. Delete each collection:
```bash
aws opensearchserverless delete-collection --cli-input-json '{
  "id": "<collection-id>"
}' --region <region>
```

b. Poll until collections are deleted (every 10 seconds, max 5 minutes):
```bash
aws opensearchserverless batch-get-collection --ids <id1> <id2> --region <region>
```

Deletion is complete when EITHER:
- The collection appears in `collectionErrorDetails` with `"errorCode": "NOT_FOUND"`, OR
- The `collectionDetails` array is empty for all requested IDs

Do NOT look for a "DELETED" status — AWS removes the collection entirely and returns NOT_FOUND.

If timeout (5 minutes), inform user and stop.

c. Delete collection group:
```bash
aws opensearchserverless delete-collection-group --cli-input-json '{
  "id": "<group-id>"
}' --region <region>
```

d. Delete associated security policies (if they exist and match the naming pattern):
```bash
aws opensearchserverless delete-security-policy --cli-input-json '{
  "type": "encryption",
  "name": "<name>-enc-policy"
}' --region <region>

aws opensearchserverless delete-security-policy --cli-input-json '{
  "type": "network",
  "name": "<name>-net-policy"
}' --region <region>
```

**6. If full teardown:**

Same as option 5 but for ALL groups. Show full confirmation list and require typed confirmation.

### Success Output

Report what was deleted and confirm cleanup is complete.

---

## Error Handling

### Credential Failure
If `aws sts get-caller-identity` fails, STOP immediately. Tell the user:
"AWS credentials are missing or expired. Please configure credentials and try again."

### Name Collision
If any create command fails with "ConflictException" or "already exists":
- Inform the user which resource name already exists
- Ask if they want to use a different name
- Suggest: `<name>-2` or ask for their preference

### Region Not Supported
If a command fails with "Could not connect to the endpoint URL":
- Inform the user that AOSS may not be available in that region
- Suggest supported regions: us-east-1, us-east-2, us-west-1, us-west-2, eu-west-1, eu-central-1, ap-southeast-1, ap-southeast-2, ap-northeast-1

### Invalid OCU Values
If `create-collection-group` fails with "Invalid value for maxIndexingCapacityInOCU" or similar:
- Inform the user that OCU values must be: 1, 2, 4, 8, 16, or any multiple of 16 (32, 48, 64, 80, 96)
- Ask for corrected values

### Vector Options Not Supported
If `create-collection` fails with "Providing VectorOptions during collection creation is not supported for account":
- Inform the user their account doesn't have vector acceleration enabled
- Retry without the `vectorOptions` field

### Collection Not Deletable (Still Creating)
If `delete-collection` fails with "ConflictException" and message about status not being ACTIVE/FAILED:
- The collection is still being created (NextGen: ~30s, standalone: 3-5 minutes)
- Wait 30 seconds and retry
- After 5 retries, inform user and suggest waiting a few more minutes before trying again

### Partial Failure During Provisioning
If a command fails mid-flow (e.g., collection group created but collection fails):
- Report what was successfully created
- Report what failed and the error message
- Suggest cleanup: "You can re-run with a different name, or use the Deprovision flow to clean up the partial resources."

### API Throttling
If a command fails with "ThrottlingException":
- Wait 5 seconds and retry (max 3 attempts)
- If still failing after retries, inform the user and suggest trying again in a minute

### Collection Group Not Empty on Delete
If `delete-collection-group` fails with "ValidationException" and message "has collections associated":
- The group still has active or deleting collections
- List remaining collections, delete them first, poll until gone, then retry group deletion
