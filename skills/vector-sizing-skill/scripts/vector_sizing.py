"""OpenSearch Vector Workload Sizing Calculator.

Multi-cloud sizing for k-NN/vector search workloads including:
- HNSW graph memory footprint
- Instance type recommendations across AWS, Azure, and GCP
- Shard strategy
- Storage requirements
- Monthly cost estimates

Supports: AWS OpenSearch Service, AWS EC2 (self-managed), Azure VMs, GCP VMs.
"""

import argparse
import json
import math
import sys

# --- Constants ---

HNSW_M_DEFAULT = 16  # Default M parameter (connections per node)
JVM_HEAP_GB = 31  # Fixed JVM heap for OpenSearch
OS_OVERHEAD_GB = 2  # OS and other overhead
USABLE_MEMORY_RATIO = 0.70  # 70% of remaining RAM usable for vectors
MAX_UTILIZATION = 0.75  # Never exceed 75% memory per node
DOCS_PER_SHARD = 30_000_000  # Target docs per shard
MAX_SHARD_SIZE_GB = 50  # Max recommended shard size

# Bytes per vector element by quantization type
BYTES_PER_ELEMENT = {
    "fp32": 4,
    "fp16": 2,
    "sq8": 1,
    "pq": 0.5,
}

# Engine-specific overhead multipliers
ENGINE_OVERHEAD = {
    "faiss": 1.0,
    "nmslib": 1.05,
    "lucene": 1.15,
}

# ============================================================================
# MULTI-CLOUD INSTANCE CATALOGS
# Format: (instance_type, vcpu, ram_gb, price_per_hour_usd)
# Prices are approximate on-demand rates (us-east-1 / eastus / us-central1)
# ============================================================================

INSTANCE_CATALOGS = {
    # AWS OpenSearch Service managed instances
    "aws-opensearch": [
        ("r7g.large.search", 2, 16, 0.251),
        ("r7g.xlarge.search", 4, 32, 0.502),
        ("r7g.2xlarge.search", 8, 64, 1.004),
        ("r7g.4xlarge.search", 16, 128, 2.008),
        ("r7g.8xlarge.search", 32, 256, 4.016),
        ("r7g.12xlarge.search", 48, 384, 6.024),
        ("r7g.16xlarge.search", 64, 512, 8.032),
        ("r8g.large.search", 2, 16, 0.266),
        ("r8g.xlarge.search", 4, 32, 0.532),
        ("r8g.2xlarge.search", 8, 64, 1.064),
        ("r8g.4xlarge.search", 16, 128, 2.128),
        ("r8g.8xlarge.search", 32, 256, 4.256),
        ("r8g.12xlarge.search", 48, 384, 6.384),
        ("r8g.16xlarge.search", 64, 512, 8.512),
        ("r8g.24xlarge.search", 96, 768, 12.768),
        ("or1.2xlarge.search", 8, 64, 1.165),
        ("or1.4xlarge.search", 16, 128, 2.330),
        ("or1.8xlarge.search", 32, 256, 4.660),
        ("or1.12xlarge.search", 48, 384, 6.990),
        ("or1.16xlarge.search", 64, 512, 9.320),
    ],
    # AWS EC2 instances (self-managed OpenSearch)
    "aws-ec2": [
        ("r7g.2xlarge", 8, 64, 0.714),
        ("r7g.4xlarge", 16, 128, 1.428),
        ("r7g.8xlarge", 32, 256, 2.856),
        ("r7g.12xlarge", 48, 384, 4.284),
        ("r7g.16xlarge", 64, 512, 5.712),
        ("r8g.2xlarge", 8, 64, 0.756),
        ("r8g.4xlarge", 16, 128, 1.512),
        ("r8g.8xlarge", 32, 256, 3.024),
        ("r8g.12xlarge", 48, 384, 4.536),
        ("r8g.16xlarge", 64, 512, 6.048),
        ("r8g.24xlarge", 96, 768, 9.072),
        ("r7i.2xlarge", 8, 64, 0.756),
        ("r7i.4xlarge", 16, 128, 1.512),
        ("r7i.8xlarge", 32, 256, 3.024),
        ("r7i.12xlarge", 48, 384, 4.536),
        ("r7i.16xlarge", 64, 512, 6.048),
        ("r7i.24xlarge", 96, 768, 9.072),
        ("x2idn.16xlarge", 64, 1024, 8.004),
        ("x2idn.24xlarge", 96, 1536, 12.006),
    ],
    # Azure VMs (self-managed OpenSearch)
    "azure": [
        ("Standard_E8s_v5", 8, 64, 0.604),
        ("Standard_E16s_v5", 16, 128, 1.208),
        ("Standard_E32s_v5", 32, 256, 2.416),
        ("Standard_E48s_v5", 48, 384, 3.624),
        ("Standard_E64s_v5", 64, 512, 4.832),
        ("Standard_E96s_v5", 96, 672, 7.248),
        ("Standard_E8as_v5", 8, 64, 0.544),
        ("Standard_E16as_v5", 16, 128, 1.088),
        ("Standard_E32as_v5", 32, 256, 2.176),
        ("Standard_E48as_v5", 48, 384, 3.264),
        ("Standard_E64as_v5", 64, 512, 4.352),
        ("Standard_E96as_v5", 96, 672, 6.528),
        ("Standard_M128s_v2", 128, 2048, 26.688),
        ("Standard_E104ids_v5", 104, 672, 9.566),
    ],
    # GCP VMs (self-managed OpenSearch)
    "gcp": [
        ("n2-highmem-8", 8, 64, 0.568),
        ("n2-highmem-16", 16, 128, 1.136),
        ("n2-highmem-32", 32, 256, 2.272),
        ("n2-highmem-48", 48, 384, 3.408),
        ("n2-highmem-64", 64, 512, 4.544),
        ("n2-highmem-80", 80, 640, 5.680),
        ("n2-highmem-96", 96, 768, 6.816),
        ("n2d-highmem-8", 8, 64, 0.496),
        ("n2d-highmem-16", 16, 128, 0.992),
        ("n2d-highmem-32", 32, 256, 1.984),
        ("n2d-highmem-48", 48, 384, 2.976),
        ("n2d-highmem-64", 64, 512, 3.968),
        ("n2d-highmem-96", 96, 768, 5.952),
        ("m2-megamem-416", 416, 5888, 51.53),
        ("m2-ultramem-208", 208, 5888, 42.186),
    ],
}

