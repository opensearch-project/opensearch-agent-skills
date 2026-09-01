#!/usr/bin/env bash
# Idempotently load deterministic Relevance X-Ray fixtures.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES_DIR="${DEMO_FIXTURES_DIR:-${SCRIPT_DIR}/fixtures}"
OPENSEARCH_URL="${OPENSEARCH_URL:-http://127.0.0.1:9200}"
INDEX="${DEMO_INDEX:-relevance-x-ray-demo}"
PIPELINE="${DEMO_PIPELINE:-relevance-x-ray-hybrid}"
WAIT_SECONDS="${DEMO_WAIT_SECONDS:-120}"

if [[ ! "$OPENSEARCH_URL" =~ ^https?://(localhost|127\.0\.0\.1|\[::1\])(:[0-9]+)?/?$ ]] \
    && [[ "${ALLOW_REMOTE_DEMO_RESET:-false}" != "true" ]]; then
    echo "Refusing to reset demo resources on non-loopback endpoint '${OPENSEARCH_URL}'." >&2
    echo "Set ALLOW_REMOTE_DEMO_RESET=true only for an intentional disposable endpoint." >&2
    exit 2
fi

request() {
    curl --fail --silent --show-error "$@"
}

echo "Waiting for OpenSearch at ${OPENSEARCH_URL}..." >&2
for _ in $(seq 1 "$WAIT_SECONDS"); do
    if request "${OPENSEARCH_URL}/_cluster/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! request "${OPENSEARCH_URL}/_cluster/health" >/dev/null 2>&1; then
    echo "OpenSearch was not ready after ${WAIT_SECONDS}s." >&2
    exit 1
fi

curl --silent --show-error -X DELETE "${OPENSEARCH_URL}/${INDEX}" >/dev/null || true
curl --silent --show-error -X DELETE \
    "${OPENSEARCH_URL}/_search/pipeline/${PIPELINE}" >/dev/null || true

request -X PUT "${OPENSEARCH_URL}/${INDEX}" \
    -H "Content-Type: application/json" \
    --data-binary "@${FIXTURES_DIR}/index.json" >/dev/null

bulk_response="$(
    request -X POST "${OPENSEARCH_URL}/_bulk" \
        -H "Content-Type: application/x-ndjson" \
        --data-binary "@${FIXTURES_DIR}/documents.ndjson"
)"
if [[ "$bulk_response" == *'"errors":true'* ]]; then
    echo "Bulk indexing reported errors: ${bulk_response}" >&2
    exit 1
fi

request -X PUT "${OPENSEARCH_URL}/_search/pipeline/${PIPELINE}" \
    -H "Content-Type: application/json" \
    --data-binary "@${FIXTURES_DIR}/search-pipeline.json" >/dev/null

request -X POST "${OPENSEARCH_URL}/${INDEX}/_refresh" >/dev/null

count="$(
    request "${OPENSEARCH_URL}/${INDEX}/_count" |
        sed -n 's/.*"count":\([0-9][0-9]*\).*/\1/p'
)"
if [[ "$count" != "10" ]]; then
    echo "Expected 10 demo documents, found '${count:-unknown}'." >&2
    exit 1
fi

echo "Relevance X-Ray demo ready: index=${INDEX}, documents=${count}, pipeline=${PIPELINE}" >&2
