# OpenSearch Vector Search Performance Benchmarks

## Core Concepts

This document provides performance benchmark data for OpenSearch vector search across different node shapes, dataset sizes, and vector dimensions. Many concrete examples use Amazon OpenSearch Service instance names because they are easy to compare, but the portable sizing signals are CPU generation, memory per node, storage IOPS/throughput, shard count, compression, and target latency.

<!-- FALLBACK: opensearch, priority=1 -->
<!-- FALLBACK: aws-pricing, priority=2, condition="cost-related" -->

## Key Performance Metrics

- **QPS (Queries Per Second)**: Queries per second, higher is better
- **Latency (p95/p99)**: Latency percentiles, lower is better
- **Recall@10/100**: Recall rate, higher is better (typically > 0.9 is excellent)
- **ef_search**: HNSW search parameter, affects the balance between recall and performance
- **Load Time**: Index build time (seconds)

## Dataset Size and Instance Selection

### Small-Scale Dataset (1M Vectors)

#### 1M Vectors, 1024 Dimensions

**Example Configuration**: 2 × r7g.xlarge or equivalent memory-optimized nodes (2 shards, 1 replica)

| ef_search | QPS | Latency (p95) | Recall@100 | Notes |
|-----------|-----|---------------|------------|-------|
| 40 | 1327.56 | 8.4ms | 0.8388 | Low-latency scenario |
| 100 | 1145.40 | 9.2ms | 0.9143 | Balanced configuration |
| 200 | 931.13 | 10.5ms | 0.9502 | High-recall scenario |

**Key Findings**:
- Using fp16 can improve performance by approximately 5%
- 2 shards + 1 replica provides good availability
- Load Time: ~1062 seconds

#### 1M Vectors, 1536 Dimensions

**Example Configuration**: 3 × r7g.2xlarge or equivalent memory-optimized nodes (3 shards, 2 replica)

| ef_search | QPS | Latency (p95) | Recall@100 | Notes |
|-----------|-----|---------------|------------|-------|
| 100 | 2356.32 | 11.9ms | 0.9746 | Recommended configuration |
| 200 | 2044.13 | 12.9ms | 0.9915 | High recall |

**Load Time**: ~852 seconds

### Medium-Scale Dataset (10M Vectors)

#### 10M Vectors, 768 Dimensions

**Example Configuration**: 3 × r8g.2xlarge or equivalent memory-optimized nodes (3 shards, 0 replica)

| ef_search | QPS | Latency (p95) | Recall@100 | Notes |
|-----------|-----|---------------|------------|-------|
| 40 | 2078.03 | 6.8ms | 0.8962 | Low latency |
| 100 | 1741.79 | 7.3ms | 0.9389 | Balanced configuration |
| 200 | 1333.02 | 8.1ms | 0.9699 | High recall |

**Key Findings**:
- 6 shards configuration can improve concurrent performance
- ef_construction=400, m=20 can optimize index quality
- GPU acceleration can improve index build speed by approximately 45%

#### 10M Vectors, 1024 Dimensions

**Example Configuration**: 3 × r7g.2xlarge or equivalent memory-optimized nodes (3 shards, 0 replica)

| ef_search | QPS | Latency (p95) | Recall@100 | Notes |
|-----------|-----|---------------|------------|-------|
| 40 | 2788.63 | 7.9ms | 0.8082 | Low latency |
| 100 | 2435.95 | 9.0ms | 0.8755 | Balanced configuration |
| 200 | 1983.60 | 9.7ms | 0.9133 | High recall |

**Load Time**: ~6078 seconds

**High-Performance Example**: 2 × r7g.16xlarge or equivalent high-memory nodes (16 shards)
- ef_search=100: QPS 1856, Latency 9.8ms, Recall@100 0.9245
- Load Time: ~54979 seconds

### Large-Scale Dataset (100M Vectors)

#### 100M Vectors, 768 Dimensions

**In-Memory Mode Example**: r8g.16xlarge.search × 2 or equivalent high-memory nodes (17 shards, 1 replica)

| ef_search | QPS | Latency (p95) | Recall@100 | Memory Usage |
|-----------|-----|---------------|------------|--------------|
| 100 | 2982.79 | 9.6ms | 0.9343 | 315GB × 2 (86.2%) |
| 200 | 2246.56 | 10.3ms | 0.9454 | High memory usage |
| 400 | 1512.79 | 12.9ms | 0.9513 | Highest recall |

**On-Disk Mode Example**: r8g.xlarge × 5 or equivalent IO-backed nodes (10 shards, 1 replica, on-disk 32x)