# All clouds combined for "all" option
INSTANCE_CATALOGS["all"] = []
for cloud, instances in INSTANCE_CATALOGS.items():
    if cloud != "all":
        for itype, vcpu, ram, price in instances:
            INSTANCE_CATALOGS["all"].append((f"{itype}", vcpu, ram, price))

# Cloud-specific storage info
STORAGE_INFO = {
    "aws-opensearch": {"type": "EBS gp3", "note": "Included in managed service"},
    "aws-ec2": {"type": "EBS gp3", "note": "3000 IOPS base, up to 16000"},
    "azure": {"type": "Premium SSD v2", "note": "Configurable IOPS/throughput"},
    "gcp": {"type": "pd-ssd", "note": "Persistent SSD, scales with size"},
}

# Cloud-specific master node recommendations
MASTER_NODES = {
    "aws-opensearch": {"type": "r7g.large.search", "count": 3},
    "aws-ec2": {"type": "r7g.large", "count": 3},
    "azure": {"type": "Standard_E2s_v5", "count": 3},
    "gcp": {"type": "n2-highmem-2", "count": 3},
}

CLOUD_LABELS = {
    "aws-opensearch": "AWS OpenSearch Service (Managed)",
    "aws-ec2": "AWS EC2 (Self-Managed)",
    "azure": "Azure VMs (Self-Managed)",
    "gcp": "GCP VMs (Self-Managed)",
    "all": "All Clouds",
}


def usable_memory_gb(instance_ram_gb: float) -> float:
    """Calculate usable memory for vectors after JVM heap and OS overhead."""
    remaining = instance_ram_gb - JVM_HEAP_GB - OS_OVERHEAD_GB
    return max(0, remaining * USABLE_MEMORY_RATIO)


def calculate_vector_memory_gb(
    num_vectors: int,
    dimensions: int,
    quantization: str = "fp32",
    engine: str = "faiss",
    m: int = HNSW_M_DEFAULT,
) -> float:
    """Calculate total memory needed for vector HNSW graph (one replica set).

    Formula: 1.1 * (bytes_per_element * dimension + 8 * m) * num_vectors
    Source: OpenSearch documentation
    """
    bytes_per_elem = BYTES_PER_ELEMENT.get(quantization.lower(), 4)
    engine_mult = ENGINE_OVERHEAD.get(engine.lower(), 1.0)

    memory_bytes = 1.1 * (bytes_per_elem * dimensions + 8 * m) * num_vectors * engine_mult
    return memory_bytes / (1024 ** 3)


