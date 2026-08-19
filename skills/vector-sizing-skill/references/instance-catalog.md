# OpenSearch Instance Type Catalog (Multi-Cloud)

## AWS — OpenSearch Service (Managed)

| Instance | vCPU | RAM | Usable* | $/hr | Monthly |
|----------|------|-----|--------:|-----:|--------:|
| r7g.4xlarge.search | 16 | 128 GB | 50 GB | $2.008 | $1,466 |
| r7g.8xlarge.search | 32 | 256 GB | 117 GB | $4.016 | $2,932 |
| r7g.12xlarge.search | 48 | 384 GB | 184 GB | $6.024 | $4,398 |
| r7g.16xlarge.search | 64 | 512 GB | 251 GB | $8.032 | $5,863 |
| r8g.8xlarge.search | 32 | 256 GB | 117 GB | $4.256 | $3,107 |
| r8g.12xlarge.search | 48 | 384 GB | 184 GB | $6.384 | $4,660 |
| r8g.16xlarge.search | 64 | 512 GB | 251 GB | $8.512 | $6,214 |
| r8g.24xlarge.search | 96 | 768 GB | 386 GB | $12.768 | $9,321 |
| or1.8xlarge.search | 32 | 256 GB | 117 GB | $4.660 | $3,402 |
| or1.12xlarge.search | 48 | 384 GB | 184 GB | $6.990 | $5,103 |
| or1.16xlarge.search | 64 | 512 GB | 251 GB | $9.320 | $6,804 |

## AWS — EC2 (Self-Managed)

| Instance | vCPU | RAM | Usable* | $/hr | Monthly |
|----------|------|-----|--------:|-----:|--------:|
| r7g.4xlarge | 16 | 128 GB | 50 GB | $1.428 | $1,042 |
| r7g.8xlarge | 32 | 256 GB | 117 GB | $2.856 | $2,085 |
| r7g.12xlarge | 48 | 384 GB | 184 GB | $4.284 | $3,127 |
| r7g.16xlarge | 64 | 512 GB | 251 GB | $5.712 | $4,170 |
| r8g.8xlarge | 32 | 256 GB | 117 GB | $3.024 | $2,208 |
| r8g.12xlarge | 48 | 384 GB | 184 GB | $4.536 | $3,311 |
| r8g.16xlarge | 64 | 512 GB | 251 GB | $6.048 | $4,415 |
| r8g.24xlarge | 96 | 768 GB | 386 GB | $9.072 | $6,623 |
| r7i.12xlarge | 48 | 384 GB | 184 GB | $4.536 | $3,311 |
| r7i.16xlarge | 64 | 512 GB | 251 GB | $6.048 | $4,415 |
| r7i.24xlarge | 96 | 768 GB | 386 GB | $9.072 | $6,623 |
| x2idn.16xlarge | 64 | 1024 GB | 520 GB | $8.004 | $5,843 |
| x2idn.24xlarge | 96 | 1536 GB | 789 GB | $12.006 | $8,764 |

## Azure — VMs (Self-Managed)

| Instance | vCPU | RAM | Usable* | $/hr | Monthly |
|----------|------|-----|--------:|-----:|--------:|
| Standard_E16s_v5 | 16 | 128 GB | 50 GB | $1.208 | $882 |
| Standard_E32s_v5 | 32 | 256 GB | 117 GB | $2.416 | $1,764 |
| Standard_E48s_v5 | 48 | 384 GB | 184 GB | $3.624 | $2,646 |
| Standard_E64s_v5 | 64 | 512 GB | 251 GB | $4.832 | $3,527 |
| Standard_E96s_v5 | 96 | 672 GB | 336 GB | $7.248 | $5,291 |
| Standard_E16as_v5 | 16 | 128 GB | 50 GB | $1.088 | $794 |
| Standard_E32as_v5 | 32 | 256 GB | 117 GB | $2.176 | $1,588 |
| Standard_E48as_v5 | 48 | 384 GB | 184 GB | $3.264 | $2,383 |
| Standard_E64as_v5 | 64 | 512 GB | 251 GB | $4.352 | $3,177 |
| Standard_E96as_v5 | 96 | 672 GB | 336 GB | $6.528 | $4,765 |
| Standard_M128s_v2 | 128 | 2048 GB | 1059 GB | $26.688 | $19,482 |