| ef_search | QPS | Latency (p95) | IOPS | Throughput | Memory Usage |
|-----------|-----|---------------|------|------------|--------------|
| 100 | 32.83 | 132.9ms | 4500 | 250MB/s | 9.7GB/node (83.6%) |
| 200 | 32.59 | 170.2ms | 4500 | 250MB/s | Low memory |

**High IOPS Configuration**: IOPS 9000, Throughput 500MB/s
- ef_search=100: QPS 73.48, Latency 114.9ms
- Performance improvement of approximately 2.2×

**Key Findings**:
- On-disk mode significantly reduces QPS (approximately 1/100)
- High IOPS can partially mitigate on-disk mode performance loss
- In-memory mode is suitable for low-latency requirements
- On-disk mode is suitable for cost-sensitive scenarios

## Quantization Compression (Binary Quantization)

### BQ Performance Comparison (1M Vectors, 1 × r8g.4xlarge)

#### Standard Mode (No Compression)

| Shards | ef_search | QPS | Latency (p95) | Recall@100 |
|--------|-----------|-----|---------------|------------|
| 1 | 100 | 4889.04 | 6.5ms | 0.9697 |
| 1 | 200 | 4294.15 | 6.1ms | 0.9812 |

#### BQ 1-bit (oversample-factor 20)

| Shards | ef_search | QPS | Latency (p95) | Recall@100 | Performance Change |
|--------|-----------|-----|---------------|------------|---------------------|
| 1 | 100 | 3097.73 | 7.9ms | 0.7659 | -37% QPS, -21% Recall |
| 8 | 100 | 570.04 | 11.4ms | 0.9243 | Multi-shard compensation |

#### BQ 4-bit (oversample-factor 20)

| Shards | ef_search | QPS | Latency (p95) | Recall@100 | Performance Change |
|--------|-----------|-----|---------------|------------|---------------------|
| 8 | 100 | 541.84 | 11.8ms | 0.9598 | High recall |
| 8 | 200 | 461.32 | 13.1ms | 0.9838 | Near lossless |

**Key Findings**:
- BQ 1-bit: 32× memory savings, but noticeable recall degradation
- BQ 4-bit: 8× memory savings, near-lossless recall
- Reducing oversample-factor from 20 to 10 can improve QPS by approximately 54%
- Multi-shard configuration can compensate for performance loss from quantization

## On-Disk Mode Cost-Effectiveness Analysis

### 10M Vectors, 1024 Dimensions Comparison

#### In-Memory Mode (om2.2xlarge.search × 1)

| Compression | ef_search | QPS | Latency (p95) | Recall@100 | Memory |
|-------------|-----------|-----|---------------|------------|--------|
| 8x | 100 | 2012.46 | 7.1ms | 0.9214 | Standard |
| 32x | 100 | 1497.58 | 6.1ms | 0.9033 | 2.7MB |

#### On-Disk Mode (om2.2xlarge.search × 1, 4 shards)

| Compression | ef_search | QPS | Latency (p95) | Recall@100 | Cost |
|-------------|-----------|-----|---------------|------------|------|
| 8x | 100 | 43.58 | 148.4ms | 0.9214 | $760.51/month |
| 32x | 100 | 41.61 | 101.8ms | 0.9033 | Lower cost |

**Key Findings**:
- On-disk mode reduces QPS by approximately 98%
- Latency increases by approximately 20×
- Suitable for batch processing or cost-sensitive scenarios
- Unstable: QPS fluctuates between 40-1500, affected by EBS IOPS

### 1M Vectors, 1024 Dimensions Comparison

#### Memory-Optimized Instances (om2.2xlarge.search × 1)

| Compression | ef_search | QPS | Latency (p95) | Recall@100 | Memory |
|-------------|-----------|-----|---------------|------------|--------|
| 32x | 100 | 1710.08 | 7.0ms | 0.8958 | 273KB |
| 8x | 100 | 1384.60 | 7.3ms | 0.9305 | 648KB |

#### General-Purpose / Smaller Memory Nodes (r8g.xlarge × 1 example)

| Compression | ef_search | QPS | Latency (p95) | Recall@100 |
|-------------|-----------|-----|---------------|------------|
| 8x | 100 | 730.89 | 7.1ms | 0.9317 |
| 8x | 200 | 564.56 | 8.3ms | 0.9634 |

**Cost Optimization Recommendations**:
- General-purpose instances are more economical for small datasets
- 8x compression provides the best cost-effectiveness
- 32x compression is suitable for extreme memory-constrained scenarios

