# Cluster Configuration and Tuning

## Core Concepts

OpenSearch cluster performance depends on hardware resource configuration, JVM settings, node role assignment, and operating system optimization. Proper cluster architecture and resource allocation are the foundation for ensuring high availability and high performance.

## Common Issues

### Issue 1: JVM Heap Memory Configuration

**Symptoms**:
- Frequent GC (garbage collection)
- OutOfMemoryError
- Degraded query and indexing performance
- Node instability

**Cause**:
Improper JVM heap memory configuration leads to frequent GC or out-of-memory conditions.

**Solution**:

1. Set heap memory size (jvm.options):
```bash
# Set to 50% of physical memory, but no more than 32GB
-Xms16g
-Xmx16g
```

2. Configure GC parameters:
```bash
# Use G1GC (recommended)
-XX:+UseG1GC
-XX:G1ReservePercent=25
-XX:InitiatingHeapOccupancyPercent=30
```

3. Monitor GC logs:
```bash
-Xlog:gc*,gc+age=trace,safepoint:file=/var/log/opensearch/gc.log:utctime,pid,tags:filecount=32,filesize=64m
```

**Best Practices**:
- Set heap memory to 50% of physical memory
- Do not exceed 32GB (compressed oops limit)
- Set Xms and Xmx to the same value (avoid dynamic resizing)
- Reserve 50% of memory for the OS page cache
- Use the G1GC garbage collector
- Monitor GC frequency and pause times

### Issue 2: Node Role Assignment

**Symptoms**:
- Unbalanced cluster load
- Some nodes overloaded
- Queries and indexing interfering with each other

**Cause**:
Having all nodes serve all roles leads to resource contention.

**Solution**:

1. Dedicated master node:
```yaml
# opensearch.yml
node.roles: [cluster_manager]
node.name: master-node-1
```

2. Dedicated data node:
```yaml
# opensearch.yml
node.roles: [data, ingest]
node.name: data-node-1
```

3. Dedicated coordinating node:
```yaml
# opensearch.yml
node.roles: []
node.name: coordinating-node-1
```

4. Recommended cluster architectures:
```
Small cluster (< 10 nodes):
- 3 master nodes
- N data nodes (data + ingest)

Medium cluster (10-50 nodes):
- 3 dedicated master nodes
- N data nodes
- 2-3 coordinating nodes

Large cluster (> 50 nodes):
- 3 dedicated master nodes
- N hot data nodes
- M warm data nodes
- 3-5 coordinating nodes
```

**Best Practices**:
- Use an odd number of master nodes (3, 5, 7)
- Master nodes should not handle data or query tasks
- Data nodes should focus on storage and queries
- Coordinating nodes handle client requests and aggregations
- Use node labels to implement data tiering (hot/warm/cold)

### Issue 3: Shard Allocation and Balancing

**Symptoms**:
- Uneven disk usage across nodes
- Some nodes under excessive load
- Shard allocation failures

**Cause**:
Improper shard allocation strategies or disk watermark thresholds being triggered.

**Solution**:

1. Configure disk watermarks:
```yaml
# opensearch.yml
cluster.routing.allocation.disk.threshold_enabled: true
cluster.routing.allocation.disk.watermark.low: 85%
cluster.routing.allocation.disk.watermark.high: 90%
cluster.routing.allocation.disk.watermark.flood_stage: 95%
```

2. Manually allocate shards:
```bash
POST /_cluster/reroute
{
  "commands": [
    {
      "move": {
        "index": "my_index",
        "shard": 0,
        "from_node": "node1",
        "to_node": "node2"
      }
    }
  ]
}
```

3. Configure shard allocation strategy:
```yaml
# opensearch.yml
cluster.routing.allocation.awareness.attributes: zone
cluster.routing.allocation.awareness.force.zone.values: zone1,zone2
```

4. Rebalance shards:
```bash
PUT /_cluster/settings
{
  "transient": {
    "cluster.routing.rebalance.enable": "all"
  }
}
```

**Best Practices**:
- Set reasonable disk watermarks (85%/90%/95%)
- Use shard allocation awareness (zone awareness)
- Avoid too many shards on a single node (< 1000)
- Regularly monitor shard distribution
- Use allocation filtering to control shard placement

### Issue 4: Thread Pool Configuration

**Symptoms**:
- Requests being rejected
- Thread pool queues full
- High query or indexing latency

**Cause**:
Thread pool sizes insufficient to handle concurrent requests.

**Solution**:

1. Check thread pool status:
```bash
GET /_cat/thread_pool?v&h=node_name,name,active,queue,rejected
```

2. Adjust thread pool sizes:
```yaml
# opensearch.yml
thread_pool:
  search:
    size: 30
    queue_size: 1000
  write:
    size: 30
    queue_size: 1000
```

3. Dynamic adjustment (temporary):
```bash
PUT /_cluster/settings
{
  "transient": {
    "thread_pool.search.queue_size": 2000
  }
}
```

**Thread Pool Types**:
- `search`: Search requests
- `write`: Index, update, and delete requests
- `get`: Get requests
- `analyze`: Analyze requests
- `snapshot`: Snapshot operations

**Best Practices**:
- search thread pool: CPU cores × 1.5
- write thread pool: CPU cores
- Queue size: 1000-2000
- Monitor the rejected metric
- Avoid unlimited queues (may cause OOM)

### Issue 5: Network and Transport Configuration

**Symptoms**:
- Slow inter-node communication
- Delayed cluster state updates
- Network timeouts

