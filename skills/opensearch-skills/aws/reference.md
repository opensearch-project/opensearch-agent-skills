# Amazon OpenSearch Service Deployment Reference

Reference material for cost, security, and operations. Load only when the user asks about these topics.

## Cost: OpenSearch Serverless

- Charged per OCU (OpenSearch Compute Units) hour
- Minimum: 2 OCUs for indexing, 2 OCUs for search
- Scales automatically based on workload
- Storage charged separately per GB
- Neural sparse enrichment: charged based on SemanticSearchOCU CloudWatch metric

## Cost: OpenSearch Domain

- Instance hours (varies by instance type)
- EBS storage (GB-month)
- Data transfer and snapshot storage

Typical small production cluster:
- 3x r6g.large.search: ~$400-500/month
- 300GB EBS storage: ~$30/month

Cost optimization: reserved instances (up to 30% savings), right-sizing, UltraWarm for cold data.

## Security Best Practices

1. **Network**: Deploy in VPC for production, use security groups, enable VPC Flow Logs
2. **Access**: Enable fine-grained access control, use IAM roles, least-privilege policies
3. **Encryption**: At-rest encryption, node-to-node encryption, enforce HTTPS
4. **Monitoring**: Enable CloudWatch logs, set up security alerting

## High Availability (Domain)

1. Enable zone awareness, distribute across 3 AZs
2. Enable automated snapshots to S3
3. Configure standby replicas
4. Test restore procedures

## Monitoring

1. CloudWatch logs: index slow logs, search slow logs, error logs, audit logs
2. CloudWatch alarms: cluster health, CPU/memory, storage, JVM pressure
3. SNS notifications for alerts

## Troubleshooting

| Issue | Check |
|---|---|
| Domain creation fails | Service quotas, VPC config, IAM permissions |
| Cluster health yellow/red | Shard allocation, storage space, node health |
| Access denied | Fine-grained access control, IAM policies, data access policies |
| Model deployment fails | ML plugin enabled, memory allocation, Bedrock region availability |
| Slow queries | Slow logs, query optimization, resource utilization |
| Collection creation fails | Service quotas, region availability, encryption policy |