## GPU Acceleration Results

### 100M Vectors, 768 Dimensions (3 × r8g.2xlarge)

| Configuration | Index Time | Speedup |
|---------------|------------|---------|
| No GPU | 56271 seconds | Baseline |
| GPU Enabled | 31037 seconds | 1.81× |

**Query Performance** (6 shards, 0 replica, ondisk):

| ef_search | QPS | Latency (p95) | Recall@100 |
|-----------|-----|---------------|------------|
| 100 | 1653.50 | 7.9ms | 0.9121 |
| 200 | 1460.13 | 8.0ms | 0.9243 |
| 400 | 1217.60 | 8.6ms | 0.9291 |

**Key Findings**:
- GPU accelerates index building by approximately 45-81%
- Query performance is not affected by GPU
- Suitable for scenarios requiring frequent index rebuilds

## Instance Selection Recommendations

### Selection by Data Scale (AWS Example Cost Comparison)

| Data Scale | Dimensions | Recommended Instance | Shards | Replica | Expected QPS | Expected Latency | Monthly Cost (USD) |
|------------|------------|---------------------|--------|---------|--------------|------------------|--------------------|
| 1M | 1024 | 2 × r7g.xlarge | 2 | 1 | 1000+ | < 10ms | ~$308 |
| 1M | 1024 (compressed) | 1 × r8g.xlarge | 1 | 0 | 700+ | < 10ms | ~$154 (50% savings) |
| 1M | 1536 | 3 × r7g.2xlarge | 3 | 2 | 2000+ | < 12ms | ~$924 |
| 10M | 768 | 3 × r8g.2xlarge | 3-6 | 0-1 | 1500+ | < 8ms | ~$616 |
| 10M | 1024 | 3 × r7g.2xlarge | 3 | 0 | 2000+ | < 10ms | ~$924 |
| 10M | 1024 (compressed) | 2 × r8g.2xlarge | 4 | 0 | 1200+ | < 12ms | ~$616 (33% savings) |
| 100M | 768 (in-memory) | 2 × r8g.16xlarge | 17 | 1 | 2500+ | < 10ms | ~$4,934 |
| 100M | 768 (on-disk) | 5 × r8g.xlarge | 10 | 1 | 30-70 | < 200ms | ~$970 (80% savings) |

**Cost Notes**:
- Costs are based on AWS us-east-1 region on-demand pricing
- On-disk mode costs include EBS storage fees
- Using Reserved Instances can save an additional 30-60%
- Compressed mode uses 8x quantization compression
- For self-managed OpenSearch, Kubernetes, or another cloud, use the same memory/CPU/IO profile and replace the price column with your platform's node and storage costs.

### Selection by Performance Requirements (with Cost Tradeoffs)

**Low-Latency Scenario** (< 10ms):
- Use in-memory mode
- ef_search = 40-100
- Choose current-generation CPUs with enough memory for graph/cache headroom
- Avoid on-disk mode
- **Cost**: High (baseline)
- **Use Case**: Real-time recommendations, search services

**High-Throughput Scenario** (> 2000 QPS):
- Increase the number of shards
- Use larger nodes when CPU saturation, network limits, or shard overhead become bottlenecks
- Consider multiple replicas to distribute load
- **Cost**: Very high (baseline × 2-3)
- **Use Case**: High-traffic applications

**Cost-Optimized Scenario**:
- Use on-disk mode + quantization compression
- Accept higher latency (100-200ms)
- Suitable for batch processing or offline scenarios
- **Cost**: Low (50-80% savings)
- **Use Case**: Batch processing, data analytics, MVP stage

**High-Recall Scenario** (Recall > 0.95):
- ef_search = 200-400
- ef_construction = 400+
- Avoid excessive quantization compression
- **Cost**: Medium-high (baseline × 1.2-1.5)
- **Use Case**: Precision matching, mission-critical workloads

**Balanced Scenario** (Recommended):
- Use 8x quantization compression
- ef_search = 100-200
- In-memory mode + reasonable sharding
- **Cost**: Medium (30-50% savings)
- **Use Case**: Most production environments

## Parameter Tuning Recommendations

### HNSW Parameters

**ef_construction**:
- Default: 128
- High-quality index: 200-400
- Tradeoff: Higher values increase indexing time but improve recall

**m (connections)**:
- Default: 16
- High-dimensional data: 20-24
- Tradeoff: Higher values increase memory but improve recall

**ef_search**:
- Low latency: 40-100
- Balanced: 100-200
- High recall: 200-400

