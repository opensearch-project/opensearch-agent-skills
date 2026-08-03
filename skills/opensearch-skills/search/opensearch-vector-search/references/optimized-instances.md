# OpenSearch Optimized Instances Guide

## Overview

OpenSearch Optimized instances are Amazon OpenSearch Service-specific instance families that provide improved price-performance for selected managed-service workloads. They use a storage architecture where local EBS/NVMe storage is used for caching and data is synchronously copied to Amazon S3 for durability. Treat this file as an AWS-specific reference; for self-managed OpenSearch or Kubernetes, translate the guidance into CPU, memory, storage, and refresh-latency requirements.

**Instance Families:**

| Family | Focus | Storage | Best For |
|--------|-------|---------|----------|
| **OR1** | Memory-optimized | EBS (gp3/io1) + S3 | Indexing-heavy workloads, log analytics |
| **OR2** | Memory-optimized (next-gen) | EBS (gp3/io1) + S3 | Same as OR1 with better price-performance |
| **OM2** | Compute-optimized | EBS (gp3/io1) + S3 | Higher indexing throughput, 15% faster than OR1 |
| **OI2** | Storage-optimized | Local NVMe + S3 | Large datasets, no EBS needed |

## Instance Specifications

### OR1 (Memory-Optimized, 1st Gen)

| Instance | vCPU | Memory (GiB) | $/month (us-east-1) |
|----------|------|-------------|---------------------|
| or1.medium.search | 1 | 8 | $76.65 |
| or1.large.search | 2 | 16 | $152.57 |
| or1.xlarge.search | 4 | 32 | $305.87 |
| or1.2xlarge.search | 8 | 64 | $610.28 |
| or1.4xlarge.search | 16 | 128 | $1,222.02 |
| or1.8xlarge.search | 32 | 256 | $2,442.58 |
| or1.12xlarge.search | 48 | 384 | $3,664.60 |
| or1.16xlarge.search | 64 | 512 | $4,878.59 |

### OR2 (Memory-Optimized, 2nd Gen)

| Instance | vCPU | Memory (GiB) | $/month (us-east-1) |
|----------|------|-------------|---------------------|
| or2.medium.search | 1 | 8 | $73.00 |
| or2.large.search | 2 | 16 | $146.00 |
| or2.xlarge.search | 4 | 32 | $292.73 |
| or2.2xlarge.search | 8 | 64 | $584.00 |
| or2.4xlarge.search | 16 | 128 | $1,168.00 |
| or2.8xlarge.search | 32 | 256 | $2,336.00 |
| or2.12xlarge.search | 48 | 384 | $3,504.00 |
| or2.16xlarge.search | 64 | 512 | $4,672.00 |

### OM2 (Compute-Optimized)

| Instance | vCPU | Memory (GiB) | $/month (us-east-1) |
|----------|------|-------------|---------------------|
| om2.large.search | 2 | 8 | $111.69 |
| om2.xlarge.search | 4 | 16 | $222.65 |
| om2.2xlarge.search | 8 | 32 | $445.30 |
| om2.4xlarge.search | 16 | 64 | $891.33 |
| om2.8xlarge.search | 32 | 128 | $1,781.93 |
| om2.12xlarge.search | 48 | 192 | $2,673.26 |
| om2.16xlarge.search | 64 | 256 | $3,564.59 |

### OI2 (Storage-Optimized, NVMe)

| Instance | vCPU | Memory (GiB) | $/month (us-east-1) |
|----------|------|-------------|---------------------|
| oi2.large.search | 2 | 16 | $212.96 |
| oi2.xlarge.search | 4 | 32 | $425.91 |
| oi2.2xlarge.search | 8 | 64 | $851.82 |
| oi2.4xlarge.search | 16 | 128 | $1,703.64 |
| oi2.8xlarge.search | 32 | 256 | $3,407.29 |
| oi2.12xlarge.search | 48 | 384 | $5,110.93 |
| oi2.16xlarge.search | 64 | 512 | $6,814.58 |
| oi2.24xlarge.search | 96 | 768 | $10,221.87 |