## GCP — VMs (Self-Managed)

| Instance | vCPU | RAM | Usable* | $/hr | Monthly |
|----------|------|-----|--------:|-----:|--------:|
| n2-highmem-16 | 16 | 128 GB | 50 GB | $1.136 | $829 |
| n2-highmem-32 | 32 | 256 GB | 117 GB | $2.272 | $1,659 |
| n2-highmem-48 | 48 | 384 GB | 184 GB | $3.408 | $2,488 |
| n2-highmem-64 | 64 | 512 GB | 251 GB | $4.544 | $3,317 |
| n2-highmem-80 | 80 | 640 GB | 319 GB | $5.680 | $4,146 |
| n2-highmem-96 | 96 | 768 GB | 386 GB | $6.816 | $4,976 |
| n2d-highmem-32 | 32 | 256 GB | 117 GB | $1.984 | $1,448 |
| n2d-highmem-48 | 48 | 384 GB | 184 GB | $2.976 | $2,172 |
| n2d-highmem-64 | 64 | 512 GB | 251 GB | $3.968 | $2,897 |
| n2d-highmem-96 | 96 | 768 GB | 386 GB | $5.952 | $4,345 |
| m2-megamem-416 | 416 | 5888 GB | 3074 GB | $51.53 | $37,617 |
| m2-ultramem-208 | 208 | 5888 GB | 3074 GB | $42.186 | $30,796 |

*Usable = (RAM - 31 GB JVM heap - 2 GB OS) x 70% usable ratio x 75% max utilization

## Cloud Selection Guide

### When to choose AWS OpenSearch Service (Managed)
- Want zero operational overhead (patching, backups, monitoring included)
- Need integrated AWS ecosystem (IAM, VPC, CloudWatch, fine-grained access control)
- Willing to pay premium for convenience
- Need OR1 instances (Optimized Engine)

### When to choose AWS EC2 (Self-Managed)
- Need maximum control over configuration
- Want x2idn instances (up to 1.5 TB RAM per node)
- Cost-sensitive but want to stay on AWS
- Need custom plugins or OpenSearch versions

### When to choose Azure
- Existing Azure infrastructure / compliance requirements
- E*as_v5 series offers strong price/performance (AMD EPYC)
- M-series for extreme memory (2 TB per node)
- Integration with Azure Monitor, Azure AD

### When to choose GCP
- Best raw price/performance ratio for memory (n2d-highmem)
- n2-highmem-96 offers 768 GB at lowest cost among 96-vCPU options
- m2-ultramem for extreme scale (5.8 TB per node)
- Integration with BigQuery, Vertex AI

## Storage by Cloud

| Cloud | Disk Type | IOPS | Notes |
|-------|-----------|------|-------|
| AWS OpenSearch | EBS gp3 | 3000-16000 | Included in service |
| AWS EC2 | EBS gp3 / io2 | 3000-64000 | Separate cost |
| Azure | Premium SSD v2 | Configurable | Pay for provisioned IOPS |
| GCP | pd-ssd | Scales with size | 30 IOPS/GB |

## Cost Optimization Tips

1. **Reserved/Committed**: AWS RIs save ~35% (1yr), GCP CUDs save ~37%, Azure RIs save ~40%
2. **AMD variants**: Azure E*as_v5 and GCP n2d are 10-20% cheaper than Intel equivalents
3. **Quantization first**: FP16 halves your memory needs before adding hardware
4. **Right-size replicas**: 0 replicas for dev/test, 1 for prod
5. **Managed vs self-managed**: Self-managed saves 30-50% on compute but adds operational cost (patching, monitoring, backup management)

## Master Node Recommendations

| Cloud | Instance | Count |
|-------|----------|-------|
| AWS OpenSearch | r7g.large.search | 3 |
| AWS EC2 | r7g.large | 3 |
| Azure | Standard_E2s_v5 | 3 |
| GCP | n2-highmem-2 | 3 |