### Quantization Compression Parameters

**oversample-factor**:
- BQ 1-bit: 10-20
- BQ 4-bit: 20
- Tradeoff: Higher values improve recall but reduce performance

**Compression Ratio Selection**:
- 32x (1-bit): Extreme memory constraints, acceptable recall loss
- 8x (4-bit): Recommended, near-lossless recall
- No compression: Sufficient memory, pursuing maximum performance

### Sharding Strategy

**Number of Shards**:
- Small dataset (< 10M): 2-4 shards
- Medium dataset (10M-50M): 6-9 shards
- Large dataset (> 50M): 10-17 shards
- Rule of thumb: shards ≈ CPU cores × 1.5

**Number of Replicas**:
- Development environment: 0 replicas
- Production environment: 1-2 replicas
- High availability: 2 replicas (3 AZs)

## Common Issues

### Issue 1: Unstable QPS with Large Fluctuations

**Symptoms**: QPS fluctuates from tens to thousands, latency also fluctuates significantly

**Causes**:
- EBS IOPS throttling in on-disk mode
- Insufficient memory causing frequent page swaps
- Excessive JVM GC pressure

**Solutions**:
1. Check EBS IOPS and throughput configuration
2. Increase IOPS to 9000+, throughput to 500MB/s+
3. Monitor memory usage, consider upgrading instances
4. Adjust JVM heap size

### Issue 2: Recall Lower Than Expected

**Symptoms**: Recall@100 < 0.9

**Causes**:
- ef_search set too low
- Excessive quantization compression loss
- Insufficient index quality

**Solutions**:
1. Increase ef_search to 200+
2. Use 4-bit instead of 1-bit quantization
3. Increase ef_construction to 400+
4. Increase oversample-factor

### Issue 3: Excessive Memory Usage

**Symptoms**: Memory usage > 85%, frequent OOM

**Causes**:
- Dataset too large
- Compression not enabled
- Too many replicas

**Solutions**:
1. Enable quantization compression (8x or 32x)
2. Use on-disk mode
3. Reduce the number of replicas
4. Upgrade to memory-optimized instances

### Issue 4: Index Build Time Too Long

**Symptoms**: Load Time > 10 hours

**Causes**:
- Dataset too large
- ef_construction set too high
- Single-threaded writes

**Solutions**:
1. Enable GPU acceleration (45-81% improvement)
2. Reduce ef_construction to 128-200
3. Increase the number of write threads
4. Use more shards for parallel building

## Performance Testing Tools

**Recommended Tools**:
- opensearch-benchmark: Official performance testing tool
- vector-search-benchmark: Vector search-specific benchmarking tool

**Key Metrics to Monitor**:
- CloudWatch: CPU, Memory, IOPS, Network
- OpenSearch Metrics: JVM heap, GC, Query latency
- Custom Metrics: QPS, Recall, Index size

## Cost Comparison Analysis

### Cost-Effectiveness Comparison of Different Configurations

#### Small-Scale Scenario (1M Vectors, 768 Dimensions)

| Configuration | Instance Setup | Monthly Cost | QPS | Latency | Cost/1000 QPS |
|---------------|----------------|-------------|-----|---------|---------------|
| Standard In-Memory | 2 × r8g.xlarge | $308 | 1,327 | 8.4ms | $232 |
| 8x Compression | 1 × r8g.xlarge | $154 | 730 | 7.1ms | $211 |
| 32x Compression | 1 × r8g.large | $77 | 400 | 8.5ms | $193 |
| On-Disk Mode | 1 × r8g.large | $95 | 25 | 150ms | $3,800 |

**Best Choice**: 8x compression (best cost-effectiveness)

#### Medium-Scale Scenario (10M Vectors, 1024 Dimensions)

| Configuration | Instance Setup | Monthly Cost | QPS | Latency | Cost/1000 QPS |
|---------------|----------------|-------------|-----|---------|---------------|
| Standard In-Memory | 3 × r7g.2xlarge | $924 | 2,435 | 9.0ms | $379 |
| 8x Compression | 2 × r8g.2xlarge | $616 | 1,200 | 11ms | $513 |
| On-Disk Mode | 1 × om2.2xlarge | $761 | 43 | 148ms | $17,698 |

**Best Choice**:
- High-performance needs: Standard in-memory
- Cost-sensitive: 8x compression (33% savings)

#### Large-Scale Scenario (100M Vectors, 768 Dimensions)

