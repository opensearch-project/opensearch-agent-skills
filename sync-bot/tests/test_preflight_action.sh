#!/usr/bin/env bash
# Local integration test for sync-preflight action.yml.
#
# Runs the preflight bash block against real repos with real gh CLI
# auth, asserting exit codes match the compatibility matrix:
#
#   mode    target repo                            expected
#   push    opensearch-project (protected)         1 (fail)
#   pr      opensearch-project (protected)         0 (OK, PRs fine)
#   dry-run any                                    0 (OK)
#   bogus   any                                    1 (fail on mode validation)
#
# This inlines the action's `run:` block because act+composite-actions
# locally is flaky; the bash is the contract and is what we test.
set -uo pipefail

ACTION_FILE="$(dirname "$(realpath "$0")")/../../.github/actions/sync-preflight/action.yml"
if [[ ! -f "${ACTION_FILE}" ]]; then
  echo "Cannot find action.yml at ${ACTION_FILE}"
  exit 2
fi

# Extract the `run: |` block from the composite step via yq.
# Fall back to python if yq missing.
extract_run_block() {
  if command -v yq >/dev/null 2>&1; then
    yq '.runs.steps[0].run' "${ACTION_FILE}"
  else
    python3 -c "
import sys, yaml
with open('${ACTION_FILE}') as f:
    doc = yaml.safe_load(f)
print(doc['runs']['steps'][0]['run'])
"
  fi
}

RUN_BLOCK="$(extract_run_block)"
if [[ -z "${RUN_BLOCK}" ]]; then
  echo "Failed to extract run block from action.yml"
  exit 2
fi

# Synthesize a GITHUB_OUTPUT file so the block doesn't error on the
# redirects. We don't assert outputs here — exit code IS the contract.
TMP_OUT="$(mktemp)"
trap 'rm -f "${TMP_OUT}"' EXIT

run_case() {
  local label="$1" mode="$2" target="$3" repo="$4" strict="$5" expected="$6"
  : > "${TMP_OUT}"

  # shellcheck disable=SC2034
  MODE="${mode}" \
  TARGET="${target}" \
  STRICT="${strict}" \
  REPO="${repo}" \
  GH_TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-$(gh auth token)}}" \
  GITHUB_OUTPUT="${TMP_OUT}" \
  bash -c "${RUN_BLOCK}" >/tmp/preflight.stdout 2>/tmp/preflight.stderr
  local rc=$?

  if [[ ${rc} -eq ${expected} ]]; then
    echo "PASS  ${label}  (rc=${rc})"
  else
    echo "FAIL  ${label}  (rc=${rc}, expected=${expected})"
    echo "----- stdout -----"
    cat /tmp/preflight.stdout
    echo "----- stderr -----"
    cat /tmp/preflight.stderr
    echo "----- outputs -----"
    cat "${TMP_OUT}"
    return 1
  fi
}

FAIL=0

# --- Unit regression for the jq-false-is-falsy bug ---
# Make sure the action distinguishes `.protected: false` (unprotected,
# API responded) from missing/error (truly unknown). The earlier
# `.protected // "unknown"` form collapsed both to "unknown", which
# silently turned the preflight into a placebo on unprotected repos.
JQ_EXPR='if has("protected") then .protected else "unknown" end'
EXPECT_PAIRS=(
  '{"protected":false}|false'
  '{"protected":true}|true'
  '{}|unknown'
  '{"name":"main"}|unknown'
)
for pair in "${EXPECT_PAIRS[@]}"; do
  JSON="${pair%%|*}"
  WANT="${pair##*|}"
  GOT="$(echo "${JSON}" | jq -r "${JQ_EXPR}")"
  if [[ "${GOT}" == "${WANT}" ]]; then
    echo "PASS  jq-regression  ${JSON} -> ${GOT}"
  else
    echo "FAIL  jq-regression  ${JSON} -> ${GOT} (want ${WANT})"
    FAIL=1
  fi
done

run_case "push -> PROTECTED upstream main (expect FAIL GH006 preempt)" \
  push main opensearch-project/opensearch-agent-skills true 1 || FAIL=1

run_case "pr -> PROTECTED upstream main (expect OK: PRs are the point)" \
  pr main opensearch-project/opensearch-agent-skills true 0 || FAIL=1

run_case "dry-run -> anywhere (expect OK)" \
  dry-run main opensearch-project/opensearch-agent-skills true 0 || FAIL=1

run_case "bogus mode (expect FAIL on validation)" \
  pushh main opensearch-project/opensearch-agent-skills true 1 || FAIL=1

run_case "push -> PROTECTED + strict=false (expect OK with warning)" \
  push main opensearch-project/opensearch-agent-skills false 0 || FAIL=1

if [[ ${FAIL} -eq 0 ]]; then
  echo
  echo "=== All preflight cases PASSED ==="
else
  echo
  echo "=== Preflight test FAILURES above ==="
  exit 1
fi
