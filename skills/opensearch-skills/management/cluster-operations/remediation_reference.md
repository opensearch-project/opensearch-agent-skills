# Remediation Reference

Catalogue of remediation commands for OpenSearch cluster operations, organized by severity and topic. Each entry includes the risk level, prerequisites, and the exact API call.

Risk levels:
- 🟢 **Safe** — no data loss possible; reversible
- 🟡 **Caution** — no data loss, but may cause brief performance impact or yellow status
- 🔴 **Destructive** — potential data loss or irreversible; MUST confirm with user first

---

## 1. Shard Allocation

### Retry failed shard allocations
🟢 Safe — retries all previously failed shard assignments

```
POST _cluster/reroute?retry_failed=true
```

### Manually assign a replica shard to a specific node
🟢 Safe — OpenSearch copies data from an existing shard

```json
POST _cluster/reroute
{
  "commands": [{
    "allocate_replica": {
      "index": "<index-name>",
      "shard": 0,
      "node": "<node-name>"
    }
  }]
}
```

### Force-allocate a primary shard (stale copy, no data loss)
🟡 Caution — use only when the primary's original node is coming back and has the latest data

```json
POST _cluster/reroute
{
  "commands": [{
    "allocate_stale_primary": {
      "index": "<index-name>",
      "shard": 0,
      "node": "<node-name>",
      "accept_data_loss": false
    }
  }]
}
```

### Force-allocate a primary shard (empty — all data in this shard lost)
🔴 Destructive — creates an empty primary; all documents in this shard are permanently lost

```json
POST _cluster/reroute
{
  "commands": [{
    "allocate_empty_primary": {
      "index": "<index-name>",
      "shard": 0,
      "node": "<node-name>",
      "accept_data_loss": true
    }
  }]
}
```

### Move a shard from one node to another
🟢 Safe — live migration, no downtime

```json
POST _cluster/reroute
{
  "commands": [{
    "move": {
      "index": "<index-name>",
      "shard": 0,
      "from_node": "<source-node>",
      "to_node": "<target-node>"
    }
  }]
}
```

### Cancel a shard relocation in progress
🟢 Safe — stops in-progress recovery; the shard stays on the source node

```json
POST _cluster/reroute
{
  "commands": [{
    "cancel": {
      "index": "<index-name>",
      "shard": 0,
      "node": "<node-name>"
    }
  }]
}
```

---

## 2. Cluster Settings

### Disable shard allocation (for maintenance)
🟡 Caution — no new shard assignments while disabled; always re-enable after maintenance

```json
PUT _cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.enable": "primaries"
  }
}
```

### Re-enable shard allocation (after maintenance)
🟢 Safe — restores normal assignment behavior

```json
PUT _cluster/settings
{
  "persistent": {
    "cluster.routing.allocation.enable": "all"
  }
}
```

### Exclude a specific node from receiving new shards (graceful drain)
🟢 Safe — existing shards migrate away; no new ones assigned

```json
PUT _cluster/settings
{
  "transient": {
    "cluster.routing.allocation.exclude._name": "<node-name>"
  }
}
```

Clear the exclusion after the node is back:
```json
PUT _cluster/settings
{
  "transient": {
    "cluster.routing.allocation.exclude._name": null
  }
}
```

### Adjust disk watermarks temporarily
🟢 Safe — higher thresholds allow more shard assignment on full disks (set back after freeing space)

```json
PUT _cluster/settings
{
  "transient": {
    "cluster.routing.allocation.disk.watermark.low": "88%",
    "cluster.routing.allocation.disk.watermark.high": "93%",
    "cluster.routing.allocation.disk.watermark.flood_stage": "97%"
  }
}
```

### Max shards per node
🟢 Safe — prevents over-sharding

```json
PUT _cluster/settings
{
  "persistent": {
    "cluster.max_shards_per_node": 1000
  }
}
```

---

## 3. Index Settings

### Reduce replica count for a single-node cluster
🟢 Safe — data is still on the primary shard

```json
PUT <index-name>/_settings
{
  "number_of_replicas": 0
}
```

### Remove read-only block (set by flood-stage watermark)
🟢 Safe — must free disk space first or the block will re-apply

```json
PUT <index-name>/_settings
{
  "index.blocks.read_only_allow_delete": null
}
```

Remove from all indices at once:
```json
PUT _all/_settings
{
  "index.blocks.read_only_allow_delete": null
}
```

### Close an index (frees heap memory from field data / segments)
🟡 Caution — index becomes unavailable for reads/writes while closed

```
POST <index-name>/_close
```

Re-open:
```
POST <index-name>/_open
```

### Delete an index
🔴 Destructive — all data in the index is permanently deleted

```
DELETE <index-name>
```

---

## 4. Cache and Memory

### Clear all caches (field data, request, query)
🟢 Safe — caches rebuild on demand; brief performance dip

```
POST _cache/clear
```

### Clear field data cache only
🟢 Safe — targeted at field data heap pressure

```
POST _cache/clear?fielddata=true
```

### Clear request cache only
🟢 Safe — clears aggregation result cache

