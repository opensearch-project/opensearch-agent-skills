#!/usr/bin/env python3
"""
Fetch Amazon OpenSearch Service on-demand pricing from AWS Pricing API.

SECURITY NOTE:
  - This script makes READ-ONLY HTTPS requests to the AWS Pricing API (pricing.us-east-1.amazonaws.com)
  - It does NOT modify any AWS resources
  - It only fetches publicly available pricing data
  - Requires: boto3, valid AWS credentials (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY or IAM role)
  - No local filesystem writes, no localhost connections

Usage:
  python3 get_opensearch_pricing.py --region us-east-1 [--instance-type r7g.xlarge] [--format table|json]
"""

import argparse
import json
import sys


def get_opensearch_pricing(region: str, instance_type: str = None) -> list[dict]:
    """Fetch OpenSearch on-demand instance pricing."""
    try:
        import boto3
    except ImportError:
        print(
            "Error: boto3 not installed. Run: uv add boto3 or use a Python environment with boto3.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Pricing API is only available in us-east-1 and ap-south-1
    client = boto3.client("pricing", region_name="us-east-1")

    filters = [
        {"Type": "TERM_MATCH", "Field": "ServiceCode", "Value": "AmazonES"},
        {"Type": "TERM_MATCH", "Field": "location", "Value": region_to_location(region)},
        {"Type": "TERM_MATCH", "Field": "termType", "Value": "OnDemand"},
    ]
    if instance_type:
        # OpenSearch instance types have .search suffix in pricing API
        it = instance_type if ".search" in instance_type else instance_type + ".search"
        filters.append(
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": it}
        )

    results = []
    next_token = None
    while True:
        kwargs = {"ServiceCode": "AmazonES", "Filters": filters, "MaxResults": 100}
        if next_token:
            kwargs["NextToken"] = next_token
        resp = client.get_products(**kwargs)

        for price_item_str in resp["PriceList"]:
            item = json.loads(price_item_str) if isinstance(price_item_str, str) else price_item_str
            attrs = item.get("product", {}).get("attributes", {})
            inst_type = attrs.get("instanceType", "")
            if not inst_type:
                continue

            # Extract on-demand price
            price_per_hour = None
            terms = item.get("terms", {}).get("OnDemand", {})
            for term in terms.values():
                for dim in term.get("priceDimensions", {}).values():
                    ppu = dim.get("pricePerUnit", {}).get("USD")
                    if ppu and float(ppu) > 0:
                        price_per_hour = float(ppu)
                        break

            if price_per_hour is None:
                continue

            results.append({
                "instance_type": inst_type,
                "vcpu": attrs.get("vcpu", ""),
                "memory_gib": attrs.get("memoryGib", attrs.get("memory", "")),
                "price_per_hour_usd": price_per_hour,
                "price_per_month_usd": round(price_per_hour * 730, 2),
                "storage": attrs.get("storage", ""),
                "network": attrs.get("networkPerformance", ""),
            })

        next_token = resp.get("NextToken")
        if not next_token:
            break

    # Deduplicate by instance_type, keep lowest price
    seen = {}
    for r in results:
        key = r["instance_type"]
        if key not in seen or r["price_per_hour_usd"] < seen[key]["price_per_hour_usd"]:
            seen[key] = r
    results = sorted(seen.values(), key=lambda x: x["price_per_month_usd"])
    return results


def region_to_location(region: str) -> str:
    """Map AWS region code to pricing API location name."""
    mapping = {
        "us-east-1": "US East (N. Virginia)",
        "us-east-2": "US East (Ohio)",
        "us-west-1": "US West (N. California)",
        "us-west-2": "US West (Oregon)",
        "eu-west-1": "EU (Ireland)",
        "eu-west-2": "EU (London)",
        "eu-west-3": "EU (Paris)",
        "eu-central-1": "EU (Frankfurt)",
        "eu-north-1": "EU (Stockholm)",
        "ap-northeast-1": "Asia Pacific (Tokyo)",
        "ap-northeast-2": "Asia Pacific (Seoul)",
        "ap-southeast-1": "Asia Pacific (Singapore)",
        "ap-southeast-2": "Asia Pacific (Sydney)",
        "ap-south-1": "Asia Pacific (Mumbai)",
        "sa-east-1": "South America (Sao Paulo)",
        "ca-central-1": "Canada (Central)",
        "me-south-1": "Middle East (Bahrain)",
        "af-south-1": "Africa (Cape Town)",
        "ap-east-1": "Asia Pacific (Hong Kong)",
        "ap-southeast-3": "Asia Pacific (Jakarta)",
        "eu-south-1": "EU (Milan)",
        "me-central-1": "Middle East (UAE)",
        "il-central-1": "Israel (Tel Aviv)",
    }
    return mapping.get(region, region)


def print_table(results: list[dict]):
    """Print results as a formatted table."""
    if not results:
        print("No pricing data found.")
        return
    header = f"{'Instance Type':<22} {'vCPU':<6} {'Memory':<10} {'$/hour':<10} {'$/month':<12} {'Network':<20}"
    print(header)
    print("-" * len(header))
    for r in results:
        mem = r["memory_gib"]
        if isinstance(mem, str) and "GiB" in mem:
            mem = mem.replace(" GiB", "")
        print(
            f"{r['instance_type']:<22} {r['vcpu']:<6} {mem:<10} "
            f"${r['price_per_hour_usd']:<9.4f} ${r['price_per_month_usd']:<11.2f} {r['network']:<20}"
        )


def main():
    parser = argparse.ArgumentParser(description="Fetch Amazon OpenSearch Service pricing")
    parser.add_argument("--region", default="us-east-1", help="AWS region (default: us-east-1)")
    parser.add_argument("--instance-type", default=None, help="Filter by instance type (e.g. r7g.xlarge)")
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format")
    args = parser.parse_args()

    results = get_opensearch_pricing(args.region, args.instance_type)

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(f"\nAmazon OpenSearch Service On-Demand Pricing ({args.region})\n")
        print_table(results)
        print(f"\nTotal: {len(results)} instance types")


if __name__ == "__main__":
    main()
