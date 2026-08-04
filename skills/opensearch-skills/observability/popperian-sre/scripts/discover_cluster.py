#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["opensearch-py>=2.6.0"]
# ///
"""Discover which telemetry signals (logs/traces/metrics/deployments) actually
exist in the cluster before generating hypotheses that assume they do.

Usage:
    uv run python scripts/discover_cluster.py
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from opensearchpy import OpenSearch
from popperian_lib.schema_discovery import SchemaDiscovery


def main():
    parser = argparse.ArgumentParser(description="Discover OpenSearch indexes and telemetry signals")
    parser.add_argument("--host", default="localhost", help="OpenSearch host")
    parser.add_argument("--port", type=int, default=9200, help="OpenSearch port")
    parser.add_argument("--user", default=os.environ.get("OPENSEARCH_USER", "admin"), help="OpenSearch user")
    parser.add_argument("--password", default=os.environ.get("OPENSEARCH_PASSWORD", ""), help="OpenSearch password")
    parser.add_argument("--no-ssl", action="store_true", help="Disable TLS")

    args = parser.parse_args()

    client = OpenSearch(
        hosts=[{'host': args.host, 'port': args.port}],
        http_auth=(args.user, args.password),
        use_ssl=not args.no_ssl,
        verify_certs=False
    )

    discovery = SchemaDiscovery(client)

    print(json.dumps({
        "signals": discovery.get_available_signals(),
        "indexes": discovery.discover_indexes()
    }, indent=2))


if __name__ == "__main__":
    main()