## Key Characteristics

### Architecture
- **Dual storage**: Data is written locally (EBS for OR1/OR2/OM2, NVMe for OI2) and synchronously replicated to S3
- **Automatic recovery**: In case of node failure, missing shards are automatically restored from S3
- **Indexing on primary only**: Indexing is only performed on primary shards, replicas are synced from S3

### Performance Characteristics
- **OM2**: Up to 15% higher indexing throughput compared to OR1, 66% higher than M7g
- **OR2**: Better price-performance than OR1 (3-5% cheaper at same specs)
- **Refresh interval**: Minimum 10 seconds (default 10s, vs 1s for standard instances)
- **Higher ingestion latency**: Buffer operations before S3 sync add latency

### When to Use Optimized Instances

**Good fit:**
- Indexing-heavy operational analytics (log analytics, observability, security analytics)
- Workloads that prioritize indexing throughput over search latency
- Large-scale data ingestion pipelines
- Write-heavy workloads where refresh interval of 10s+ is acceptable

**Not ideal for:**
- **Latency-sensitive vector search / k-NN workloads**: The 10-second minimum refresh interval and S3-sync architecture add latency. For Amazon OpenSearch Service, standard memory-optimized instances such as r7g/r8g are often a better fit for pure low-latency vector search
- Real-time search with sub-second refresh requirements
- Read-heavy workloads with minimal indexing

### Vector Search Considerations

For vector search workloads, optimized instances can be used but with caveats:
- The 10-second refresh interval means newly indexed vectors won't be searchable immediately
- S3 sync adds write latency, which can impact bulk vector indexing throughput
- For pure low-latency vector search clusters on Amazon OpenSearch Service, standard memory-optimized instances such as **r7g/r8g** usually provide better search latency
- For mixed workloads (logs + vectors), OR2/OM2 can be cost-effective for the log portion

## Requirements & Limitations

- **OpenSearch version**: 2.11+ for new domains, 2.15+ for existing domains
- **Encryption at rest**: Must be enabled
- **Master nodes**: Must use Graviton instances (c6g, m6g, r6g, or newer)
- **Refresh interval**: Minimum 10 seconds
- **Replica behavior**: Replicas may lag primary shards by a few seconds (monitor via `ReplicationLagMaxTime` metric)

## Provisioning Example

```bash
# Create domain with OR2 instances
aws opensearch create-domain \
  --domain-name my-domain \
  --engine-version OpenSearch_2.17 \
  --cluster-config "InstanceType=or2.2xlarge.search,InstanceCount=3,DedicatedMasterEnabled=true,DedicatedMasterType=r7g.large.search,DedicatedMasterCount=3" \
  --ebs-options "EBSEnabled=true,VolumeType=gp3,VolumeSize=200" \
  --encryption-at-rest-options Enabled=true \
  --node-to-node-encryption-options Enabled=true \
  --domain-endpoint-options EnforceHTTPS=true
```

## Cost Comparison (us-east-1, 256 GiB memory tier)

| Instance | Type | Memory | $/month | Notes |
|----------|------|--------|---------|-------|
| r7g.8xlarge | Standard | 256 GiB | $2,076.85 | Strong fit for vector search |
| r8g.8xlarge | Standard | 256 GiB | $2,284.90 | Current-generation performance example |
| or2.8xlarge | Optimized | 256 GiB | $2,336.00 | Best for indexing-heavy + S3 durability |
| or1.8xlarge | Optimized | 256 GiB | $2,442.58 | Previous gen optimized |
| oi2.8xlarge | Optimized | 256 GiB | $3,407.29 | NVMe, highest IOPS |

**Key insight**: For the same memory, optimized instances cost ~10-15% more than standard instances, but include S3-based durability and automatic recovery. Choose based on workload type, not just price.

## Tuning Tips

For best indexing throughput on optimized instances:
1. Use large bulk sizes (recommended: 10 MB per bulk request)
2. Use multiple ingestion clients for parallel processing
3. Set primary shard count = data node count for maximum utilization
4. Monitor `ReplicationLagMaxTime` to ensure replicas stay in sync
