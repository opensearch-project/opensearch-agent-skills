#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["opensearch-py>=2.6.0", "pydantic>=2.0.0"]
# ///
"""Execute a validated, read-only PPL query and print the (context-bounded) result.

Usage:
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
    parser.add_argument("--user", default=os.environ.get("OPENSEARCH_USER", "admin"), help="OpenSearch user")
    parser.add_argument("--password", default=os.environ.get("OPENSEARCH_PASSWORD", ""), help="OpenSearch password")
    parser.add_argument("--no-ssl", action="store_true", help="Disable TLS")
    parser.add_argument(
        "--max-rows-in-context", type=int, default=QueryExecutor.DEFAULT_MAX_ROWS_IN_CONTEXT,
        help=(
            "Cap on datarows printed to stdout (which the agent reads into its context), "
            f"independent of the query's own row cap. Default {QueryExecutor.DEFAULT_MAX_ROWS_IN_CONTEXT}. "
            "Pass 0 to disable and print every row."
        )
    )

    args = parser.parse_args()

    client = OpenSearch(
        hosts=[{'host': args.host, 'port': args.port}],
        http_auth=(args.user, args.password),
        use_ssl=not args.no_ssl,
        verify_certs=False
    )

    executor = QueryExecutor(client)
    max_rows_in_context = None if args.max_rows_in_context == 0 else args.max_rows_in_context
    result = executor.execute_ppl(args.query, max_rows_in_context=max_rows_in_context)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
