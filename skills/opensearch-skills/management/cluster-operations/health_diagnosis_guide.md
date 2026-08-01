# Cluster Health Diagnosis Guide

Detailed decision trees and query patterns for diagnosing OpenSearch cluster issues.

---

## 1. Reading Cluster Health at a Glance

```
GET _cluster/health
```

Response fields to check first:

| Field | What it means |
|---|---|
| `status` | `green` = all shards assigned; `yellow` = replicas unassigned; `red` = primaries unassigned |
| `unassigned_shards` | Any value > 0 requires investigation |
| `relocating_shards` | > 0 means shards are moving — usually fine post-restart |
| `initializing_shards` | > 0 means shards are being recovered — usually fine post-restart |
| `active_primary_shards` | Should equal the expected total primaries |
| `number_of_pending_tasks` | > 10 may indicate cluster master is overloaded |

```
GET _cluster/health?level=indices
```

Use `level=indices` to see per-index status — immediately identifies which indices are causing yellow/red.

---

## 2. Decision Tree — Red Cluster

```
Cluster RED
  │
  ├─ GET _cluster/allocation/explain
  │     │
  │     ├─ reason: NODE_LEFT
  │     │     └─ Did the node come back?
  │     │             ├─ YES → wait for recovery; watch GET _cat/recovery?active_only=true
  │     │             └─ NO  → does a replica exist on another node?
  │     │                       ├─ YES → promote replica:
  │     │                       │        POST _cluster/reroute (allocate_stale_primary w/ accept_data_loss: false first)
  │     │                       └─ NO  → restore from snapshot (DATA LOSS — confirm with user)
  │     │
  │     ├─ reason: ALLOCATION_FAILED
  │     │     └─ check: GET _cat/allocation?v  (is any node at disk watermark?)
  │     │             ├─ disk full → free disk, then POST _cluster/reroute?retry_failed=true
  │     │             └─ other failure → check _cluster/explain for detail; retry allocation
  │     │
  │     ├─ reason: NO_VALID_SHARD_COPY
  │     │     └─ All copies lost. Only option: restore from snapshot.
  │     │        Show user: GET _snapshot/_all and GET _snapshot/<repo>/_all
  │     │
  │     └─ reason: INDEX_CREATED (new index)
  │           └─ replicas cannot be placed (not enough nodes for replica count)
  │              Fix: reduce replica count: PUT <index>/_settings {"number_of_replicas": 0}
  │
  └─ No result from allocation/explain → check master logs or run:
       GET _cluster/pending_tasks
       GET _nodes/_master
```

---

## 3. Decision Tree — Yellow Cluster

Yellow = primary shards OK, but ≥1 replica is unassigned. Data is safe but no redundancy.

```
Cluster YELLOW
  │
  ├─ Single-node cluster?
  │     └─ Expected — set replicas to 0: PUT <index>/_settings {"number_of_replicas": 0}
  │
  ├─ Not enough data nodes for replica count?
  │     └─ Add a node, OR reduce replica count for affected indices
  │
  ├─ Node recently left or joined?
  │     └─ Wait up to 1 minute; OpenSearch auto-assigns replicas
  │
  └─ Disk watermark reached on target nodes?
        GET _cat/allocation?v&h=node,disk.percent,shards
        └─ disk.percent > 85% → free disk; adjust watermarks if needed:
           PUT _cluster/settings {"transient":{"cluster.routing.allocation.disk.watermark.high":"90%"}}
```

---

## 4. JVM / Memory Pressure Triage

### Step 1 — Check heap usage per node

```
GET _cat/nodes?v&h=name,heap.percent,heap.current,heap.max,ram.percent,gc.young.time,gc.young.count
```

| heap.percent | Action |
|---|---|
| < 75% | Normal |
| 75–85% | Monitor; check field data cache |
| 85–95% | **Act now** — clear caches, reduce pressure |
| > 95% | Critical — force GC, reduce load, consider rolling restart |

### Step 2 — Identify memory consumers

```
GET _nodes/stats/indices/fielddata?fields=*&pretty
GET _nodes/stats/breaker
```

**Field data cache too large** — cause: `terms` aggregations on `text` fields or large `keyword` fields:
```
POST _cache/clear?fielddata=true
```
Then prevent recurrence:
```json
PUT _cluster/settings
{
  "persistent": {
    "indices.breaker.fielddata.limit": "30%"
  }
}
```

**Request circuit breaker tripping** — cause: very large aggregations or single query loading too much data:
```
GET _nodes/stats/breaker
```
Look for `tripped > 0` on `request` or `in_flight_requests`.

### Step 3 — Check for GC pressure

```
GET _nodes/hot_threads?threads=5&type=cpu
GET _nodes/stats/jvm
```

In `_nodes/stats/jvm`, check `jvm.mem.heap_used_percent` per node, and `jvm.gc.collectors.young.collection_time_in_millis` — if GC time is > 10% of wall clock time, the JVM is under severe pressure.

### Step 4 — Emergency memory relief

