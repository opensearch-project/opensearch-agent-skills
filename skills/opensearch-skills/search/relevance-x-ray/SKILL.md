---
name: relevance-x-ray
description: >
  Diagnose why a specific OpenSearch query/document pair scored the way it
  did. Use this skill when the user asks why a document ranked too low or
  too high, why a search result looks wrong, wants to debug relevance,
  understand a _explain output, tune BM25/hybrid/k-NN scoring, or asks
  things like "why didn't X show up," "why is Y ranked first," explain
  score, relevance debugging, ranking diagnosis, or missing synonyms.
  Complements opensearch-launchpad's aggregate evaluation (nDCG/P@k/MRR
  across many queries) by collecting evidence for a single query and
  document and abstaining when that evidence cannot establish a cause.
compatibility: Requires uv. Needs a reachable OpenSearch cluster (local, Docker, or remote).
metadata:
  author: arunx2
  version: "0.1"
---

# Relevance X-Ray

Act as an evidence-driven OpenSearch relevance debugger. Given a query and a
target document, collect the observed rank, competing hits, mappings, analyzer
evidence, and explain output. State only conclusions supported by those
artifacts; otherwise identify what remains unknown.

## When to Use

Activate when the user has a *specific* query and result they're confused
about (e.g., "why didn't 'wireless charger' return this product in the top
5?"). If instead they want aggregate quality metrics across many queries
(nDCG, P@k, MRR) or a brand-new search app, defer to
[opensearch-launchpad/evaluation_guide.md](../opensearch-launchpad/evaluation_guide.md).

## Prerequisites

- `uv` installed
- A reachable OpenSearch cluster. Use the read-only connection helpers bundled
  in `scripts/relevance_xray_lib/client.py`; they never bootstrap Docker and
  never send credentials over remote plaintext HTTP.

## Critical Rules (MUST follow)

1. **Preflight-check first** — run `preflight-check` before querying any index.
   Every diagnostic CLI command also enforces preflight in-process and MUST
   stop if it fails. Never start Docker or mutate infrastructure implicitly.
2. **Never fabricate evidence** — every score, rank, token, mapping, and
   parameter in the diagnosis MUST come from a live OpenSearch response or
   the submitted query. If evidence is unavailable, label the conclusion
   unknown; do not guess.
3. **One diagnosis at a time** — when the user gives multiple query/document
   pairs, process and present them one at a time unless they ask for a
   batch summary.
4. **Compare rankings, not isolated scores** — run the actual search and
   report the target's observed top-k rank plus representative hits above it.
   A single document's `_explain` output is insufficient to explain rank.
5. **Preserve explain arithmetic** — distinguish additive clauses from
   `max`/`product` operations and non-additive IDF, TF, norm, and boost
   factors. Never sum arbitrary explain nodes.
6. **Abstain on unsupported hybrid claims** — show raw BM25/k-NN leg explain
   scores separately, but never compare them with pipeline weights unless
   normalized per-leg contributions for the same result set are available.
7. **Require counterfactual evidence** — diagnose k-NN recall or recommend a
   vocabulary experiment only when a controlled rerun improves the target rank.

## Inputs Needed

Ask for whatever is missing:
- Index name
- Query (text or full query DSL)
- The document(s) the user is confused about (doc `_id`, or "top result" /
  "expected result" framing)

If the user only gives a query with no target document, run the query and
ask which result they want explained.

## Workflow

For a disposable OpenSearch 3.8.0 environment with deterministic fixtures,
read [demo-playbook.md](demo-playbook.md). Use its automated test before
changing parser, rule, synonym, k-NN, or hybrid behavior.

Run the commands below from this skill directory so the bundled `scripts/`
paths resolve for both standalone and full-tree installations.

### Step 1 — Preflight and fetch context

```bash
uv run python scripts/relevance_x_ray.py preflight-check
uv run python scripts/relevance_x_ray.py inspect-index --index <index>
```

`inspect-index` returns mappings, analyzers, and index settings. Read this
before interpreting explain output.

### Step 2 — Run the query with explain

```bash
uv run python scripts/relevance_x_ray.py explain \
  --index <index> --query '<query DSL or text>' --doc-id <id>
```

The command first runs the actual top-k search, then explains the target and
reports competing hits. For hybrid queries, it explains each raw retrieval
leg separately and explicitly marks normalized pipeline attribution as
unavailable unless the cluster response supplies it.

### Step 3 — Parse and diagnose

The command returns:
- Observed target rank and representative higher-ranked hits
- Additive score clauses separated from non-additive scoring factors
- Supported findings with evidence and confidence
- Evaluated rules and limitations for rules that lacked sufficient evidence

Translate the output into a direct answer; do not paste raw JSON. Lead with a
supported finding when one exists. Otherwise say that no root cause was
established and name the missing evidence.

### Step 4 — Propose a fix

Only a supported finding should end with a concrete suggestion:
- A mapping/analyzer change (show the exact `PUT` body)
- A boost adjustment
- A candidate vocabulary expansion (see Step 5)
- An `ef_search` candidate validated while holding `k` constant

When no finding is supported, recommend the next evidence-gathering action
instead of changing production configuration.

### Step 5 — Vocabulary suggestions (optional, on request or when a vocabulary gap is detected)

When the query term is absent from the target but the user suspects a
vocabulary gap, run:

```bash
uv run python scripts/relevance_x_ray.py suggest-synonyms \
  --index <index> --query-term <term> --doc-id <id>
```

This takes a reproducible randomized document sample, fetches its generated
term vectors in one bounded batch, counts support once per document, restricts
candidates to terms present in the target, and runs a non-mutating
`multi_match(operator=or)` query expansion. Recommend only candidates that
improve the target's measured top-k rank. Report the sample size, support,
association, validation query shape, and rank delta. Treat this as evidence
for a candidate experiment, not proof that two terms are semantically
equivalent or that a production synonym analyzer will rank identically.

## Diagnosis Rules

`scripts/relevance_xray_lib/rules_engine.py` evaluates a rule only when its required evidence is
available and reports which rules were skipped. Tags mirror
`opensearch-launchpad`'s finding-tag vocabulary where applicable.

| Rule | Trigger | Tag | Typical Fix |
|---|---|---|---|
| Missing keyword sub-field | Query relies on exact/filter match against a `text` field with no `.keyword` sub-field | `[INDEX_MAPPING]` | Add a `.keyword` sub-field, reindex |
| Analyzer mismatch | Actual search-analyzer tokens miss the target while index-analyzer tokens overlap its term vectors | `[INDEX_MAPPING]` | Align analyzers and re-run the same ranking query |
| Unavailable scoring field | A script/function field is absent or has `doc_values: false`; `index: false` alone is not an error | `[QUERY_TUNING]` | Fix the reference or enable the required value source |
| Vocabulary candidate | A target term has document-level corpus association with the query term and improves rank under query expansion | `[QUERY_TUNING]` | Evaluate a search-time synonym on a broader judged query set |
| Weak k-NN recall | The target rank improves when only explicit `ef_search` is increased and `k` remains fixed | `[MODEL_SELECTION]` | Evaluate the measured parameter candidate against latency and aggregate relevance |
| Hybrid inert leg | A nonzero-weight leg has zero measured normalized contribution across inspected results | `[SEARCH_PIPELINE]` | Inspect the leg and normalization bounds; do not infer this from raw-score ratios |

## Output Format

Present findings as:

1. **Supported conclusion** — observed fact or evidence-backed finding with
   confidence; explicitly say when no root cause was established.
2. **Evidence** — rank, competing hits, score clauses, factors, analyzed
   tokens, and counterfactual deltas with their source.
3. **Coverage** — rules evaluated and limitations/unknowns.
4. **Fix or next measurement** — provide a fix only when validated.

Do not dump raw `_explain` JSON on the user unless they explicitly ask for
it.
