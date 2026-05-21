# Deprovision (Teardown)

Companion file for the AOSS NextGen provisioning skill. Read this when user selects Flow 5.

---

## Flow 5: Deprovision

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