def calculate_storage_gb(
    num_vectors: int,
    dimensions: int,
    doc_size_bytes: int = 1024,
    quantization: str = "fp32",
    source_data_gb: float = 0,
) -> float:
    """Calculate total storage needed (primary, one replica set).

    If source_data_gb is provided, it replaces the per-doc estimate for
    non-vector storage (text fields, metadata, etc.).
    """
    bytes_per_elem = BYTES_PER_ELEMENT.get(quantization.lower(), 4)
    vector_storage = num_vectors * dimensions * bytes_per_elem
    if source_data_gb > 0:
        doc_storage = source_data_gb * (1024**3)
    else:
        doc_storage = num_vectors * doc_size_bytes
    return (vector_storage + doc_storage) / (1024**3)


def recommend_instances(
    total_memory_gb: float,
    num_replicas: int = 1,
    multi_az: int = 2,
    qps: int = 0,
    cloud: str = "aws-ec2",
) -> list:
    """Recommend instance configurations at different tiers."""
    total_with_replicas = total_memory_gb * (1 + num_replicas)

    catalog = INSTANCE_CATALOGS.get(cloud, INSTANCE_CATALOGS["aws-ec2"])

    recommendations = []

    viable = [
        (itype, vcpu, ram, price)
        for itype, vcpu, ram, price in catalog
        if usable_memory_gb(ram) >= 20
    ]

    viable.sort(key=lambda x: x[2], reverse=True)

    seen_sizes = set()
    for itype, vcpu, ram, price in viable:
        usable = usable_memory_gb(ram)
        effective_usable = usable * MAX_UTILIZATION
        nodes_needed = math.ceil(total_with_replicas / effective_usable)

        if multi_az > 0 and nodes_needed % multi_az != 0:
            nodes_needed += multi_az - (nodes_needed % multi_az)

        nodes_needed = max(nodes_needed, multi_az if multi_az > 0 else 2)

        if qps > 0:
            min_vcpus = math.ceil(qps / 500)
            min_nodes_for_qps = math.ceil(min_vcpus / vcpu)
            if multi_az > 0 and min_nodes_for_qps % multi_az != 0:
                min_nodes_for_qps += multi_az - (min_nodes_for_qps % multi_az)
            nodes_needed = max(nodes_needed, min_nodes_for_qps)

        monthly_cost = nodes_needed * price * 730

        size_key = f"{ram}-{vcpu}"
        if size_key in seen_sizes:
            continue
        seen_sizes.add(size_key)

        tier = "performance"
        if nodes_needed > 12:
            tier = "economy"
        elif nodes_needed <= 6:
            tier = "performance"
        else:
            tier = "balanced"

        recommendations.append({
            "instance_type": itype,
            "cloud": cloud,
            "vcpu": vcpu,
            "ram_gb": ram,
            "usable_memory_gb": round(effective_usable, 1),
            "nodes": nodes_needed,
            "total_vcpu": nodes_needed * vcpu,
            "monthly_compute_usd": round(monthly_cost),
            "tier": tier,
        })

    recommendations.sort(key=lambda x: x["monthly_compute_usd"])
    return recommendations[:5]


def calculate_shards(num_vectors: int, storage_per_replica_gb: float) -> dict:
    """Calculate recommended shard configuration."""
    by_doc_count = math.ceil(num_vectors / DOCS_PER_SHARD)
    by_size = math.ceil(storage_per_replica_gb / MAX_SHARD_SIZE_GB)
    primary_shards = max(by_doc_count, by_size, 1)

    return {
        "primary_shards": primary_shards,
        "reasoning": {
            "by_doc_count": f"{num_vectors:,} docs / {DOCS_PER_SHARD:,} per shard = {by_doc_count}",
            "by_shard_size": f"{storage_per_replica_gb:.1f} GB / {MAX_SHARD_SIZE_GB} GB max = {by_size}",
            "chosen": max(by_doc_count, by_size),
        },
    }


def format_bytes(gb: float) -> str:
    """Format GB value to human-readable string."""
    if gb >= 1024:
        return f"{gb / 1024:.2f} TB"
    return f"{gb:.1f} GB"


