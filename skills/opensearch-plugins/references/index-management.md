# Index Management

The Index Management (IM) plugin provides tools for managing the lifecycle, transformation, and maintenance of OpenSearch indices. It includes Index State Management (ISM) for policy-driven automation, rollups and transforms for data aggregation, and index rollover for time-series data.

## Key Concepts

- **Index State Management (ISM)** — Define policies that automatically transition indices through states (e.g., hot → warm → delete) based on conditions like age, size, or document count.
- **Policy** — A JSON document defining states, transitions, and actions. Attached to indices via the ISM API or index templates.
- **State** — A named stage in the index lifecycle (e.g., `hot`, `warm`, `cold`, `delete`). Each state has actions and transitions.
- **Action** — An operation performed in a state: `rollover`, `replica_count`, `read_only`, `force_merge`, `shrink`, `snapshot`, `delete`, `allocation`, and others.
- **Transition** — A condition that triggers moving to the next state (e.g., `min_index_age: 30d`).
- **Rollover** — Create a new index when the current one meets a condition (age, size, doc count). Used with index aliases for time-series data.
- **Rollup** — Aggregate historical data into a summary index with reduced granularity to save storage.
- **Transform** — Create a summary index by grouping and aggregating data from a source index.
- **Snapshot management** — Automate snapshot creation and deletion on a schedule.

## Common Use Cases

- Automating hot-warm-cold-delete lifecycle for log data
- Rolling over time-series indices (daily, weekly) with aliases
- Reducing storage costs by rolling up old metrics data
- Scheduled snapshots for backup and recovery

## Guides

- [ISM policies](https://docs.opensearch.org/latest/im-plugin/ism/policies/) — Policy structure, actions, transitions, and sample policies (includes auto-rollover example)
- [ISM error prevention](https://docs.opensearch.org/latest/im-plugin/ism/error-prevention/index/) — Common ISM errors and resolutions
- [Data streams](https://docs.opensearch.org/latest/im-plugin/data-streams/) — Time-series data management with append-only indices

## Official Documentation

- [Index Management overview](https://docs.opensearch.org/latest/im-plugin/index/)
- [ISM overview](https://docs.opensearch.org/latest/im-plugin/ism/index/)
- [ISM API](https://docs.opensearch.org/latest/im-plugin/ism/api/)
- [Rollup](https://docs.opensearch.org/latest/im-plugin/index-rollups/index/)
- [Transform](https://docs.opensearch.org/latest/im-plugin/index-transforms/index/)
- [Snapshot management](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-management/)
- [Index rollover](https://docs.opensearch.org/latest/im-plugin/ism/policies/#rollover)