**Cause**:
Improper network configuration or insufficient bandwidth.

**Solution**:

1. Configure network settings:
```yaml
# opensearch.yml
network.host: 0.0.0.0
http.port: 9200
transport.port: 9300

# Compress transport data
transport.compress: true

# Timeout settings
cluster.publish.timeout: 30s
discovery.request_peers_timeout: 10s
```

2. Configure TCP parameters:
```yaml
# opensearch.yml
transport.tcp.keep_alive: true
transport.tcp.reuse_address: true
```

3. Operating system optimization:
```bash
# /etc/sysctl.conf
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.tcp_tw_reuse = 1
```

**Best Practices**:
- Use a dedicated network for inter-node communication
- Enable transport compression (transport.compress)
- Configure reasonable timeout values
- Monitor network latency and bandwidth usage
- Use high-speed networking (10Gbps+)

## Configuration Examples

### Production Environment Configuration (opensearch.yml)

```yaml
# Cluster configuration
cluster.name: production-cluster
node.name: data-node-1
node.roles: [data, ingest]

# Network configuration
network.host: 0.0.0.0
http.port: 9200
transport.port: 9300
transport.compress: true

# Discovery configuration
discovery.seed_hosts: ["master-1:9300", "master-2:9300", "master-3:9300"]
cluster.initial_cluster_manager_nodes: ["master-1", "master-2", "master-3"]

# Path configuration
path.data: /var/lib/opensearch
path.logs: /var/log/opensearch

# Memory configuration
bootstrap.memory_lock: true

# Shard allocation
cluster.routing.allocation.disk.threshold_enabled: true
cluster.routing.allocation.disk.watermark.low: 85%
cluster.routing.allocation.disk.watermark.high: 90%
cluster.routing.allocation.disk.watermark.flood_stage: 95%

# Thread pools
thread_pool:
  search:
    size: 30
    queue_size: 1000
  write:
    size: 30
    queue_size: 1000

# Security configuration
plugins.security.ssl.http.enabled: true
plugins.security.ssl.transport.enabled: true
```

### JVM Configuration (jvm.options)

```bash
# Heap memory (set to 50% of physical memory, no more than 32GB)
-Xms16g
-Xmx16g

# GC configuration
-XX:+UseG1GC
-XX:G1ReservePercent=25
-XX:InitiatingHeapOccupancyPercent=30

# GC logging
-Xlog:gc*,gc+age=trace,safepoint:file=/var/log/opensearch/gc.log:utctime,pid,tags:filecount=32,filesize=64m

# Heap dump (on OOM)
-XX:+HeapDumpOnOutOfMemoryError
-XX:HeapDumpPath=/var/log/opensearch/heapdump.hprof

# Performance optimization
-XX:+AlwaysPreTouch
-Djava.io.tmpdir=/tmp
```

### Operating System Configuration

```bash
# /etc/security/limits.conf
opensearch soft nofile 65535
opensearch hard nofile 65535
opensearch soft memlock unlimited
opensearch hard memlock unlimited

# /etc/sysctl.conf
vm.max_map_count=262144
vm.swappiness=1
net.core.somaxconn=65535
net.ipv4.tcp_max_syn_backlog=8192
```

## Performance Monitoring

### Key Metrics

1. **Cluster Health**:
```bash
GET /_cluster/health
```

2. **Node Statistics**:
```bash
GET /_nodes/stats
```

3. **Thread Pool Status**:
```bash
GET /_cat/thread_pool?v
```

4. **Shard Allocation**:
```bash
GET /_cat/shards?v
```

5. **JVM Memory**:
```bash
GET /_nodes/stats/jvm
```

### Alert Thresholds

- Cluster status: not green
- JVM heap usage: > 85%
- GC time ratio: > 10%
- Disk usage: > 85%
- Thread pool rejection rate: > 1%
- Query latency: > 500ms
- Indexing latency: > 1s

## Capacity Planning

### Hardware Recommendations

**Data Nodes**:
- CPU: 16-32 cores
- Memory: 64-128 GB
- Disk: SSD, 1-4 TB
- Network: 10 Gbps

**Master Nodes**:
- CPU: 4-8 cores
- Memory: 8-16 GB
- Disk: SSD, 100-200 GB
- Network: 1-10 Gbps

**Coordinating Nodes**:
- CPU: 8-16 cores
- Memory: 32-64 GB
- Disk: SSD, 100-200 GB
- Network: 10 Gbps

### Capacity Calculation

```
Number of data nodes = (total data size × (1 + replica count)) / (per-node disk capacity × 0.7)
Number of master nodes = 3 (fixed)
Number of coordinating nodes = max(2, number of data nodes / 10)
```

## Troubleshooting

### Common Issues

1. **Cluster status yellow**:
   - Check if replica shards are unassigned
   - Check if there are enough nodes

2. **Cluster status red**:
   - Check if primary shards are missing
   - Check if nodes are offline
   - Review shard allocation failure reasons

3. **Nodes frequently restarting**:
   - Check for JVM OOM
   - Check disk space
   - Review system logs

4. **Slow queries**:
   - Check slow query logs
   - Analyze query structure
   - Check cache hit rates

## Reference Resources

- [OpenSearch Cluster Configuration](https://opensearch.org/docs/latest/install-and-configure/configuring-opensearch/)
- [Performance Tuning Guide](https://opensearch.org/docs/latest/tuning-your-cluster/)
- [Capacity Planning](https://opensearch.org/docs/latest/tuning-your-cluster/availability-and-recovery/cluster-manager/)