| Configuration | Instance Setup | Monthly Cost | QPS | Latency | Cost/1000 QPS |
|---------------|----------------|-------------|-----|---------|---------------|
| In-Memory Mode | 2 × r8g.16xlarge | $4,934 | 2,982 | 9.6ms | $1,655 |
| On-Disk Mode (Standard) | 5 × r8g.xlarge | $770 | 32 | 132ms | $24,063 |
| On-Disk Mode (High IOPS) | 5 × r8g.xlarge | $970 | 73 | 114ms | $13,288 |

**Best Choice**:
- Real-time services: In-memory mode
- Batch processing: On-disk mode (80% savings)

### Compression Level Cost-Effectiveness Analysis

#### 1M Vectors, 1024 Dimensions, Single Instance Comparison

| Compression Level | Instance Type | Monthly Cost | Memory Usage | QPS | Recall | Cost-Effectiveness Score |
|-------------------|---------------|-------------|--------------|-----|--------|--------------------------|
| No Compression | r8g.4xlarge | $617 | 8.7 GB | 4,889 | 0.970 | 7.9 |
| 8x (4-bit) | r8g.xlarge | $154 | 1.1 GB | 730 | 0.960 | **9.5** ⭐ |
| 32x (1-bit) | r8g.large | $77 | 273 KB | 400 | 0.766 | 5.2 |

**Cost-Effectiveness Score** = (QPS × Recall) / Cost × 100

**Conclusion**: 8x compression provides the best cost-effectiveness

### Replica Strategy Cost Impact

| Replicas | Cost Multiplier | Availability | Read Performance | Recommended Scenario |
|----------|-----------------|--------------|------------------|---------------------|
| 0 | 1× | Low | Baseline | Development/Testing |
| 1 | 2× | High | +50% | Production (recommended) |
| 2 | 3× | Very high | +100% | Mission-critical services |

**Cost Optimization Recommendations**:
- Development environment: 0 replicas (50% savings)
- Production environment: 1 replica (balance cost and availability)
- Mission-critical services: 2 replicas (highest availability)

### Reserved Instances Cost Savings

#### 1-Year Reserved Instance Discounts

| Instance Type | On-Demand Price | 1-Year Reserved | Savings | 3-Year Reserved | Savings |
|---------------|-----------------|-----------------|---------|-----------------|---------|
| r8g.xlarge | $154/month | $108/month | 30% | $77/month | 50% |
| r8g.2xlarge | $308/month | $216/month | 30% | $154/month | 50% |
| r8g.4xlarge | $617/month | $432/month | 30% | $308/month | 50% |
| r8g.16xlarge | $2,467/month | $1,727/month | 30% | $1,234/month | 50% |

**Break-Even Period**:
- 1-year reserved: Takes effect immediately
- 3-year reserved: Suitable for long-term stable services

### Overall Cost Optimization Strategy

#### Cost Optimization Priority

1. **Use 8x Quantization Compression** → 50-75% savings
   - Near-lossless recall
   - Takes effect immediately
   - No architecture changes required

2. **Optimize Replica Configuration** → 33-50% savings
   - Use 0 replicas for development environments
   - Use 1 replica for production environments
   - Avoid excessive redundancy

3. **Use Reserved Instances** → 30-50% savings
   - 1-year reserved suitable for most scenarios
   - 3-year reserved suitable for core services
   - Requires long-term commitment

4. **Consider On-Disk Mode** → 50-80% savings
   - Only suitable for batch processing scenarios
   - Must accept higher latency
   - Requires high IOPS EBS

5. **Right-Size Instances** → 20-40% savings
   - Monitor resource utilization
   - Target 60-80% CPU/memory
   - Evaluate and adjust periodically

#### Cost Optimization Decision Tree

```
Can you accept 5% recall loss?
├─ Yes → Use 8x compression (recommended)
│   └─ Is this a production environment?
│       ├─ Yes → 1 replica + 1-year RI → Total savings 65%
│       └─ No → 0 replicas → Total savings 75%
└─ No → Can you accept 100ms+ latency?
    ├─ Yes → On-disk mode + 32x compression → Total savings 80%
    └─ No → Standard configuration + 1-year RI → Total savings 30%
```

## Reference Resources

- OpenSearch k-NN Official Documentation
- HNSW Algorithm Paper
- Binary Quantization Technical Documentation
- AWS EC2 Instance Type Comparison
- [AWS Pricing Calculator](https://calculator.aws/) - Cost estimation tool
- [OpenSearch Cost Optimization Blog](https://aws.amazon.com/blogs/big-data/) - Latest optimization techniques