def run_calculate(args):
    """Main calculation entry point."""
    vector_memory_gb = calculate_vector_memory_gb(
        num_vectors=args.vectors,
        dimensions=args.dimensions,
        quantization=args.quantization,
        engine=args.engine,
    )

    source_data_gb = getattr(args, 'source_data_gb', 0) or 0
    storage_primary_gb = calculate_storage_gb(
        num_vectors=args.vectors,
        dimensions=args.dimensions,
        doc_size_bytes=args.doc_size_bytes,
        quantization=args.quantization,
        source_data_gb=source_data_gb,
    )
    storage_total_gb = storage_primary_gb * (1 + args.replicas)

    # Get recommendations for specified cloud(s)
    clouds = args.cloud if isinstance(args.cloud, list) else [args.cloud]
    all_recommendations = {}
    for cloud in clouds:
        recs = recommend_instances(
            total_memory_gb=vector_memory_gb,
            num_replicas=args.replicas,
            multi_az=args.multi_az,
            qps=args.qps,
            cloud=cloud,
        )
        all_recommendations[cloud] = recs

    shard_config = calculate_shards(args.vectors, storage_primary_gb)

    result = {
        "inputs": {
            "vectors": args.vectors,
            "dimensions": args.dimensions,
            "engine": args.engine,
            "quantization": args.quantization,
            "replicas": args.replicas,
            "doc_size_bytes": args.doc_size_bytes,
            "source_data_gb": source_data_gb,
            "qps": args.qps,
            "multi_az": args.multi_az,
            "cloud": clouds,
        },
        "memory": {
            "vector_memory_per_replica_set": format_bytes(vector_memory_gb),
            "vector_memory_per_replica_set_gb": round(vector_memory_gb, 2),
            "total_with_replicas": format_bytes(vector_memory_gb * (1 + args.replicas)),
            "total_with_replicas_gb": round(vector_memory_gb * (1 + args.replicas), 2),
            "formula": f"1.1 x ({BYTES_PER_ELEMENT[args.quantization]} x {args.dimensions} + 8 x {HNSW_M_DEFAULT}) x {args.vectors:,}",
        },
        "storage": {
            "primary": format_bytes(storage_primary_gb),
            "total_with_replicas": format_bytes(storage_total_gb),
        },
        "shards": shard_config,
        "recommendations": all_recommendations,
        "quantization_savings": {},
    }

    # Add storage details per cloud
    for cloud in clouds:
        recs = all_recommendations.get(cloud, [])
        if recs:
            top = recs[0]
            ebs_per_node = math.ceil(storage_total_gb / top["nodes"] * 1.2)
            storage_type = STORAGE_INFO.get(cloud, {}).get("type", "SSD")
            result["storage"][f"disk_per_node_{cloud}"] = {
                "size_gb": ebs_per_node,
                "type": storage_type,
            }

    # Add master node info
    result["master_nodes"] = {}
    for cloud in clouds:
        mn = MASTER_NODES.get(cloud, MASTER_NODES["aws-ec2"])
        result["master_nodes"][cloud] = mn

    if args.quantization == "fp32":
        fp16_mem = calculate_vector_memory_gb(args.vectors, args.dimensions, "fp16", args.engine)
        sq8_mem = calculate_vector_memory_gb(args.vectors, args.dimensions, "sq8", args.engine)
        result["quantization_savings"] = {
            "current_fp32": format_bytes(vector_memory_gb),
            "fp16_half_precision": {
                "memory": format_bytes(fp16_mem),
                "savings_pct": "50%",
                "recall_impact": "~99% of FP32 recall",
            },
            "sq8_scalar_quantization": {
                "memory": format_bytes(sq8_mem),
                "savings_pct": "75%",
                "recall_impact": "~95-98% of FP32 recall",
            },
            "note": "Quantization requires FAISS engine. Test recall on your dataset before committing.",
        }

    if args.output == "json":
        print(json.dumps(result, indent=2))
    else:
        print_human_readable(result, clouds)


