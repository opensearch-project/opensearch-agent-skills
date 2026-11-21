#!/usr/bin/env python3
"""Discover which telemetry signals (logs/traces/metrics/deployments) actually
exist in the cluster before generating hypotheses that assume they do.

Credentials are read only from OPENSEARCH_USER / OPENSEARCH_PASSWORD -- not
accepted as CLI arguments, since a --password flag would put the credential
in process listings (ps, /proc) visible to other users on the host.

Usage:
    OPENSEARCH_USER=admin OPENSEARCH_PASSWORD=... uv run python scripts/discover_cluster.py
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
    parser.add_argument("--no-ssl", action="store_true", help="Disable TLS")
    parser.add_argument(
        "--insecure", action="store_true",
        help=(
            "Skip TLS certificate verification (e.g. for a local cluster's self-signed cert). "
            "Off by default -- credentials otherwise traverse an unverified connection, which "
            "is a MITM exposure on anything but a fully trusted local network."
        )
    )

    args = parser.parse_args()

    password = os.environ.get("OPENSEARCH_PASSWORD")
    if not password:
        parser.error(
            "OPENSEARCH_PASSWORD is not set. Refusing to connect with an empty "
            "credential -- a misconfigured cluster that accepts empty-password "
            "auth would otherwise succeed silently."
        )

    client = OpenSearch(
        hosts=[{'host': args.host, 'port': args.port}],
        http_auth=(os.environ.get("OPENSEARCH_USER", "admin"), password),
        use_ssl=not args.no_ssl,
        verify_certs=not args.insecure
    )

    discovery = SchemaDiscovery(client)

    print(json.dumps({
        "signals": discovery.get_available_signals(),
        "indexes": discovery.discover_indexes()
    }, indent=2))


if __name__ == "__main__":
    main()
