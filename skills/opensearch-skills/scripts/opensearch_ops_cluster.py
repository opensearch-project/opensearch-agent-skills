#!/usr/bin/env python3
"""
Cluster operations commands for opensearch_ops.py.

Requires: opensearch-py (already declared in the project's pyproject.toml).

These functions are designed to be imported by opensearch_ops.py and wired
into its argparse dispatch table, or called directly for testing.

Usage (via the main CLI):
    uv run python scripts/opensearch_ops.py cluster-health
    uv run python scripts/opensearch_ops.py cluster-stats
    uv run python scripts/opensearch_ops.py allocation-explain [--index <name>] [--shard <n>] [--primary]
    uv run python scripts/opensearch_ops.py list-shards [--state UNASSIGNED]
    uv run python scripts/opensearch_ops.py node-stats [--node <name>]
    uv run python scripts/opensearch_ops.py hot-threads [--node <name>] [--threads <n>]
    uv run python scripts/opensearch_ops.py reroute-retry
    uv run python scripts/opensearch_ops.py set-replicas --index <name> --replicas <n>
    uv run python scripts/opensearch_ops.py clear-cache [--index <name>] [--type fielddata|request|query]
    uv run python scripts/opensearch_ops.py disk-usage
    uv run python scripts/opensearch_ops.py list-ism-policies
    uv run python scripts/opensearch_ops.py apply-ism-policy --index <name> --policy-id <id>
"""

import argparse
import json
import os
import sys

# ---------------------------------------------------------------------------
# Client helper — reuse the existing lib/client module when available,
# fall back to a minimal inline implementation for testing environments.
# ---------------------------------------------------------------------------

def _get_client():
    """Return an OpenSearch client using the same resolution logic as opensearch_ops.py.

    Primary path: reuse lib.client.create_client() which handles all auth modes
    (basic, SigV4 for AOS/AOSS) and TLS settings from the shared configuration.

    Fallback path (lib.client unavailable): build a minimal client from environment
    variables. TLS certificate verification is always enabled; set
    OPENSEARCH_SSL_VERIFY=false explicitly to disable it in local development
    environments where a self-signed certificate is in use.
    """
    # Insert the scripts directory once so lib.* imports resolve,
    # then narrow the try/except to the import statement only.
    _scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)

    try:
        from lib.client import create_client
    except ImportError:
        create_client = None

    if create_client is not None:
        return create_client()
    else:
        # Minimal fallback: honour OPENSEARCH_URL / OPENSEARCH_USERNAME / OPENSEARCH_PASSWORD
        from opensearchpy import OpenSearch
        url = os.environ.get("OPENSEARCH_URL", "https://localhost:9200")
        username = os.environ.get("OPENSEARCH_USERNAME")
        password = os.environ.get("OPENSEARCH_PASSWORD")
        if not username or not password:
            raise EnvironmentError(
                "OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD must be set. "
                "For AWS auth, use the primary path (lib.client.create_client)."
            )
        # Default to verifying TLS certificates. Set OPENSEARCH_SSL_VERIFY=false
        # only in local development environments with self-signed certificates.
        ssl_verify_env = os.environ.get("OPENSEARCH_SSL_VERIFY", "true").lower()
        verify_certs = ssl_verify_env not in ("false", "0", "no")
        use_ssl = url.startswith("https")
        return OpenSearch(
            hosts=[url],
            http_auth=(username, password),
            use_ssl=use_ssl,
            verify_certs=verify_certs,
        )


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_cluster_health(args):
    """Return cluster health. Optionally drill down to index or shard level."""
    client = _get_client()
    level = getattr(args, "level", "cluster")
    result = client.cluster.health(level=level)
    print(json.dumps(result, indent=2))


def cmd_cluster_stats(args):
    """Return high-level cluster statistics (node count, shard totals, store size)."""
    client = _get_client()
    stats = client.cluster.stats()
    summary = {
        "status": stats.get("status"),
        "node_count": stats.get("nodes", {}).get("count", {}).get("total"),
        "data_node_count": stats.get("nodes", {}).get("count", {}).get("data"),
        "primary_shards": stats.get("indices", {}).get("shards", {}).get("primaries"),
        "replica_shards": stats.get("indices", {}).get("shards", {}).get("replication"),
        "index_count": stats.get("indices", {}).get("count"),
        "store_size_bytes": stats.get("indices", {}).get("store", {}).get("size_in_bytes"),
        "docs_count": stats.get("indices", {}).get("docs", {}).get("count"),
    }
    print(json.dumps(summary, indent=2))