def print_human_readable(result: dict, clouds: list):
    """Print results in a human-readable table format."""
    inputs = result["inputs"]
    mem = result["memory"]
    stor = result["storage"]
    shards = result["shards"]

    print("=" * 78)
    print("  OPENSEARCH VECTOR SIZING ESTIMATE (Multi-Cloud)")
    print("=" * 78)
    print()
    print("  INPUTS")
    print(f"  Vectors:        {inputs['vectors']:,}")
    print(f"  Dimensions:     {inputs['dimensions']}")
    print(f"  Engine:         {inputs['engine']}")
    print(f"  Quantization:   {inputs['quantization'].upper()}")
    print(f"  Replicas:       {inputs['replicas']}")
    print(f"  Multi-AZ:       {inputs['multi_az']}-AZ")
    if inputs.get("source_data_gb", 0) > 0:
        print(f"  Source data:    {inputs['source_data_gb']} GB")
    print(f"  Clouds:         {', '.join(CLOUD_LABELS.get(c, c) for c in clouds)}")
    if inputs["qps"] > 0:
        print(f"  Target QPS:     {inputs['qps']:,}")
    print()
    print("-" * 78)
    print()
    print("  MEMORY REQUIREMENT (HNSW graph must fit in RAM)")
    print(f"  Formula: {mem['formula']}")
    print(f"  Per replica set:       {mem['vector_memory_per_replica_set']}")
    print(f"  Total (with replicas): {mem['total_with_replicas']}")
    print()
    print("-" * 78)
    print()
    print("  STORAGE")
    print(f"  Primary:               {stor['primary']}")
    print(f"  Total (with replicas): {stor['total_with_replicas']}")
    print()
    print("-" * 78)
    print()
    print("  SHARD STRATEGY")
    print(f"  Primary shards: {shards['primary_shards']}")
    print(f"    By doc count:  {shards['reasoning']['by_doc_count']}")
    print(f"    By shard size: {shards['reasoning']['by_shard_size']}")
    print()

    for cloud in clouds:
        recs = result["recommendations"].get(cloud, [])
        label = CLOUD_LABELS.get(cloud, cloud)
        print("-" * 78)
        print()
        print(f"  RECOMMENDATIONS: {label}")
        print()
        if not recs:
            print("  No viable configuration found.")
            print()
            continue

        print(f"  {'Tier':<12} {'Instance':<24} {'Nodes':<7} {'RAM':<8} {'Usable':<9} {'Monthly':<10}")
        print(f"  {'-'*12} {'-'*24} {'-'*7} {'-'*8} {'-'*9} {'-'*10}")
        for rec in recs:
            print(
                f"  {rec['tier']:<12} {rec['instance_type']:<24} {rec['nodes']:<7} "
                f"{rec['ram_gb']} GB{'':<2} {rec['usable_memory_gb']:.0f} GB{'':<3} "
                f"${rec['monthly_compute_usd']:,}"
            )
        print()

        mn = result["master_nodes"].get(cloud, {})
        if mn:
            print(f"  Master nodes: {mn['count']} x {mn['type']}")

        disk_key = f"disk_per_node_{cloud}"
        if disk_key in stor:
            disk = stor[disk_key]
            print(f"  Disk per node:  {disk['size_gb']} GB ({disk['type']})")
        print()

    if result.get("quantization_savings"):
        qs = result["quantization_savings"]
        print("-" * 78)
        print()
        print("  QUANTIZATION OPTIONS (reduce memory if recall trade-off acceptable)")
        print(f"  Current (FP32):  {qs['current_fp32']}")
        if "fp16_half_precision" in qs:
            fp16 = qs["fp16_half_precision"]
            print(f"  FP16:            {fp16['memory']} (saves {fp16['savings_pct']}, {fp16['recall_impact']})")
        if "sq8_scalar_quantization" in qs:
            sq8 = qs["sq8_scalar_quantization"]
            print(f"  SQ8:             {sq8['memory']} (saves {sq8['savings_pct']}, {sq8['recall_impact']})")
        print(f"  Note: {qs.get('note', '')}")
        print()

    print("=" * 78)


