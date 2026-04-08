# Cross-Cluster Replication

Cross-Cluster Replication (CCR) replicates indices from one OpenSearch cluster to another, enabling disaster recovery, geo-locality for low-latency reads, and centralized reporting across distributed deployments.

## Key Concepts

- **Leader index** — The source index on the leader (remote) cluster. All writes go here.
- **Follower index** — The replicated index on the follower (local) cluster. Read-only; automatically kept in sync with the leader.
- **Replication rule** — An autofollow pattern that automatically replicates new indices matching a pattern (e.g., `logs-*`) from the leader cluster.
- **Remote cluster connection** — A configured connection from the follower cluster to the leader cluster. Defined in cluster settings using seed nodes.
- **Syncing** — The follower index continuously pulls changes (new documents, updates, deletes) from the leader index via shard-level replication tasks.
- **Pause / Resume** — Replication can be paused and resumed on individual follower indices without data loss.
- **Status** — Monitor replication lag, syncing state, and any errors via the replication status API.
- **Auto-follow** — Automatically start replicating new indices on the leader that match a specified pattern.

## Common Use Cases

- Disaster recovery with a hot standby cluster in another region
- Low-latency reads by replicating data close to users in different geographies
- Centralizing data from multiple clusters into one reporting cluster
- Migrating data between clusters

## Official Documentation

- [Cross-cluster replication overview](https://docs.opensearch.org/latest/tuning-your-cluster/replication-plugin/index/)
- [Getting started](https://docs.opensearch.org/latest/tuning-your-cluster/replication-plugin/getting-started/)
- [Autofollow](https://docs.opensearch.org/latest/tuning-your-cluster/replication-plugin/auto-follow/)
- [Settings reference](https://docs.opensearch.org/latest/tuning-your-cluster/replication-plugin/settings/)
- [API reference](https://docs.opensearch.org/latest/tuning-your-cluster/replication-plugin/api/)
