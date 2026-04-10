#!/bin/bash
# Start a local OpenSearch single-node cluster in Docker.
# Usage: ./start_opensearch.sh [--security]
#   --security  Enable the security plugin (HTTPS + auth). Default is disabled.
#
# Outputs JSON status to stdout.

set -euo pipefail

CONTAINER_NAME="opensearch-node"
IMAGE="opensearchproject/opensearch:latest"
PORT=9200
DISABLE_SECURITY="true"
PROTOCOL="http"
CREDS=""

if [[ "${1:-}" == "--security" ]]; then
    DISABLE_SECURITY="false"
    PROTOCOL="https"
    CREDS=" (user: admin, pass: myStrongPassword123!)"
fi

# Already running?
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "{\"status\":\"already_running\",\"endpoint\":\"${PROTOCOL}://localhost:${PORT}\"}"
    exit 0
fi

# Remove stopped container if leftover
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

echo "Starting OpenSearch..." >&2

docker run -d \
    --pull always \
    --name "$CONTAINER_NAME" \
    -p "${PORT}:9200" \
    -p 9600:9600 \
    -e "discovery.type=single-node" \
    -e "DISABLE_SECURITY_PLUGIN=${DISABLE_SECURITY}" \
    -e "OPENSEARCH_INITIAL_ADMIN_PASSWORD=myStrongPassword123!" \
    "$IMAGE" >/dev/null

# Wait for healthy
for i in $(seq 1 30); do
    if curl -sk -o /dev/null -w "%{http_code}" "${PROTOCOL}://localhost:${PORT}" 2>/dev/null | grep -qE "200|401"; then
        echo "{\"status\":\"started\",\"endpoint\":\"${PROTOCOL}://localhost:${PORT}\"${CREDS:+,\"credentials\":\"admin / myStrongPassword123!\"}}"
        exit 0
    fi
    sleep 2
done

echo "{\"status\":\"error\",\"message\":\"OpenSearch did not start within 60 seconds\"}"
exit 1