def run_compare(args):
    """Compare sizing across different quantization levels."""
    configs = ["fp32", "fp16", "sq8", "pq"]
    clouds = args.cloud if isinstance(args.cloud, list) else [args.cloud]

    for cloud in clouds:
        label = CLOUD_LABELS.get(cloud, cloud)
        results = []

        for quant in configs:
            mem = calculate_vector_memory_gb(args.vectors, args.dimensions, quant, args.engine)
            recs = recommend_instances(mem, args.replicas, args.multi_az, args.qps, cloud)
            top = recs[0] if recs else None
            results.append({
                "quantization": quant.upper(),
                "memory_gb": round(mem, 1),
                "memory_with_replicas_gb": round(mem * (1 + args.replicas), 1),
                "top_recommendation": top,
            })

        if args.output == "json":
            print(json.dumps({"cloud": cloud, "comparisons": results}, indent=2))
        else:
            print()
            print(f"  QUANTIZATION COMPARISON — {label}")
            print(f"  {args.vectors:,} vectors x {args.dimensions} dims ({args.engine})")
            print()
            print(f"  {'Quant':<8} {'Mem/Replica':<14} {'Total Mem':<14} {'Instance':<24} {'Nodes':<7} {'Monthly':<10}")
            print(f"  {'-'*8} {'-'*14} {'-'*14} {'-'*24} {'-'*7} {'-'*10}")
            for r in results:
                top = r["top_recommendation"]
                if top:
                    print(
                        f"  {r['quantization']:<8} {format_bytes(r['memory_gb']):<14} "
                        f"{format_bytes(r['memory_with_replicas_gb']):<14} "
                        f"{top['instance_type']:<24} {top['nodes']:<7} ${top['monthly_compute_usd']:,}"
                    )
                else:
                    print(f"  {r['quantization']:<8} {format_bytes(r['memory_gb']):<14} — no viable config —")
            print()


def run_instance_info(args):
    """Show available instance types and their specs."""
    clouds = args.cloud if isinstance(args.cloud, list) else [args.cloud]

    for cloud in clouds:
        catalog = INSTANCE_CATALOGS.get(cloud, [])
        label = CLOUD_LABELS.get(cloud, cloud)

        print()
        print(f"  {label}")
        print(f"  {'Instance':<24} {'vCPU':<6} {'RAM':<10} {'Usable*':<10} {'$/hr':<9} {'$/month':<10}")
        print(f"  {'-'*24} {'-'*6} {'-'*10} {'-'*10} {'-'*9} {'-'*10}")
        for itype, vcpu, ram, price in catalog:
            usable = usable_memory_gb(ram) * MAX_UTILIZATION
            if usable < 15:
                continue
            monthly = price * 730
            print(f"  {itype:<24} {vcpu:<6} {ram} GB{'':<4} {usable:.0f} GB{'':<5} ${price:<8.3f} ${monthly:,.0f}")
        print()

    print("  * Usable = (RAM - 31 GB JVM - 2 GB OS) x 70% x 75% max utilization")
    print("  Prices are approximate on-demand. Verify current pricing for your region.")
    print()


def run_cross_cloud(args):
    """Compare the best option across all clouds."""
    vector_memory_gb = calculate_vector_memory_gb(
        args.vectors, args.dimensions, args.quantization, args.engine
    )

    print()
    print(f"  CROSS-CLOUD COMPARISON: {args.vectors:,} vectors x {args.dimensions} dims")
    print(f"  Engine: {args.engine} | Quantization: {args.quantization.upper()} | Replicas: {args.replicas}")
    print(f"  Memory needed: {format_bytes(vector_memory_gb)} per replica set")
    print()
    print(f"  {'Cloud':<32} {'Instance':<24} {'Nodes':<7} {'Monthly':<12} {'Notes'}")
    print(f"  {'-'*32} {'-'*24} {'-'*7} {'-'*12} {'-'*20}")

    for cloud in ["aws-opensearch", "aws-ec2", "azure", "gcp"]:
        recs = recommend_instances(
            vector_memory_gb, args.replicas, args.multi_az, args.qps, cloud
        )
        label = CLOUD_LABELS.get(cloud, cloud)
        if recs:
            top = recs[0]
            note = "Managed" if "opensearch" in cloud else "Self-managed"
            print(
                f"  {label:<32} {top['instance_type']:<24} {top['nodes']:<7} "
                f"${top['monthly_compute_usd']:,}{'':<6} {note}"
            )
        else:
            print(f"  {label:<32} {'— no viable config —':<24}")

    print()
    print("  Note: Managed service (AWS OpenSearch) includes patching, backups, monitoring.")
    print("  Self-managed is cheaper but requires operational overhead.")
    print()


def parse_cloud_arg(value: str) -> list:
    """Parse comma-separated cloud argument into a list."""
    clouds = [c.strip() for c in value.split(",")]
    valid = set(INSTANCE_CATALOGS.keys())
    for c in clouds:
        if c not in valid:
            raise argparse.ArgumentTypeError(
                f"Unknown cloud '{c}'. Valid: {', '.join(sorted(valid - {'all'}))}"
            )
    return clouds


