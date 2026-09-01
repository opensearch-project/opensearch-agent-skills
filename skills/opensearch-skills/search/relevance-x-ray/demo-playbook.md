# Relevance X-Ray Demo Playbook

Use this playbook to forward-test the skill against the pinned
OpenSearch 3.8.0 demo image. The environment is local, security-disabled, disposable,
and seeded with deterministic data.

## Contents

- [Start](#start)
- [Automated Test](#automated-test)
- [Demo Cases](#demo-cases)
- [Expected Behavior](#expected-behavior)
- [Cleanup](#cleanup)

## Start

From the repository root:

```bash
bash skills/opensearch-skills/search/relevance-x-ray/examples/docker/run-demo.sh up
```

The command builds `relevance-x-ray-demo:3.8.0`, publishes OpenSearch at
`http://localhost:19200`, waits for the loader, and verifies ten documents.
Override the host port with `OPENSEARCH_PORT=<port>`.

## Automated Test

Run all assertions:

```bash
bash skills/opensearch-skills/search/relevance-x-ray/examples/docker/run-demo.sh test
```

The test fails if any case loses its expected evidence or abstention.

## Demo Cases

Run every report:

```bash
bash skills/opensearch-skills/search/relevance-x-ray/examples/docker/run-demo.sh all
```

Run one case by replacing `all` with one of these commands:

| Command | Example user question | Evidence under test |
|---|---|---|
| `abstention` | "Why is doc 1 ranked here for trainers?" | Ranking and explain evidence without an unsupported root cause |
| `analyzer` | "Why does running miss doc 8?" | Search/index analyzer tokens plus target term vectors |
| `mapping` | "Is brand an exact-match field?" | `term` query against a text field without a keyword sub-field |
| `scoring` | "Why is quality_score not affecting rank?" | Absent `field_value_factor` mapping |
| `doc-values` | "Can popularity score with index:false?" | No false positive when doc values remain enabled |
| `synonym` | "Should sneakers expand to trainers?" | Document-level association plus measured OR-expansion rank change |
| `knn` | "Does a larger ef_search recover doc 1?" | Baseline versus higher-`ef_search` target rank with `k` fixed |
| `hybrid` | "Which hybrid leg retrieved doc 1?" | Raw leg explanations and explicit normalization limitation |

For a raw CLI invocation:

```bash
OPENSEARCH_HOST=127.0.0.1 \
OPENSEARCH_PORT=19200 \
OPENSEARCH_AUTH_MODE=none \
uv run python skills/opensearch-skills/search/relevance-x-ray/scripts/relevance_x_ray.py explain \
  --index relevance-x-ray-demo \
  --query trainers \
  --doc-id 1 \
  --auth-mode none
```

## Expected Behavior

The playbook verifies these contracts:

1. Reports include the observed target rank and higher-ranked competitors.
2. Analyzer findings cite tokens returned by `_analyze` and `_termvectors`.
3. `index: false` does not trigger a scoring-field error when doc values work.
4. Vocabulary experiments are proposed only after document support and
   OR-expansion rank validation.
5. k-NN recall findings require a measured `ef_search` counterfactual with
   `k` held constant.
6. Hybrid raw scores are never compared directly with pipeline weights.
7. Cases without sufficient evidence explicitly withhold a root cause.

The fixture vectors are synthetic and only test control flow. Do not use
their scores as model-quality benchmarks.

## Cleanup

```bash
bash skills/opensearch-skills/search/relevance-x-ray/examples/docker/run-demo.sh down
```
