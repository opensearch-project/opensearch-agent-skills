#!/usr/bin/env python3
"""Execute a validated, read-only PPL query and print the (context-bounded) result.

Credentials are read only from OPENSEARCH_USER / OPENSEARCH_PASSWORD -- not
accepted as CLI arguments, since a --password flag would put the credential
in process listings (ps, /proc) visible to other users on the host.

Usage:
    OPENSEARCH_USER=admin OPENSEARCH_PASSWORD=... \
        uv run python scripts/run_ppl.py "source=traces-* | stats avg(duration_ms) by service"
"""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from opensearchpy import OpenSearch
from popperian_lib.query_executor import QueryExecutor


def main():
    parser = argparse.ArgumentParser(description="Run a validated, read-only PPL query")
    parser.add_argument("query", help="PPL query to execute")
    parser.add_argument("--host", default="localhost", help="OpenSearch host")
    parser.add_argument("--port", type=int, default=9200, help="OpenSearch port")
    parser.add_argument("--no-ssl", action="store_true", help="Disable TLS")
    parser.add_argument(
        "--insecure", action="store_true",
        help=(
            "Skip TLS certificate verification (e.g. for a local cluster's self-signed cert). "
            "Off by default -- credentials and query results otherwise traverse an unverified "
            "connection, which is a MITM exposure on anything but a fully trusted local network."
        )
    )
    parser.add_argument(
        "--max-rows-in-context", type=int, default=QueryExecutor.DEFAULT_MAX_ROWS_IN_CONTEXT,
        help=(
            "Cap on datarows printed to stdout (which the agent reads into its context), "
            f"independent of the query's own row cap. Default {QueryExecutor.DEFAULT_MAX_ROWS_IN_CONTEXT}. "
            "Pass 0 to disable and print every row."
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

    executor = QueryExecutor(client)
    max_rows_in_context = None if args.max_rows_in_context == 0 else args.max_rows_in_context
    result = executor.execute_ppl(args.query, max_rows_in_context=max_rows_in_context)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