In order of increasing aggressiveness (always prefer non-destructive first):

1. **Clear all caches** (safe):
   ```
   POST _cache/clear
   ```

2. **Force merge read-only indices** (reduces segment memory):
   ```
   POST <read-only-index>/_forcemerge?max_num_segments=1
   ```

3. **Disable fielddata on problematic fields** (prevents future cache growth):
   ```json
   PUT <index>/_mapping
   {
     "properties": {
       "<field>": { "type": "keyword", "doc_values": true, "fielddata": false }
     }
   }
   ```

4. **Rolling restart** (last resort — causes brief yellow status):
   - Disable shard allocation before restarting each node:
   ```json
   PUT _cluster/settings
   { "persistent": { "cluster.routing.allocation.enable": "primaries" } }
   ```
   - Restart the node.
   - Re-enable:
   ```json
   PUT _cluster/settings
   { "persistent": { "cluster.routing.allocation.enable": "all" } }
   ```
   - Wait for green before moving to the next node.

---

## 5. Slow Query Triage

### Step 1 — Identify slow queries from slow logs

```
GET <index>/_settings?filter_path=**.slowlog
```

Enable slow logging if not already set:
```json
PUT <index>/_settings
{
  "index.search.slowlog.threshold.query.warn": "5s",
  "index.search.slowlog.threshold.query.info": "1s",
  "index.search.slowlog.threshold.fetch.warn": "1s"
}
```

### Step 2 — Use the Profile API on a representative query

```json
POST <index>/_search
{
  "profile": true,
  "query": {
    "match": { "message": "error" }
  }
}
```

In the response, check `profile.shards[*].searches[*].query[*].time_in_nanos`. The highest values indicate the most expensive query clauses.

### Step 3 — Common slow query root causes

| Symptom | Root Cause | Fix |
|---|---|---|
| High `BooleanQuery` time | Many `should` clauses or wildcard queries | Rewrite with `filter` context; avoid leading wildcards |
| High `TermsQuery` time on `text` field | No `keyword` mapping | Add `.keyword` sub-field or use `keyword` type |
| Long fetch time | Large `_source` returned | Use `_source_includes` to limit returned fields |
| Slow aggregations | `terms` agg on `text` field | Map field as `keyword` instead |
| High shard count per query | Too many indices in wildcard pattern | Use index aliases with date filters |

### Step 4 — Check node-level search stats

```
GET _nodes/stats/indices/search
```

Look for `query_total`, `query_time_in_millis`, `query_current` per node — imbalanced values suggest shard distribution problems.

---

## 6. Disk Watermark Issues

OpenSearch has three watermark levels:

| Watermark | Default | Effect |
|---|---|---|
| `low` | 85% | No new shards allocated to this node |
| `high` | 90% | OpenSearch tries to relocate shards away |
| `flood_stage` | 95% | **Indices become read-only** — writes fail |

Check current disk usage:
```
GET _cat/allocation?v&h=node,shards,disk.used,disk.avail,disk.total,disk.percent
```

If an index is read-only due to flood stage:
1. Free disk space.
2. Reset the read-only flag:
   ```json
   PUT <index>/_settings
   { "index.blocks.read_only_allow_delete": null }
   ```
3. Optionally, temporarily raise the flood-stage watermark (set it back after freeing space):
   ```json
   PUT _cluster/settings
   {
     "transient": {
       "cluster.routing.allocation.disk.watermark.flood_stage": "97%"
     }
   }
   ```

---

## 7. Master Node Overload

Signs: `_cluster/health` shows many `pending_tasks`; `_cluster/stats` is slow; node joins/leaves are delayed.

```
GET _cluster/pending_tasks
GET _nodes/_master
GET _nodes/<master-node-id>/stats/thread_pool/management
```

Common causes:
- Too many indices (thousands) — reduce index count or use data streams with rollover
- Frequent mapping updates — set `dynamic: strict` on indices to prevent auto-mapping
- Frequent cluster settings changes from an external tool — audit and reduce frequency

---

## 8. Useful Diagnostic Commands Reference

```bash
# Overall health
GET _cluster/health?level=shards

# Node overview
GET _cat/nodes?v&h=name,ip,heap.percent,cpu,load_1m,node.role,master

# Shard state summary
GET _cat/shards?v&s=state&h=index,shard,prirep,state,unassigned.reason,node

# Recovery progress
GET _cat/recovery?v&active_only=true

# Index sizes and doc counts
GET _cat/indices?v&s=store.size:desc&h=health,status,index,pri,rep,docs.count,store.size

# Segment info (memory usage)
GET _cat/segments?v&h=index,shard,segment,size.memory,committed

# Thread pool queues (detect backlog)
GET _cat/thread_pool?v&h=name,active,queue,rejected

# Pending cluster tasks
GET _cluster/pending_tasks

# Node JVM stats
GET _nodes/stats/jvm,indices,breaker

# Hot threads (live)
GET _nodes/hot_threads?threads=5&type=cpu&interval=500ms
```
