#!/usr/bin/env bash
# Build, run, and exercise the OpenSearch 3.8 Relevance X-Ray demo.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="${SCRIPT_DIR}/../../scripts/relevance_x_ray.py"
PORT="${OPENSEARCH_PORT:-19200}"
BASE_URL="http://127.0.0.1:${PORT}"
INDEX="relevance-x-ray-demo"
PIPELINE="relevance-x-ray-hybrid"
COMPOSE=(docker compose -f "${SCRIPT_DIR}/docker-compose.yml")

run_cli() {
    OPENSEARCH_HOST=127.0.0.1 \
    OPENSEARCH_PORT="$PORT" \
    OPENSEARCH_AUTH_MODE=none \
        uv run python "$CLI" "$@" --auth-mode none
}

heading() {
    printf "\n== %s ==\n" "$1"
}

case_abstention() {
    heading "No unsupported root cause"
    run_cli explain \
        --index "$INDEX" \
        --query "trainers" \
        --doc-id 1
}

case_analyzer() {
    heading "Analyzer mismatch backed by _analyze and _termvectors"
    run_cli explain \
        --index "$INDEX" \
        --query '{"query":{"match":{"stemmed_text":{"query":"running"}}}}' \
        --doc-id 8
}

case_mapping() {
    heading "Exact-match query against text-only field"
    run_cli explain \
        --index "$INDEX" \
        --query '{"query":{"term":{"brand":{"value":"trailco"}}}}' \
        --doc-id 1
}

case_scoring() {
    heading "Missing field referenced by field_value_factor"
    run_cli explain \
        --index "$INDEX" \
        --query '{"query":{"function_score":{"query":{"match":{"title":"trainers"}},"field_value_factor":{"field":"quality_score","missing":1.0}}}}' \
        --doc-id 1
}

case_doc_values() {
    heading "index:false field remains valid through doc values"
    run_cli explain \
        --index "$INDEX" \
        --query '{"query":{"function_score":{"query":{"match":{"title":"trainers"}},"field_value_factor":{"field":"popularity","missing":1.0}}}}' \
        --doc-id 1
}

case_synonym() {
    heading "Corpus-supported and rank-validated vocabulary candidate"
    run_cli suggest-synonyms \
        --index "$INDEX" \
        --query-term sneakers \
        --doc-id 1 \
        --fields title,description,stemmed_text,brand
}

case_knn() {
    heading "Controlled k-NN ef_search counterfactual with k held constant"
    run_cli explain \
        --index "$INDEX" \
        --query '{"query":{"knn":{"embedding":{"vector":[1.0,0.0,0.0],"k":1,"method_parameters":{"ef_search":1}}}}}' \
        --doc-id 1
}

case_hybrid() {
    heading "Hybrid raw legs with normalization abstention"
    run_cli explain \
        --index "$INDEX" \
        --search-pipeline "$PIPELINE" \
        --query '{"query":{"hybrid":{"queries":[{"match":{"title":"sneakers"}},{"knn":{"embedding":{"vector":[1.0,0.0,0.0],"k":5,"method_parameters":{"ef_search":20}}}}]}}}' \
        --doc-id 1
}

case_all() {
    case_abstention
    case_analyzer
    case_mapping
    case_scoring
    case_doc_values
    case_synonym
    case_knn
    case_hybrid
}

assert_contains() {
    local output="$1"
    local expected="$2"
    if [[ "$output" != *"$expected"* ]]; then
        printf "Expected output to contain: %s\n" "$expected" >&2
        printf "%s\n" "$output" >&2
        exit 1
    fi
}

smoke_test() {
    local output

    heading "Checking OpenSearch version and fixtures"
    verify

    output="$(case_abstention)"
    assert_contains "$output" "No supported root cause was established"

    output="$(case_analyzer)"
    assert_contains "$output" "analyzer_mismatch"
    assert_contains "$output" "HIGH CONFIDENCE"

    output="$(case_mapping)"
    assert_contains "$output" "missing_keyword_subfield"

    output="$(case_scoring)"
    assert_contains "$output" "unindexed_scoring_field"
    assert_contains "$output" "mapping field 'quality_score' is absent"

    output="$(case_doc_values)"
    assert_contains "$output" "Evaluated rules: unindexed_scoring_field"
    assert_contains "$output" "No supported root cause was established"

    output="$(case_synonym)"
    assert_contains "$output" "Rank-improving expansion candidates for 'sneakers'"
    assert_contains "$output" "'trainers'"

    output="$(case_knn)"
    assert_contains "$output" "holding k constant did not improve"
    assert_contains "$output" "No automatic fix is justified"

    output="$(case_hybrid)"
    assert_contains "$output" "not a normalized hybrid contribution"
    assert_contains "$output" "Hybrid imbalance was not evaluated"

    echo "All Relevance X-Ray OpenSearch 3.8 smoke cases passed."
}

verify() {
    local version count
    version="$(
        curl --fail --silent "${BASE_URL}" |
            sed -n 's/.*"number" : "\([^"]*\)".*/\1/p'
    )"
    count="$(
        curl --fail --silent "${BASE_URL}/${INDEX}/_count" |
            sed -n 's/.*"count":\([0-9][0-9]*\).*/\1/p'
    )"
    if [[ "$version" != 3.8.0 ]]; then
        echo "Expected OpenSearch 3.8.0, found '${version:-unknown}'." >&2
        exit 1
    fi
    if [[ "$count" != 10 ]]; then
        echo "Expected 10 fixtures, found '${count:-unknown}'." >&2
        exit 1
    fi
    echo "OpenSearch ${version}; ${INDEX} has ${count} documents."
}

usage() {
    cat <<'EOF'
Usage: run-demo.sh <command>

  up          Build and start OpenSearch 3.8.0; wait for seeded data
  verify      Verify version, index, and document count
  test        Run assertions for every demo scenario
  all         Print every scenario report
  abstention  Show evidence without inventing a root cause
  analyzer    Detect analyzer divergence using real tokens
  mapping     Detect text-only exact-match mapping
  scoring     Detect an absent field_value_factor field
  doc-values  Confirm index:false is valid when doc values exist
  synonym     Mine and rank-validate a vocabulary expansion candidate
  knn         Validate a higher-recall k-NN parameter sweep
  hybrid      Separate raw hybrid legs and abstain on normalization
  logs        Follow OpenSearch and loader logs
  down        Stop and remove the demo container
EOF
}

command="${1:-help}"
case "$command" in
    up)
        "${COMPOSE[@]}" up --build --detach --wait
        verify
        ;;
    verify) verify ;;
    test) smoke_test ;;
    all) case_all ;;
    abstention) case_abstention ;;
    analyzer) case_analyzer ;;
    mapping) case_mapping ;;
    scoring) case_scoring ;;
    doc-values) case_doc_values ;;
    synonym) case_synonym ;;
    knn) case_knn ;;
    hybrid) case_hybrid ;;
    logs) "${COMPOSE[@]}" logs --follow ;;
    down) "${COMPOSE[@]}" down --volumes --remove-orphans ;;
    help|-h|--help) usage ;;
    *)
        usage >&2
        exit 2
        ;;
esac
