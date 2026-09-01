# Relevance X-Ray

**OpenSearch Agent Skills Hackathon 2026 submission.** Diagnoses *why* a
specific search result ranked where it did in OpenSearch by collecting
rank, competitor, analyzer, mapping, and explain evidence. It proposes a
fix only when that evidence supports one.

Submission: https://github.com/opensearch-project/opensearch-agent-skills/issues/86

## Problem

`opensearch-launchpad`'s evaluation guide already answers "is my index
good, on average, across many test queries" (nDCG, P@k, MRR). But when a
user has one specific query and one specific document they're confused
about — "why didn't 'wireless charger' return this product in the top 5?"
— the raw `_explain` tree alone does not establish a ranking cause. This
skill combines it with rank, competitor, mapping, and analyzer evidence and
explicitly abstains when that evidence is insufficient.

## What it does

Given an index, a query, and a document, Relevance X-Ray:

1. Fetches the index's mapping/analyzer configuration for context.
2. Runs the actual top-k search and parses the target's explain tree while
   preserving sum/max/product operations and separating score clauses from
   non-additive factors.
3. Runs a small rules engine against known anti-patterns: missing
   `.keyword` sub-fields, unavailable doc-value scoring fields, analyzer
   mismatches backed by analyzed tokens/term vectors, measured k-NN recall
   changes, and normalized hybrid output when available.
4. Optionally mines target-present vocabulary candidates from a randomized
   document sample and retains only candidates that improve rank in a
   controlled OR query-expansion rerun.

Findings reuse the `[INDEX_MAPPING]` / `[MODEL_SELECTION]` /
`[SEARCH_PIPELINE]` / `[QUERY_TUNING]` tag vocabulary already established
by `opensearch-launchpad`'s evaluator, so the two skills read consistently.

Query tuning preserves the baseline query shape. A `bool` query containing
`multi_match` can receive field-boost candidates such as `title^2` while
remaining a `bool` query. `function_score` candidates are proposed only when
the baseline already uses `function_score`; the skill does not wrap an
ordinary query in one. A `bool` query composed only of individual `match`
clauses does not currently receive automatic field-boost candidates.

## Try it

```bash
# 1. Build OpenSearch 3.8.0 and wait for deterministic fixtures
bash examples/docker/run-demo.sh up

# 2. Run all end-to-end assertions
bash examples/docker/run-demo.sh test

# 3. Print every example report
bash examples/docker/run-demo.sh all
```

See [demo-playbook.md](demo-playbook.md) for individual analyzer, mapping,
scoring, synonym, k-NN, hybrid, and abstention cases.

## Files

```
relevance-x-ray/
  SKILL.md                     Skill manifest (frontmatter + workflow)
  README.md                    This file
  demo-playbook.md             OpenSearch 3.8 test and presentation guide
  scripts/
    relevance_x_ray.py         Standalone CLI entrypoint
    relevance_xray_lib/        Read-only client and diagnostic modules
  examples/
    demo_index_setup.sh        Seeds an existing cluster
    seed-demo.sh               Idempotent fixture loader
    fixtures/                  Mapping, documents, and search pipeline
    docker/                    Custom image, Compose file, and demo runner

../../scripts/relevance_x_ray.py
                                Compatibility launcher for full-tree installs
```

## Testing

Follows the repo's convention: pure functions unit-tested with fixture
data, no live cluster required.

```bash
uv run pytest tests/test_agent_skills_explain_parser.py \
              tests/test_agent_skills_relevance_diagnostics.py \
              tests/test_agent_skills_relevance_x_ray.py \
              tests/test_agent_skills_relevance_x_ray_demo.py \
              tests/test_agent_skills_rules_engine.py \
              tests/test_agent_skills_synonym_suggester.py \
              tests/test_agent_skills_report.py \
              tests/test_agent_skills_query_tuner.py -v
```

The thin client-calling functions in `synonym_suggester.py`
(`fetch_sample_document_ids`, `fetch_document_term_lists`,
`validate_synonym_candidate`) are tested against a fake client object, not
a real cluster, matching the pattern used elsewhere in this repo.

## Design notes / scope for the hackathon build

- Bundles its read-only CLI runtime so the leaf works when installed
  independently. A compatibility launcher preserves the full-tree command.
- Vendor-neutral: pure OpenSearch REST API calls (`_search`, `_explain`,
  `_analyze`, `_termvectors`, `_mtermvectors`, `_mapping`), no proprietary dependencies.
  Supports endpoints and authentication modes handled by the shared client
  primitives.
- The vocabulary miner is a lightweight, dependency-free co-occurrence
  heuristic, not an embedding similarity search — this keeps it fully
  unit-testable with no extra ML dependency and no network calls in tests.
  Its OR-expansion validation is evidence for a candidate experiment, not
  proof that a production synonym analyzer will produce the same ranking.
- Scope was deliberately staged: BM25 explain parsing and the anti-pattern
  rules are the baseline-submittable core; hybrid/k-NN leg-splitting and
  the synonym suggester are the stretch layers described in the hackathon
  submission.
