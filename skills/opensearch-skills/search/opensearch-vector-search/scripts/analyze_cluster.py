#!/usr/bin/env python3
"""
OpenSearch Vector Search Cluster Analyzer

Connects to an OpenSearch cluster and analyzes vector (k-NN) index configurations.
Provides optimization recommendations based on best practices.

Usage:
  python3 analyze_cluster.py --url <opensearch_url> --username <user> --password <pass>
  python3 analyze_cluster.py --url <opensearch_url> --no-auth
  python3 analyze_cluster.py --url <opensearch_url> --username <user> --password <pass> --index <index_name>
  python3 analyze_cluster.py --url <opensearch_url> --username <user> --password <pass> --action cluster-overview
  python3 analyze_cluster.py --url <opensearch_url> --username <user> --password <pass> --action index-detail --index <index_name>
  python3 analyze_cluster.py --url <opensearch_url> --username <user> --password <pass> --action shard-analysis --index <index_name>

Actions:
  cluster-overview  - Cluster health, nodes, and all k-NN index summary (default)
  index-detail      - Deep dive into a specific index's vector configuration
  shard-analysis    - Shard distribution and sizing for a specific index
  all               - Run all analyses

Output: JSON format for easy parsing by AI agents.

Safety: This script is READ-ONLY. It never creates, modifies, or deletes any indices or data.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


try:
    from opensearchpy import OpenSearch, RequestsHttpConnection
except ImportError:
    OpenSearch = None
    RequestsHttpConnection = None


def create_client(url: str, username: str = None, password: str = None,
                  no_auth: bool = False, verify_ssl: bool = True) -> OpenSearch:
    """Create an OpenSearch client connection."""
    if OpenSearch is None or RequestsHttpConnection is None:
        print(json.dumps({
            "error": "opensearch-py not installed. Run: uv add opensearch-py or use a Python environment with opensearch-py.",
            "success": False
        }))
        sys.exit(1)

    parsed = url.rstrip("/")
    use_ssl = parsed.startswith("https")

    kwargs = {
        "hosts": [parsed],
        "use_ssl": use_ssl,
        "verify_certs": verify_ssl,
        "ssl_show_warn": not verify_ssl,
        "connection_class": RequestsHttpConnection,
        "timeout": 30,
    }

    if not no_auth and username and password:
        kwargs["http_auth"] = (username, password)

    return OpenSearch(**kwargs)


def _as_int(value, default: int = 0) -> int:
    """Return an integer value without raising on incomplete API responses."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_request(func, *args, **kwargs):
    """Execute a request safely, returning None on error."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        return {"_error": str(e)}


def get_cluster_overview(client: OpenSearch) -> dict:
    """Get cluster health, version, and node information."""
    result = {}

    # Cluster health
    health = safe_request(client.cluster.health)
    if health and "_error" not in health:
        result["cluster_health"] = {
            "cluster_name": health.get("cluster_name"),
            "status": health.get("status"),
            "number_of_nodes": health.get("number_of_nodes"),
            "number_of_data_nodes": health.get("number_of_data_nodes"),
            "active_primary_shards": health.get("active_primary_shards"),
            "active_shards": health.get("active_shards"),
            "unassigned_shards": health.get("unassigned_shards"),
        }
    else:
        result["cluster_health"] = health

    # Cluster info (version)
    info = safe_request(client.info)
    if info and "_error" not in info:
        version_info = info.get("version", {})
        result["version"] = {
            "distribution": version_info.get("distribution", "elasticsearch"),
            "number": version_info.get("number"),
            "lucene_version": version_info.get("lucene_version"),
        }
    else:
        result["version"] = info

    # Node stats
    try:
        nodes_stats = client.nodes.stats(metric="os,jvm,indices")
        nodes_summary = []
        if "nodes" in nodes_stats:
            for node_id, node_data in nodes_stats["nodes"].items():
                node_info = {
                    "name": node_data.get("name"),
                    "roles": node_data.get("roles", []),
                    "os": {},
                    "jvm": {},
                    "indices": {},
                }
                # OS info
                os_data = node_data.get("os", {})
                mem = os_data.get("mem", {})
                node_info["os"] = {
                    "total_memory_gb": round(mem.get("total_in_bytes", 0) / (1024**3), 1),
                    "used_memory_gb": round(mem.get("used_in_bytes", 0) / (1024**3), 1),
                    "free_memory_gb": round(mem.get("free_in_bytes", 0) / (1024**3), 1),
                    "memory_used_percent": mem.get("used_percent"),
                    "cpu_percent": os_data.get("cpu", {}).get("percent"),
                }
                # JVM info
                jvm_data = node_data.get("jvm", {})
                jvm_mem = jvm_data.get("mem", {})
                node_info["jvm"] = {
                    "heap_max_gb": round(jvm_mem.get("heap_max_in_bytes", 0) / (1024**3), 2),
                    "heap_used_gb": round(jvm_mem.get("heap_used_in_bytes", 0) / (1024**3), 2),
                    "heap_used_percent": jvm_mem.get("heap_used_percent"),
                }
                # Index stats
                indices_data = node_data.get("indices", {})
                store = indices_data.get("store", {})
                docs = indices_data.get("docs", {})
                node_info["indices"] = {
                    "doc_count": docs.get("count"),
                    "store_size_gb": round(store.get("size_in_bytes", 0) / (1024**3), 2),
                }
                nodes_summary.append(node_info)
        result["nodes"] = nodes_summary
    except Exception as e:
        result["nodes"] = {"_error": str(e)}

    # k-NN stats
    try:
        knn_stats = client.transport.perform_request("GET", "/_plugins/_knn/stats")
        if isinstance(knn_stats, dict):
            # Extract cluster-level knn stats
            cluster_knn = {}
            for key in ["circuit_breaker_triggered", "total_graph_memory",
                        "cache_capacity_reached", "eviction_count",
                        "hit_count", "miss_count", "graph_memory_usage",
                        "graph_memory_usage_percentage", "graph_index_requests",
                        "graph_index_errors", "graph_query_requests",
                        "graph_query_errors", "knn_query_requests"]:
                if key in knn_stats:
                    result.setdefault("knn_stats", {})[key] = knn_stats[key]
            # Node-level knn stats
            nodes_knn = knn_stats.get("nodes", {})
            if nodes_knn:
                node_knn_list = []
                for nid, ndata in nodes_knn.items():
                    node_knn_list.append({
                        "graph_memory_usage": ndata.get("graph_memory_usage"),
                        "graph_memory_usage_percentage": ndata.get("graph_memory_usage_percentage"),
                        "cache_capacity_reached": ndata.get("cache_capacity_reached"),
                        "graph_query_requests": ndata.get("graph_query_requests"),
                        "graph_index_requests": ndata.get("graph_index_requests"),
                    })
                result["knn_node_stats"] = node_knn_list
    except Exception:
        result["knn_stats"] = {"_note": "k-NN plugin may not be installed or accessible"}

    return result


def find_knn_indices(client: OpenSearch) -> list:
    """Find all indices with k-NN vector fields."""
    knn_indices = []

    try:
        # Get all indices
        indices = client.cat.indices(format="json", h="index,docs.count,store.size,pri,rep,health,status")
        if not indices:
            return []

        for idx_info in indices:
            index_name = idx_info.get("index", "")
            # Skip system indices
            if index_name.startswith("."):
                continue

            # Check if index has knn setting or knn_vector fields
            try:
                settings = client.indices.get_settings(index=index_name)
                mappings = client.indices.get_mapping(index=index_name)

                idx_settings = settings.get(index_name, {}).get("settings", {}).get("index", {})
                knn_enabled = idx_settings.get("knn", "false")

                # Check for knn_vector fields in mapping
                idx_mapping = mappings.get(index_name, {}).get("mappings", {})
                vector_fields = _extract_vector_fields(idx_mapping.get("properties", {}))

                if str(knn_enabled).lower() == "true" or vector_fields:
                    knn_indices.append({
                        "index": index_name,
                        "docs_count": idx_info.get("docs.count", "0"),
                        "store_size": idx_info.get("store.size", "0"),
                        "primary_shards": idx_info.get("pri"),
                        "replicas": idx_info.get("rep"),
                        "health": idx_info.get("health"),
                        "status": idx_info.get("status"),
                        "knn_enabled": str(knn_enabled).lower() == "true",
                        "vector_fields_count": len(vector_fields),
                        "vector_fields_summary": [
                            {
                                "name": f["name"],
                                "dimension": f.get("dimension"),
                                "engine": f.get("engine"),
                                "space_type": f.get("space_type"),
                            }
                            for f in vector_fields
                        ],
                    })
            except Exception:
                continue

    except Exception as e:
        return [{"_error": str(e)}]

    return knn_indices


def _extract_vector_fields(properties: dict, prefix: str = "") -> list:
    """Recursively extract knn_vector fields from index mappings."""
    fields = []
    for field_name, field_def in properties.items():
        full_name = f"{prefix}.{field_name}" if prefix else field_name
        if field_def.get("type") == "knn_vector":
            method = field_def.get("method", {})
            params = method.get("parameters", {})
            encoder = params.get("encoder", {})
            fields.append({
                "name": full_name,
                "dimension": field_def.get("dimension"),
                "data_type": field_def.get("data_type", "float"),
                "mode": field_def.get("mode"),
                "compression_level": field_def.get("compression_level"),
                "space_type": field_def.get("space_type") or method.get("space_type"),
                "engine": method.get("engine"),
                "method_name": method.get("name"),
                "hnsw_m": params.get("m"),
                "hnsw_ef_construction": params.get("ef_construction"),
                "encoder_name": encoder.get("name") if encoder else None,
                "encoder_params": encoder.get("parameters") if encoder else None,
            })
        # Recurse into nested/object fields
        if "properties" in field_def:
            fields.extend(_extract_vector_fields(field_def["properties"], full_name))

    return fields


def get_index_detail(client: OpenSearch, index_name: str) -> dict:
    """Get detailed vector configuration for a specific index."""
    result = {"index": index_name}

    # Settings
    try:
        settings = client.indices.get_settings(index=index_name)
        idx_settings = settings.get(index_name, {}).get("settings", {}).get("index", {})
        result["settings"] = {
            "knn": idx_settings.get("knn"),
            "knn_algo_param_ef_search": idx_settings.get("knn.algo_param.ef_search"),
            "number_of_shards": idx_settings.get("number_of_shards"),
            "number_of_replicas": idx_settings.get("number_of_replicas"),
            "refresh_interval": idx_settings.get("refresh_interval"),
            "codec": idx_settings.get("codec"),
        }
    except Exception as e:
        result["settings"] = {"_error": str(e)}

    # Mappings - vector fields
    try:
        mappings = client.indices.get_mapping(index=index_name)
        idx_mapping = mappings.get(index_name, {}).get("mappings", {})
        vector_fields = _extract_vector_fields(idx_mapping.get("properties", {}))
        result["vector_fields"] = vector_fields

        # Non-vector fields summary
        all_fields = _count_fields(idx_mapping.get("properties", {}))
        result["total_fields"] = all_fields
        result["non_vector_fields"] = all_fields - len(vector_fields)
    except Exception as e:
        result["vector_fields"] = {"_error": str(e)}

    # Index stats
    try:
        stats = client.indices.stats(index=index_name)
        idx_stats = stats.get("indices", {}).get(index_name, {})
        primaries = idx_stats.get("primaries", {})
        total = idx_stats.get("total", {})

        result["stats"] = {
            "docs_count": primaries.get("docs", {}).get("count"),
            "docs_deleted": primaries.get("docs", {}).get("deleted"),
            "store_size_bytes": primaries.get("store", {}).get("size_in_bytes"),
            "store_size_gb": round(primaries.get("store", {}).get("size_in_bytes", 0) / (1024**3), 3),
            "total_store_size_gb": round(total.get("store", {}).get("size_in_bytes", 0) / (1024**3), 3),
            "indexing_total": primaries.get("indexing", {}).get("index_total"),
            "search_query_total": total.get("search", {}).get("query_total"),
            "search_query_time_ms": total.get("search", {}).get("query_time_in_millis"),
        }

        # Compute avg search latency
        query_total = total.get("search", {}).get("query_total", 0)
        query_time = total.get("search", {}).get("query_time_in_millis", 0)
        if query_total > 0:
            result["stats"]["avg_search_latency_ms"] = round(query_time / query_total, 2)
    except Exception as e:
        result["stats"] = {"_error": str(e)}

    # Memory estimate for vector fields
    if isinstance(result.get("vector_fields"), list) and result["vector_fields"]:
        doc_count = _as_int(result.get("stats", {}).get("docs_count"))

        if doc_count > 0:
            result["memory_estimates"] = []
            for vf in result["vector_fields"]:
                dim = vf.get("dimension", 0)
                m = vf.get("hnsw_m") or 16
                replicas = int(result.get("settings", {}).get("number_of_replicas", 1) or 1)

                # Determine compression ratio
                encoder_name = vf.get("encoder_name")
                encoder_params = vf.get("encoder_params") or {}
                mode = vf.get("mode")
                compression = vf.get("compression_level")
                data_type = vf.get("data_type", "float")

                bytes_per_dim = 4  # float32 default
                compression_label = "none (float32)"

                if data_type == "byte":
                    bytes_per_dim = 1
                    compression_label = "byte (4x)"
                elif encoder_name == "sq":
                    sq_type = encoder_params.get("type", "")
                    if sq_type == "fp16":
                        bytes_per_dim = 2
                        compression_label = "FP16 (2x)"
                    elif sq_type in ("int8", "byte"):
                        bytes_per_dim = 1
                        compression_label = "byte/int8 (4x)"
                elif encoder_name == "binary":
                    bits = encoder_params.get("bits", 1)
                    bytes_per_dim = bits / 8
                    compression_label = f"binary {bits}-bit ({int(32/bits)}x)"
                elif encoder_name == "pq":
                    # PQ: code_size bits per sub-vector, m sub-vectors
                    pq_m = _as_int(encoder_params.get("m"), dim // 8 if dim else 0)
                    code_size = _as_int(encoder_params.get("code_size"), 8)
                    total_bytes = (code_size / 8) * pq_m if pq_m else 0
                    bytes_per_dim = total_bytes / dim if dim > 0 else 0
                    compression_label = f"product quantization (PQ m={pq_m}, code_size={code_size})"

                if mode == "on_disk":
                    compression_label += " + disk mode"
                    if compression:
                        compression_label += f" (compression_level={compression})"

                # HNSW memory formula: 1.1 * (bytes_per_dim * d + 8 * m) * num_vectors * (replicas+1)
                mem_bytes = 1.1 * (bytes_per_dim * dim + 8 * m) * doc_count * (replicas + 1)
                mem_gb = mem_bytes / (1024**3)

                result["memory_estimates"].append({
                    "field": vf["name"],
                    "dimension": dim,
                    "doc_count": doc_count,
                    "hnsw_m": m,
                    "replicas": replicas,
                    "compression": compression_label,
                    "bytes_per_dim": bytes_per_dim,
                    "estimated_memory_gb": round(mem_gb, 2),
                    "mode": mode or "in_memory",
                })

    return result


def get_shard_analysis(client: OpenSearch, index_name: str) -> dict:
    """Analyze shard distribution for a specific index."""
    result = {"index": index_name}

    try:
        shards = client.cat.shards(index=index_name, format="json",
                                    h="index,shard,prirep,state,docs,store,node")
        result["shards"] = shards

        # Summary
        primary_shards = [s for s in shards if s.get("prirep") == "p"]
        replica_shards = [s for s in shards if s.get("prirep") == "r"]

        primary_sizes = []
        for s in primary_shards:
            store = s.get("store", "0b")
            primary_sizes.append(store)

        result["summary"] = {
            "total_shards": len(shards),
            "primary_shards": len(primary_shards),
            "replica_shards": len(replica_shards),
            "shard_states": {},
        }

        for s in shards:
            state = s.get("state", "UNKNOWN")
            result["summary"]["shard_states"][state] = result["summary"]["shard_states"].get(state, 0) + 1

        # Node distribution
        node_dist = {}
        for s in shards:
            node = s.get("node", "UNASSIGNED")
            node_dist[node] = node_dist.get(node, 0) + 1
        result["summary"]["node_distribution"] = node_dist

    except Exception as e:
        result["shards"] = {"_error": str(e)}

    return result


def _count_fields(properties: dict) -> int:
    """Count total number of fields in mappings."""
    count = 0
    for field_name, field_def in properties.items():
        count += 1
        if "properties" in field_def:
            count += _count_fields(field_def["properties"])
    return count


def generate_recommendations(cluster_overview: dict, knn_indices: list,
                              index_details: list = None) -> list:
    """Generate optimization recommendations based on analysis results."""
    recommendations = []

    # Check cluster health
    health = cluster_overview.get("cluster_health", {})
    if health.get("status") == "red":
        recommendations.append({
            "severity": "CRITICAL",
            "category": "cluster_health",
            "message": "Cluster status is RED. Some primary shards are unassigned.",
            "action": "Check unassigned shards and resolve allocation issues before optimizing vector search."
        })
    elif health.get("status") == "yellow":
        recommendations.append({
            "severity": "WARNING",
            "category": "cluster_health",
            "message": "Cluster status is YELLOW. Some replica shards are unassigned.",
            "action": "Ensure enough data nodes for replica allocation, or reduce replica count."
        })

    if health.get("unassigned_shards", 0) > 0:
        recommendations.append({
            "severity": "WARNING",
            "category": "cluster_health",
            "message": f"{health['unassigned_shards']} unassigned shards detected.",
            "action": "Run GET /_cluster/allocation/explain to diagnose allocation failures."
        })

    # Check node memory
    nodes = cluster_overview.get("nodes", [])
    for node in nodes:
        if isinstance(node, dict) and "os" in node:
            mem_pct = node["os"].get("memory_used_percent", 0)
            if mem_pct and mem_pct > 90:
                recommendations.append({
                    "severity": "WARNING",
                    "category": "memory",
                    "message": f"Node '{node.get('name')}' memory usage is {mem_pct}% (>90%).",
                    "action": "Consider scaling up instance type or adding more data nodes."
                })
            jvm_pct = node.get("jvm", {}).get("heap_used_percent", 0)
            if jvm_pct and jvm_pct > 85:
                recommendations.append({
                    "severity": "WARNING",
                    "category": "jvm",
                    "message": f"Node '{node.get('name')}' JVM heap usage is {jvm_pct}% (>85%).",
                    "action": "Check for memory pressure. Consider reducing shard count or upgrading instances."
                })

    # Check k-NN stats
    knn_stats = cluster_overview.get("knn_stats", {})
    if knn_stats.get("circuit_breaker_triggered"):
        recommendations.append({
            "severity": "CRITICAL",
            "category": "knn_memory",
            "message": "k-NN circuit breaker has been triggered. Vector graphs may be evicted from memory.",
            "action": "Increase node memory, reduce vector index size, or enable quantization/disk mode."
        })
    if knn_stats.get("cache_capacity_reached"):
        recommendations.append({
            "severity": "WARNING",
            "category": "knn_cache",
            "message": "k-NN cache capacity has been reached. Frequent evictions may degrade performance.",
            "action": "Increase knn.memory.circuit_breaker.limit or add more memory."
        })

    # Analyze each k-NN index
    if index_details:
        for detail in index_details:
            _analyze_index_config(detail, recommendations)
    elif knn_indices:
        for idx in knn_indices:
            if idx.get("vector_fields_summary"):
                for vf in idx["vector_fields_summary"]:
                    # Check engine
                    if vf.get("engine") and vf["engine"] not in ("faiss", None):
                        recommendations.append({
                            "severity": "INFO",
                            "category": "engine",
                            "index": idx["index"],
                            "field": vf["name"],
                            "message": f"Using '{vf['engine']}' engine. FAISS is recommended for better performance.",
                            "action": "Consider migrating to FAISS engine. Requires reindex."
                        })
                    # Check space_type
                    if vf.get("space_type") and vf["space_type"] == "l2":
                        recommendations.append({
                            "severity": "INFO",
                            "category": "space_type",
                            "index": idx["index"],
                            "field": vf["name"],
                            "message": f"Using 'l2' space type. 'cosine' is recommended for broader applicability.",
                            "action": "Consider using cosine similarity unless L2 distance is specifically required."
                        })

    return recommendations


def _analyze_index_config(detail: dict, recommendations: list):
    """Analyze a single index configuration and add recommendations."""
    index_name = detail.get("index", "unknown")
    settings = detail.get("settings", {})
    vector_fields = detail.get("vector_fields", [])
    stats = detail.get("stats", {})
    memory_estimates = detail.get("memory_estimates", [])

    if not isinstance(vector_fields, list):
        return

    # Check knn setting
    if str(settings.get("knn")).lower() != "true" and vector_fields:
        recommendations.append({
            "severity": "CRITICAL",
            "category": "knn_setting",
            "index": index_name,
            "message": "index.knn is not enabled but knn_vector fields exist.",
            "action": "Set index.knn=true in index settings. Requires reindex."
        })

    for vf in vector_fields:
        field_name = vf.get("name", "unknown")
        dim = vf.get("dimension", 0)
        engine = vf.get("engine")
        method = vf.get("method_name")
        space_type = vf.get("space_type")
        m = vf.get("hnsw_m")
        ef_construction = vf.get("hnsw_ef_construction")
        encoder_name = vf.get("encoder_name")
        data_type = vf.get("data_type", "float")
        mode = vf.get("mode")

        # Engine recommendation
        if engine and engine != "faiss":
            recommendations.append({
                "severity": "INFO",
                "category": "engine",
                "index": index_name,
                "field": field_name,
                "message": f"Using '{engine}' engine. FAISS is recommended for production workloads.",
                "action": "Migrate to FAISS engine for better performance and quantization support. Requires reindex."
            })

        # Space type recommendation
        if space_type == "l2":
            recommendations.append({
                "severity": "INFO",
                "category": "space_type",
                "index": index_name,
                "field": field_name,
                "message": "Using 'l2' (Euclidean distance). 'cosine' is generally recommended.",
                "action": "Use cosine similarity unless L2 is specifically required by your embedding model."
            })

        # HNSW parameter checks
        if m is not None:
            if m < 8:
                recommendations.append({
                    "severity": "WARNING",
                    "category": "hnsw_params",
                    "index": index_name,
                    "field": field_name,
                    "message": f"HNSW m={m} is too low. May result in poor recall.",
                    "action": "Increase m to 16 (recommended default). Requires reindex."
                })
            elif m > 48:
                recommendations.append({
                    "severity": "INFO",
                    "category": "hnsw_params",
                    "index": index_name,
                    "field": field_name,
                    "message": f"HNSW m={m} is very high. Increases memory usage significantly.",
                    "action": "Consider m=16 or m=32 unless extremely high recall is required."
                })

        if ef_construction is not None:
            if ef_construction < 100:
                recommendations.append({
                    "severity": "WARNING",
                    "category": "hnsw_params",
                    "index": index_name,
                    "field": field_name,
                    "message": f"ef_construction={ef_construction} is low. May result in poor index quality.",
                    "action": "Increase ef_construction to 256-512 for better recall. Requires reindex."
                })

        # Quantization recommendations for large indices
        doc_count = _as_int(stats.get("docs_count"))
        if doc_count > 10_000_000 and not encoder_name and data_type == "float" and not mode:
            recommendations.append({
                "severity": "INFO",
                "category": "quantization",
                "index": index_name,
                "field": field_name,
                "message": f"Index has {doc_count:,} docs with no compression. Consider quantization to reduce memory.",
                "action": "Use Byte quantization (4x, <5% recall loss) or FP16 (2x, <2% recall loss). Requires reindex."
            })

        # Disk mode recommendation for very large indices
        if doc_count > 50_000_000 and not mode:
            recommendations.append({
                "severity": "INFO",
                "category": "disk_mode",
                "index": index_name,
                "field": field_name,
                "message": f"Index has {doc_count:,} docs. Disk mode can reduce memory by 32x.",
                "action": "If latency tolerance is 100-200ms, consider mode: on_disk with compression. Requires reindex."
            })

    # Memory estimate warnings
    for mem in memory_estimates:
        mem_gb = mem.get("estimated_memory_gb", 0)
        if mem_gb > 100:
            recommendations.append({
                "severity": "WARNING",
                "category": "memory_sizing",
                "index": index_name,
                "field": mem.get("field"),
                "message": f"Estimated vector memory: {mem_gb:.1f} GB for field '{mem.get('field')}'.",
                "action": f"Ensure cluster has sufficient KNN-available memory. "
                          f"Recommended total node memory > {mem_gb * 1.5:.0f} GB."
            })

    # Shard count check
    num_shards = settings.get("number_of_shards")
    if num_shards:
        num_shards = int(num_shards)
        doc_count = _as_int(stats.get("docs_count"))
        if num_shards == 1 and doc_count > 5_000_000:
            recommendations.append({
                "severity": "WARNING",
                "category": "sharding",
                "index": index_name,
                "message": f"Only 1 primary shard for {doc_count:,} docs. May limit query parallelism.",
                "action": "Consider increasing primary shards to data_node_count × 1.5-2."
            })
        if num_shards > 50:
            recommendations.append({
                "severity": "WARNING",
                "category": "sharding",
                "index": index_name,
                "message": f"{num_shards} primary shards is excessive. Each shard has memory overhead.",
                "action": "Reduce shard count. Recommended: data_node_count × 1.5-2."
            })

    # Refresh interval
    refresh = settings.get("refresh_interval")
    if refresh and refresh == "1s":
        doc_count = _as_int(stats.get("docs_count"))
        if doc_count > 1_000_000:
            recommendations.append({
                "severity": "INFO",
                "category": "refresh_interval",
                "index": index_name,
                "message": "refresh_interval is 1s (default). For large vector indices, 30s is recommended.",
                "action": "Set refresh_interval to 30s to reduce indexing overhead."
            })


def main():
    parser = argparse.ArgumentParser(
        description="OpenSearch Vector Search Cluster Analyzer (READ-ONLY)")
    parser.add_argument("--url", required=True, help="OpenSearch cluster URL (e.g., https://host:9200)")
    parser.add_argument("--username", "-u", help="Username for basic auth")
    parser.add_argument("--password", "-p", help="Password for basic auth")
    parser.add_argument("--no-auth", action="store_true", help="Connect without authentication")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (only for trusted development clusters).",
    )
    parser.add_argument("--index", "-i", help="Specific index to analyze")
    parser.add_argument("--action", "-a", default="cluster-overview",
                        choices=["cluster-overview", "index-detail", "shard-analysis", "all"],
                        help="Analysis action to perform")
    parser.add_argument("--format", "-f", default="json", choices=["json", "pretty"],
                        help="Output format")

    args = parser.parse_args()

    # Validate auth
    if not args.no_auth and (not args.username or not args.password):
        print(json.dumps({
            "error": "Either provide --username and --password, or use --no-auth",
            "success": False
        }))
        sys.exit(1)

    # Connect
    try:
        client = create_client(
            url=args.url,
            username=args.username,
            password=args.password,
            no_auth=args.no_auth,
            verify_ssl=not args.insecure,
        )
        # Test connection
        client.info()
    except Exception as e:
        print(json.dumps({
            "error": f"Failed to connect to {args.url}: {str(e)}",
            "success": False
        }))
        sys.exit(1)

    output = {
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "cluster_url": args.url,
    }

    actions = [args.action] if args.action != "all" else ["cluster-overview", "index-detail", "shard-analysis"]

    if "cluster-overview" in actions:
        output["cluster_overview"] = get_cluster_overview(client)
        output["knn_indices"] = find_knn_indices(client)

    if "index-detail" in actions:
        if args.index:
            output["index_detail"] = get_index_detail(client, args.index)
        elif "knn_indices" in output:
            # Analyze all k-NN indices
            details = []
            for idx in output.get("knn_indices", []):
                if isinstance(idx, dict) and "index" in idx:
                    details.append(get_index_detail(client, idx["index"]))
            output["index_details"] = details
        else:
            output["index_detail"] = {"_note": "Specify --index or run with --action all"}

    if "shard-analysis" in actions:
        if args.index:
            output["shard_analysis"] = get_shard_analysis(client, args.index)
        elif "knn_indices" in output:
            shard_analyses = []
            for idx in output.get("knn_indices", []):
                if isinstance(idx, dict) and "index" in idx:
                    shard_analyses.append(get_shard_analysis(client, idx["index"]))
            output["shard_analyses"] = shard_analyses

    # Generate recommendations
    index_details = None
    if "index_detail" in output and isinstance(output["index_detail"], dict):
        index_details = [output["index_detail"]]
    elif "index_details" in output:
        index_details = output["index_details"]

    output["recommendations"] = generate_recommendations(
        output.get("cluster_overview", {}),
        output.get("knn_indices", []),
        index_details,
    )

    # Output
    indent = 2 if args.format == "pretty" else None
    print(json.dumps(output, indent=indent, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