```
POST _cache/clear?request=true
```

### Force merge an index (reduce segment count and memory)
🟡 Caution — CPU/IO intensive; only run on read-only or low-traffic indices

```
POST <index-name>/_forcemerge?max_num_segments=1
```

### Adjust field data circuit breaker
🟡 Caution — raising the limit prevents `Data too large` errors but increases OOM risk

```json
PUT _cluster/settings
{
  "persistent": {
    "indices.breaker.fielddata.limit": "40%"
  }
}
```

### Adjust request circuit breaker
🟡 Caution — controls max memory for a single search request

```json
PUT _cluster/settings
{
  "persistent": {
    "indices.breaker.request.limit": "50%"
  }
}
```

---

## 5. Snapshot and Restore

### List all snapshot repositories
```
GET _snapshot/_all
```

### List all snapshots in a repository
```
GET _snapshot/<repository-name>/_all
```

### Create a manual snapshot
🟢 Safe — read-only operation on cluster data

```
PUT _snapshot/<repository-name>/<snapshot-name>?wait_for_completion=false
```

### Restore an index from a snapshot
🟡 Caution — if the index already exists, the restore fails unless the index is deleted first

```json
POST _snapshot/<repository-name>/<snapshot-name>/_restore
{
  "indices": "<index-name>",
  "rename_pattern": "^(.+)$",
  "rename_replacement": "restored_$1"
}
```

---

## 6. ISM Policy Templates

### Log retention — rollover + delete
Rolls over when index reaches 50 GB or 7 days old; deletes after 30 days.

```json
PUT _plugins/_ism/policies/log-retention-30d
{
  "policy": {
    "description": "Rollover at 50GB/7d; delete after 30d",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [],
        "transitions": [{
          "state_name": "warm",
          "conditions": {
            "min_index_age": "7d",
            "min_primary_shard_size": "50gb"
          }
        }]
      },
      {
        "name": "warm",
        "actions": [
          { "force_merge": { "max_num_segments": 1 } },
          { "read_only": {} }
        ],
        "transitions": [{
          "state_name": "delete",
          "conditions": { "min_index_age": "30d" }
        }]
      },
      {
        "name": "delete",
        "actions": [{ "delete": {} }],
        "transitions": []
      }
    ],
    "ism_template": [{
      "index_patterns": ["logs-*"],
      "priority": 100
    }]
  }
}
```

### Attach ISM policy to an existing index
```json
POST _plugins/_ism/add/<index-name>
{
  "policy_id": "log-retention-30d"
}
```

### Check ISM policy execution status
```
GET _plugins/_ism/explain/<index-name>
```

---

## 7. Alerting — Notification Destinations

### Create a Slack destination
```json
POST _plugins/alerting/destinations
{
  "name": "slack-ops-channel",
  "type": "slack",
  "slack": {
    "url": "<slack-webhook-url>"
  }
}
```

### Create a webhook destination
```json
POST _plugins/alerting/destinations
{
  "name": "pagerduty-webhook",
  "type": "custom_webhook",
  "custom_webhook": {
    "url": "<webhook-url>",
    "method": "POST",
    "header_params": {
      "Content-Type": "application/json"
    }
  }
}
```

### Create a cluster health alert (query monitor)
Fires when any index is RED for more than 5 minutes.

```json
POST _plugins/alerting/monitors
{
  "type": "monitor",
  "name": "Cluster Red Status Alert",
  "monitor_type": "query_level_monitor",
  "enabled": true,
  "schedule": {
    "period": { "interval": 5, "unit": "MINUTES" }
  },
  "inputs": [{
    "search": {
      "indices": ["*"],
      "query": {
        "size": 0,
        "query": { "match_all": {} }
      }
    }
  }],
  "triggers": [{
    "query_level_trigger": {
      "id": "red-cluster-trigger",
      "name": "Cluster status RED",
      "severity": "1",
      "condition": {
        "script": {
          "source": "ctx.results[0]._shards.failed > 0",
          "lang": "painless"
        }
      },
      "actions": [{
        "name": "Notify Slack",
        "destination_id": "<destination-id>",
        "message_template": {
          "source": "Cluster is RED. Failed shards: {{ctx.results.0._shards.failed}}. Time: {{ctx.periodEnd}}"
        }
      }]
    }
  }]
}
```

---

## 8. Slow Log Configuration

### Enable slow query logging on an index
🟢 Safe — adds log output only

```json
PUT <index-name>/_settings
{
  "index.search.slowlog.threshold.query.warn": "10s",
  "index.search.slowlog.threshold.query.info": "5s",
  "index.search.slowlog.threshold.query.debug": "2s",
  "index.search.slowlog.threshold.fetch.warn": "1s",
  "index.search.slowlog.threshold.fetch.info": "800ms",
  "index.search.slowlog.level": "info"
}
```

### Disable slow query logging
```json
PUT <index-name>/_settings
{
  "index.search.slowlog.threshold.query.warn": "-1",
  "index.search.slowlog.threshold.query.info": "-1",
  "index.search.slowlog.threshold.fetch.warn": "-1"
}
```
