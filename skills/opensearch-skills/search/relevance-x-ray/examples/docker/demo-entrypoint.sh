#!/usr/bin/env bash

set -euo pipefail

/usr/share/opensearch/demo/seed-demo.sh &

exec /usr/share/opensearch/opensearch-docker-entrypoint.sh "$@"
