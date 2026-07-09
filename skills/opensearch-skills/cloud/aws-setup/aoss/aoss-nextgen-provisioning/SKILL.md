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
- `"generation": "NEXTGEN"` is REQUIRED for NextGen collection groups.
- AWS credentials must be pre-configured; check first and stop if missing
- Execute commands directly — do not generate scripts for the user to run
- **Usage attribution (required):** Prefix every AWS CLI command you run in a shell with `AWS_SDK_UA_APP_ID=opensearch-agent-skills` (e.g. `AWS_SDK_UA_APP_ID=opensearch-agent-skills aws opensearchserverless ...`), regardless of service or subcommand. Scope it per-command — do not `export` it globally. This tags the call's User-Agent header so cloud requests from this skill are attributable.
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

## Companion Files

This skill is split across multiple files to stay under 500 lines. Read companion files on demand:
- **If user selects Flow 2 (Advanced) or Flow 4 (Add to Existing Group):** Read `ADVANCED.md` in this directory.
- **If user selects Flow 5 (Deprovision):** Read `DEPROVISION.md` in this directory.
- **On any command failure:** Read `ERRORS.md` in this directory for error handling guidance.

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

Proceed to the corresponding flow section below (or read companion file as noted above).

---

## Flow 1: Simple Provisioning

### Inputs

Collect from the user (one at a time):
1. **Collection name** — 3-32 chars, lowercase letters, numbers, hyphens. Must start with a letter. Pattern: `[a-z][a-z0-9-]+`
2. **Collection type** — SEARCH or VECTORSEARCH
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
  "policy": "[{\"Rules\":[{\"Resource\":[\"collection/<name>\"],\"Permission\":[\"aoss:*\"],\"ResourceType\":\"collection\"},{\"Resource\":[\"index/<name>/*\"],\"Permission\":[\"aoss:*\"],\"ResourceType\":\"index\"},{\"Resource\":[\"model/*/*\"],\"Permission\":[\"aoss:*\"],\"ResourceType\":\"model\"},{\"Resource\":[\"agent/*/*\"],\"Permission\":[\"aoss:*\"],\"ResourceType\":\"agent\"}],\"Principal\":[\"<principal-arn>\"]}]"
}' --region <region>
```

**Important:** The `model` and `agent` resource types are required for semantic enrichment (CreateIndex with `semantic_enrichment`) and for deploying ML models or agents on the collection. The `model/*/*` wildcard pattern is needed because semantic enrichment creates ML connectors at the account level, not scoped to a single collection name. Always include both `model` and `agent` rules.

### Success Output

After all commands succeed, report:
- Collection group name and ID
- Collection name, ID, and ARN (from create-collection response)
- Region
- Remind user: "Your collection will be ACTIVE in 1-2 minutes. You can check status with: `aws opensearchserverless batch-get-collection --ids <id> --region <region>`"

---

## Flow 3: Standalone Collection (Classic)

For customers who want a collection without a collection group (v1-style, no NextGen features).

### Inputs

Collect from the user:
1. **Collection name** — 3-32 chars, lowercase, alphanumeric + hyphens, starts with letter
2. **Collection type** — SEARCH or VECTORSEARCH
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