def main():
    parser = argparse.ArgumentParser(
        description="OpenSearch Vector Workload Sizing Calculator (Multi-Cloud)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Size for AWS OpenSearch Service
  python vector_sizing.py calculate --vectors 100000000 --dimensions 1536 --cloud aws-opensearch

  # Compare across all clouds
  python vector_sizing.py cross-cloud --vectors 294000000 --dimensions 1536

  # Size for self-managed on GCP
  python vector_sizing.py calculate --vectors 50000000 --dimensions 768 --cloud gcp

  # Compare AWS EC2 vs Azure
  python vector_sizing.py calculate --vectors 100000000 --dimensions 1536 --cloud aws-ec2,azure

  # Quantization comparison on Azure
  python vector_sizing.py compare --vectors 294000000 --dimensions 1536 --cloud azure

  # Show GCP instance catalog
  python vector_sizing.py instances --cloud gcp

Available clouds: aws-opensearch, aws-ec2, azure, gcp
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Calculate command
    calc_parser = subparsers.add_parser("calculate", help="Calculate cluster sizing")
    calc_parser.add_argument("--vectors", type=int, required=True, help="Number of vectors")
    calc_parser.add_argument("--dimensions", type=int, required=True, help="Vector dimensions")
    calc_parser.add_argument("--engine", choices=["faiss", "nmslib", "lucene"], default="faiss")
    calc_parser.add_argument("--quantization", choices=["fp32", "fp16", "sq8", "pq"], default="fp32")
    calc_parser.add_argument("--replicas", type=int, default=1)
    calc_parser.add_argument("--doc-size-bytes", type=int, default=1024,
                             help="Per-doc non-vector size in bytes (ignored if --source-data-gb set)")
    calc_parser.add_argument("--source-data-gb", type=float, default=0,
                             help="Total source data size in GB (text, metadata). Overrides --doc-size-bytes")
    calc_parser.add_argument("--qps", type=int, default=0, help="Target queries per second")
    calc_parser.add_argument("--multi-az", type=int, choices=[0, 2, 3], default=2)
    calc_parser.add_argument("--cloud", type=parse_cloud_arg, default=["aws-ec2"],
                             help="Cloud(s): aws-opensearch, aws-ec2, azure, gcp (comma-separated)")
    calc_parser.add_argument("--output", choices=["human", "json"], default="human")

    # Compare command
    comp_parser = subparsers.add_parser("compare", help="Compare quantization options")
    comp_parser.add_argument("--vectors", type=int, required=True)
    comp_parser.add_argument("--dimensions", type=int, required=True)
    comp_parser.add_argument("--engine", choices=["faiss", "nmslib", "lucene"], default="faiss")
    comp_parser.add_argument("--replicas", type=int, default=1)
    comp_parser.add_argument("--multi-az", type=int, choices=[0, 2, 3], default=2)
    comp_parser.add_argument("--qps", type=int, default=0)
    comp_parser.add_argument("--cloud", type=parse_cloud_arg, default=["aws-ec2"],
                             help="Cloud(s): aws-opensearch, aws-ec2, azure, gcp")
    comp_parser.add_argument("--output", choices=["human", "json"], default="human")

    # Cross-cloud command
    cross_parser = subparsers.add_parser("cross-cloud", help="Compare best option across all clouds")
    cross_parser.add_argument("--vectors", type=int, required=True)
    cross_parser.add_argument("--dimensions", type=int, required=True)
    cross_parser.add_argument("--engine", choices=["faiss", "nmslib", "lucene"], default="faiss")
    cross_parser.add_argument("--quantization", choices=["fp32", "fp16", "sq8", "pq"], default="fp32")
    cross_parser.add_argument("--replicas", type=int, default=1)
    cross_parser.add_argument("--multi-az", type=int, choices=[0, 2, 3], default=2)
    cross_parser.add_argument("--qps", type=int, default=0)
    cross_parser.add_argument("--output", choices=["human", "json"], default="human")

    # Instances command
    inst_parser = subparsers.add_parser("instances", help="Show available instance types")
    inst_parser.add_argument("--cloud", type=parse_cloud_arg, default=["aws-ec2"],
                             help="Cloud(s): aws-opensearch, aws-ec2, azure, gcp")

    args = parser.parse_args()

    if args.command == "calculate":
        run_calculate(args)
    elif args.command == "compare":
        run_compare(args)
    elif args.command == "cross-cloud":
        run_cross_cloud(args)
    elif args.command == "instances":
        run_instance_info(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
