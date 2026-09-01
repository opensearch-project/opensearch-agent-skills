#!/bin/bash
# Load the deterministic Relevance X-Ray fixtures into an existing cluster.
#
# Usage:
#   bash examples/demo_index_setup.sh [host] [port]
#
# For the pinned OpenSearch 3.8 environment, prefer:
#   bash docker/run-demo.sh up

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${1:-127.0.0.1}"
PORT="${2:-9200}"

if [[ ! "$HOST" =~ ^([A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])$ ]]; then
    echo "Invalid OpenSearch host '${HOST}'." >&2
    exit 2
fi
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || ((PORT < 1 || PORT > 65535)); then
    echo "Invalid OpenSearch port '${PORT}'." >&2
    exit 2
fi

OPENSEARCH_URL="http://${HOST}:${PORT}" \
    "${SCRIPT_DIR}/seed-demo.sh"
