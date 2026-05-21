# Advanced Provisioning & Add to Existing Group

Companion file for the AOSS NextGen provisioning skill. Read this when user selects Flow 2 or Flow 4.

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
2. **Collection type** — SEARCH or VECTORSEARCH
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
  --region <region>
```

If Prod preset or with capacity overrides:
```bash
aws opensearchserverless create-collection-group \
  --name <name>-group \
  --standby-replicas ENABLED \
  --generation NEXTGEN \
  --capacity-limits '{"minIndexingCapacityInOCU":<min-idx>,"maxIndexingCapacityInOCU":<max-idx>,"minSearchCapacityInOCU":<min-srch>,"maxSearchCapacityInOCU":<max-srch>}' \
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

Same as Flow 1 in SKILL.md (ask if user wants to set up data access policy, collect principal ARN if yes).

### Success Output

Same as Flow 1 — report group ID, collection ID, ARN, region, and status check command.

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

If no matching policies exist, warn the user and offer to create them (same commands as Flow 1 steps 1-2 in SKILL.md).

**5. Collect inputs:**

- **Collection name** — 3-32 chars, lowercase, alphanumeric + hyphens, starts with letter
- **Collection type** — SEARCH or VECTORSEARCH

**6. Create collection:**
```bash
aws opensearchserverless create-collection --cli-input-json '{
  "name": "<name>",
  "type": "<TYPE>",
  "collectionGroupName": "<selected-group-name>"
}' --region <region>
```

**7. Optional — Data access policy:**

Same as Flow 1 in SKILL.md.

### Success Output

Report collection name, ID, ARN, which group it was added to, and status check command.