def cmd_allocation_explain(args):
    """
    Call _cluster/allocation/explain to get the authoritative reason a shard
    is unassigned or cannot be allocated to a given node.
    """
    client = _get_client()
    body = {}
    if getattr(args, "index", None):
        body["index"] = args.index
        body["shard"] = getattr(args, "shard", 0)
        body["primary"] = getattr(args, "primary", True)

    try:
        result = client.cluster.allocation_explain(body=body or None)
        # Surface the most useful fields first
        summary = {
            "index": result.get("index"),
            "shard": result.get("shard"),
            "primary": result.get("primary"),
            "current_state": result.get("current_state"),
            "unassigned_info": result.get("unassigned_info"),
            "explanation": result.get("explanation"),
            "can_allocate": result.get("can_allocate"),
            "allocate_explanation": result.get("allocate_explanation"),
            "node_allocation_decisions": [
                {
                    "node_name": d.get("node_name"),
                    "deciders": [
                        dec for dec in d.get("deciders", [])
                        if dec.get("decision") != "YES"
                    ],
                }
                for d in result.get("node_allocation_decisions", [])
                if d.get("can_allocate") != "YES"
            ],
        }
        print(json.dumps(summary, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_list_shards(args):
    """
    List shards filtered by state (default: UNASSIGNED).
    Returns index, shard, primary/replica, state, unassigned reason, and node.
    """
    client = _get_client()
    state_filter = getattr(args, "state", "UNASSIGNED")
    params = {
        "v": True,
        "h": "index,shard,prirep,state,unassigned.reason,unassigned.details,node",
        "s": "state,index",
    }
    try:
        result = client.cat.shards(params=params, format="json")
        if state_filter and state_filter.upper() != "ALL":
            result = [s for s in result if s.get("state", "").upper() == state_filter.upper()]
        print(json.dumps(result, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_node_stats(args):
    """
    Return per-node statistics: JVM heap, CPU, load, circuit breakers.
    Filters to a specific node name if --node is provided.
    """
    client = _get_client()
    node_id = getattr(args, "node", None) or "_all"
    try:
        raw = client.nodes.stats(
            node_id=node_id,
            metric="jvm,os,indices,breaker,thread_pool",
        )
        nodes = raw.get("nodes", {})
        summary = {}
        for nid, info in nodes.items():
            jvm = info.get("jvm", {}).get("mem", {})
            breakers = info.get("breakers", {})
            summary[info.get("name", nid)] = {
                "heap_used_percent": info.get("jvm", {}).get("mem", {}).get("heap_used_percent"),
                "heap_used_mb": round(jvm.get("heap_used_in_bytes", 0) / 1024 / 1024, 1),
                "heap_max_mb": round(jvm.get("heap_max_in_bytes", 0) / 1024 / 1024, 1),
                "cpu_percent": info.get("os", {}).get("cpu", {}).get("percent"),
                "load_1m": info.get("os", {}).get("cpu", {}).get("load_average", {}).get("1m"),
                "fielddata_breaker_tripped": breakers.get("fielddata", {}).get("tripped", 0),
                "request_breaker_tripped": breakers.get("request", {}).get("tripped", 0),
            }
        print(json.dumps(summary, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_hot_threads(args):
    """
    Capture hot thread snapshots from all (or a specific) node.
    Useful for diagnosing CPU spikes and GC pressure.
    """
    client = _get_client()
    node_id = getattr(args, "node", None) or "_all"
    threads = getattr(args, "threads", 5)
    try:
        result = client.nodes.hot_threads(
            node_id=node_id,
            threads=threads,
            type="cpu",
            interval="500ms",
        )
        # hot_threads returns plain text — print as-is
        print(result)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_reroute_retry(args):
    """
    Retry all previously failed shard allocations.
    This is safe: no data loss, no shard moves — just retries assignments
    that failed due to transient errors (disk full, node restart, etc.).
    """
    client = _get_client()
    try:
        result = client.cluster.reroute(retry_failed=True)
        acknowledged = result.get("acknowledged", False)
        print(json.dumps({"acknowledged": acknowledged, "message": "Retried all failed shard allocations."}))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_set_replicas(args):
    """
    Set the replica count for an index.
    Common use case: set replicas=0 on a single-node cluster to go green.
    """
    client = _get_client()
    index = args.index
    replicas = int(args.replicas)
    try:
        result = client.indices.put_settings(
            index=index,
            body={"number_of_replicas": replicas},
        )
        print(json.dumps({"acknowledged": result.get("acknowledged"), "index": index, "replicas": replicas}))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_clear_cache(args):
    """
    Clear index caches. Defaults to clearing all caches.
    Optionally restrict to fielddata, request, or query caches.
    """
    client = _get_client()
    index = getattr(args, "index", None) or "_all"
    cache_type = getattr(args, "type", "all")

    kwargs = {}
    if cache_type == "fielddata":
        kwargs["fielddata"] = True
    elif cache_type == "request":
        kwargs["request"] = True
    elif cache_type == "query":
        kwargs["query"] = True
    # "all" → no filter kwargs → clears everything

    try:
        result = client.indices.clear_cache(index=index, **kwargs)
        print(json.dumps({
            "acknowledged": True,
            "index": index,
            "cache_type": cache_type,
            "_shards": result.get("_shards"),
        }))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_disk_usage(args):
    """
    Show disk usage per node: used, available, total, percent, shard count.
    Flags nodes exceeding the 85% low watermark.
    """
    client = _get_client()
    try:
        result = client.cat.allocation(
            params={
                "v": True,
                "h": "node,shards,disk.used,disk.avail,disk.total,disk.percent",
                "s": "disk.percent:desc",
            },
            format="json",
        )
        LOW_WATERMARK = 85
        for entry in result:
            pct = entry.get("disk.percent", "")
            try:
                entry["warning"] = int(pct) >= LOW_WATERMARK
            except (ValueError, TypeError):
                entry["warning"] = False
        print(json.dumps(result, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


def cmd_list_ism_policies(args):
    """
    List all ISM policies installed on the cluster.
    Returns policy IDs and their descriptions.
    """
    client = _get_client()
    try:
        result = client.transport.perform_request(
            "GET", "/_plugins/_ism/policies"
        )
        policies = result.get("policies", [])
        summary = [
            {
                "id": p.get("_id"),
                "description": p.get("policy", {}).get("description"),
                "default_state": p.get("policy", {}).get("default_state"),
                "states": [s.get("name") for s in p.get("policy", {}).get("states", [])],
                "ism_template": p.get("policy", {}).get("ism_template"),
            }
            for p in policies
        ]
        print(json.dumps(summary, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "hint": "ISM plugin may not be installed. Run: GET _cat/plugins?v to verify."}))


def cmd_apply_ism_policy(args):
    """
    Attach an ISM policy to an existing index.
    Requires --index and --policy-id.
    """
    client = _get_client()
    index = args.index
    policy_id = args.policy_id
    try:
        result = client.transport.perform_request(
            "POST",
            f"/_plugins/_ism/add/{index}",
            body={"policy_id": policy_id},
        )
        print(json.dumps(result, indent=2))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))


# ---------------------------------------------------------------------------
# Argparse wiring — called by opensearch_ops.py main() to register sub-commands
# ---------------------------------------------------------------------------

def register_commands(sub):
    """Register all cluster-operations sub-commands into an argparse subparsers object."""

    # cluster-health
    p = sub.add_parser("cluster-health", help="Show cluster health summary")
    p.add_argument("--level", default="cluster", choices=["cluster", "indices", "shards"],
                   help="Granularity of health report (default: cluster)")

    # cluster-stats
    sub.add_parser("cluster-stats", help="Show cluster-wide statistics")

    # allocation-explain
    p = sub.add_parser("allocation-explain", help="Explain why a shard is unassigned")
    p.add_argument("--index", default=None, help="Index name (omit to explain the first unassigned shard)")
    p.add_argument("--shard", type=int, default=0, help="Shard number (default: 0)")
    p.add_argument("--primary", action=argparse.BooleanOptionalAction, default=True,
                   help="Explain primary shard (default: true). Use --no-primary to explain a replica.")

    # list-shards
    p = sub.add_parser("list-shards", help="List shards by state")
    p.add_argument("--state", default="UNASSIGNED",
                   help="Filter by shard state: UNASSIGNED, INITIALIZING, RELOCATING, STARTED, ALL (default: UNASSIGNED)")

    # node-stats
    p = sub.add_parser("node-stats", help="Show per-node JVM, CPU, and circuit breaker stats")
    p.add_argument("--node", default=None, help="Node name filter (default: all nodes)")

    # hot-threads
    p = sub.add_parser("hot-threads", help="Capture hot thread snapshots for CPU diagnosis")
    p.add_argument("--node", default=None, help="Node name filter (default: all nodes)")
    p.add_argument("--threads", type=int, default=5, help="Number of hot threads to capture per node (default: 5)")

    # reroute-retry
    sub.add_parser("reroute-retry", help="Retry all previously failed shard allocations (safe, no data loss)")

    # set-replicas
    p = sub.add_parser("set-replicas", help="Set replica count for an index")
    p.add_argument("--index", required=True, help="Index name")
    p.add_argument("--replicas", required=True, type=int, help="Number of replicas (0 for single-node clusters)")

    # clear-cache
    p = sub.add_parser("clear-cache", help="Clear index caches")
    p.add_argument("--index", default=None, help="Index name (default: all indices)")
    p.add_argument("--type", default="all", choices=["all", "fielddata", "request", "query"],
                   help="Cache type to clear (default: all)")

    # disk-usage
    sub.add_parser("disk-usage", help="Show disk usage per node with watermark warnings")

    # list-ism-policies
    sub.add_parser("list-ism-policies", help="List all ISM policies on the cluster")

    # apply-ism-policy
    p = sub.add_parser("apply-ism-policy", help="Attach an ISM policy to an existing index")
    p.add_argument("--index", required=True, help="Index name")
    p.add_argument("--policy-id", required=True, help="ISM policy ID to attach")


DISPATCH = {
    "cluster-health": cmd_cluster_health,
    "cluster-stats": cmd_cluster_stats,
    "allocation-explain": cmd_allocation_explain,
    "list-shards": cmd_list_shards,
    "node-stats": cmd_node_stats,
    "hot-threads": cmd_hot_threads,
    "reroute-retry": cmd_reroute_retry,
    "set-replicas": cmd_set_replicas,
    "clear-cache": cmd_clear_cache,
    "disk-usage": cmd_disk_usage,
    "list-ism-policies": cmd_list_ism_policies,
    "apply-ism-policy": cmd_apply_ism_policy,
}
