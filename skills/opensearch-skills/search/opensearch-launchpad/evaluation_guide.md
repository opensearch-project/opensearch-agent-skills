# Search Quality Evaluation Guide

Data-driven evaluation that runs real queries against the live index, computes quantitative metrics, and diagnoses issues with actionable recommendations.

## When to Evaluate

Offer evaluation after Phase 4 completes successfully:
> "Would you like to evaluate the search quality? I can run test queries, measure relevance metrics, and suggest improvements."

If the user declines, skip to Phase 5.

## Evaluation Workflow

### Step 1: Generate Test Queries

**Option A — UI server is running (preferred):**

Call the suggestions endpoint. It returns test queries with capabilities already assigned from the search configuration in Phase 4:

```
GET http://127.0.0.1:8765/api/suggestions?index=<index>
```

Response:
```json
{
  "suggestions": [
    {"text": "The Godfather", "capability": "exact", "query_mode": "TERM", ...},
    {"text": "director:Frank Darabont", "capability": "structured", "query_mode": "FILTER", ...},
    ...
  ],
  "sample_docs": [...],
  "has_semantic": true,
  "index": "my-index"
}
```

Use the `suggestions` list directly as test queries.

**Option B — UI server is not running:**

Ask the user to provide test queries. The agent assigns a capability to each query based on its form:

| Capability | How to detect | Example |
|-----------|---------------|---------|
| `exact` | Matches a known title/name in the data | `The Matrix` |
| `structured` | Contains `field:value` syntax | `genres:Drama` |
| `combined` | Free text + `field:value` | `space adventure genres:Sci-Fi` |
| `autocomplete` | Short prefix (< 5 chars or partial word) | `The Ma` |
| `fuzzy` | Contains apparent misspelling | `Teh Matrx` |
| `semantic` | Natural language describing a concept | `movies about redemption in prison` |

### Step 2: Batch Search

Run **all** queries through the search pipeline in a single call using `evaluate_search_results`. This runs every query through `search_ui_search` (the real pipeline from Phase 4) and returns results for the agent to judge:

```bash
uv run python -c "
import sys, json; sys.path.insert(0, 'scripts')
from opensearchpy import OpenSearch
from lib.evaluate import evaluate_search_results
client = OpenSearch(hosts=[{'host': 'localhost', 'port': 9200}], use_ssl=False, verify_certs=False)
result = evaluate_search_results(client, '<index>', title_field='<title_field>', k=5)
print(json.dumps(result['queries'], indent=2))
"
```

Output — one entry per query with all results:
```json
[
  {"query": "The Godfather", "capability": "exact", "results": [
    {"title": "The Godfather", "score": 1.28},
    {"title": "The Matrix", "score": 0.40}, ...
  ]},
  {"query": "director:Frank Darabont", "capability": "structured", "results": [
    {"title": "The Shawshank Redemption", "score": 1.91}
  ]},
  ...
]
```

This is **one command, one approval** — no per-query back-and-forth.

### Step 3: Judge Relevance

For each query, the agent reviews the returned documents and assigns a relevance grade to each query-document pair. Grade every document in the top-k results — do not skip any.

**Grading scale:**

| Grade | Label | Criteria |
|-------|-------|----------|
| 3 | Perfect | The document is exactly what a user searching this query would want. For exact queries, the title matches. For semantic queries, the document directly addresses the concept. |
| 2 | Relevant | The document is clearly useful and related to the query intent, but is not the ideal result. For example, a sequel when the user searched for the original. |
| 1 | Marginal | The document shares a topic, genre, or keyword with the query but does not satisfy the search intent. A loose thematic connection. |
| 0 | Irrelevant | The document has no meaningful connection to the query. This is the default for unlisted documents. |

**Judgment prompt — for each query-document pair, evaluate:**

1. **Intent match**: What is the user trying to find with this query? Does this document satisfy that intent?
2. **Content relevance**: How well does the document's content relate to the query, regardless of how the query was issued? A document about prison redemption is relevant to "movies about redemption in prison" whether the query came from a keyword search, semantic search, or a structured filter.
3. **Would a real user click this?** If yes, grade >= 2. If maybe, grade 1. If no, grade 0.

**Example judgment for query `"movies about redemption in prison"`:**

| Document | Grade | Reasoning |
|----------|-------|-----------|
| The Shawshank Redemption | 3 | Directly about redemption and prison — perfect match |
| Pulp Fiction | 1 | Contains themes of redemption but not about prison |
| Interstellar | 0 | Space exploration — no connection to prison or redemption |

Also judge documents that **should** appear but are missing from results — these feed into Rule 5 (missed relevant docs). Include them in the `relevance` dict even if they weren't returned.

### Step 4: Compute Metrics and Diagnose

Pass the relevance judgments from Step 3 together with the cached search results from Step 2 into `evaluate_index`. This reuses the search results — no queries are re-run:

```bash
uv run python -c "
import sys, json; sys.path.insert(0, 'scripts')
from opensearchpy import OpenSearch
from lib.evaluate import evaluate_search_results, evaluate_index
client = OpenSearch(hosts=[{'host': 'localhost', 'port': 9200}], use_ssl=False, verify_certs=False)
search_results = evaluate_search_results(client, '<index>', title_field='<title_field>', k=5)
report = evaluate_index(
    search_results=search_results,
    relevance_overrides={
        'The Godfather': {'The Godfather': 3, 'Goodfellas': 1},
        'director:Frank Darabont': {'The Shawshank Redemption': 3},
    },
)
print(report)
"
```

If Step 2 was not run separately, `evaluate_index` can also run searches from scratch:

```python
report = evaluate_index(
    client, index_name, title_field="title", k=5,
    relevance_overrides={...},
)
```

### Step 5: Present Results

**Always present the output of `format_report()` (or `evaluate_index()`) directly to the user.** Do not reformat, summarize, or rearrange the report. The report has a fixed schema with these sections in order:

1. **Header** — index name, methods, k, query count
2. **Per-query detail** — for each query: relevance labels, per-method star rating + nDCG/P@k/MRR, ranked document list with scores, grades, and DCG contributions
3. **nDCG table** — all queries × methods in a single table with MEAN row
4. **Summary** — mean metrics per method with visual bar
5. **Per-type breakdown** — mean nDCG grouped by query capability
6. **Findings & recommendations** — grouped by tag, sorted by severity, with recommended next action
7. **Completion check** — pass/fail against target thresholds

This schema is produced by `format_report()` in `evaluate.py`. Present it as a code block so formatting is preserved:

````
```
<output of evaluate_index() or format_report()>
```
````

After the report, add a brief summary (2-3 sentences) highlighting the key takeaway and suggested next step.

## Metrics

Three metrics are computed per query per method, all at cutoff `k`:

| Metric | Formula | What it measures |
|--------|---------|------------------|
| **nDCG@k** | Normalized Discounted Cumulative Gain | Ranking quality -- are the best docs at the top? |
| **P@k** | Precision at k | What fraction of top-k results are relevant? |
| **MRR** | Mean Reciprocal Rank | How quickly does the first relevant result appear? |

### Target Thresholds

| Metric | Good (>= ) | Acceptable (>=) | Poor (<) |
|--------|-----------|-----------------|----------|
| Mean nDCG@k | 0.70 | 0.50 | 0.30 |
| Mean P@k | 0.60 | 0.40 | 0.20 |
| Mean MRR | 0.70 | 0.50 | 0.20 |

## Diagnosis Rules

The engine applies five diagnostic rules, comparing across all provided methods:

### Rule 1: All methods fail (nDCG < 0.3 for every method)
- **Severity**: HIGH
- **Meaning**: No retrieval strategy can find relevant documents for this query
- **Tag**: `[MODEL_SELECTION]` for semantic queries, `[INDEX_MAPPING]` for combined/structured
- **Fix**: Check field mappings, analyzers, or upgrade embedding model

### Rule 2: Pairwise method gaps (tag-aware)
- **Severity**: MEDIUM
- **Triggers when**: A vector-tagged method fails (nDCG < 0.3) while a lexical-tagged method succeeds (nDCG > 0.5), or vice versa
- **Tag**: `[MODEL_SELECTION]` when vector fails, `[INDEX_MAPPING]` when lexical fails
- **Fix**: Upgrade embedding model, or add proper text analyzers/boosting

### Rule 3: Hybrid worse than single signals
- **Severity**: MEDIUM/LOW
- **Triggers when**: A hybrid-tagged method's nDCG is > 0.15 below the best non-hybrid method
- **Tag**: `[SEARCH_PIPELINE]`
- **Fix**: Adjust hybrid weights, or use query-type-aware routing

### Rule 4: Irrelevant docs in top-2
- **Severity**: MEDIUM
- **Triggers when**: An irrelevant document (grade 0) appears in positions 1-2 and nDCG < 0.8
- **Tag**: `[QUERY_TUNING]` or `[MODEL_SELECTION]`
- **Fix**: Reduce field boosts, restructure query, or upgrade model

### Rule 5: Missed relevant documents
- **Severity**: LOW
- **Triggers when**: High-relevance documents (grade >= 2) don't appear in any method's top-k
- **Tag**: `[MODEL_SELECTION]`
- **Fix**: Embed more fields, use a higher-capacity model

## Finding Tags

| Tag | What it targets | Example fix |
|-----|----------------|-------------|
| `[INDEX_MAPPING]` | Field types, analyzers, `.keyword` sub-fields | Add `.keyword` to filterable fields |
| `[EMBEDDING_FIELDS]` | Which fields are embedded | Concatenate `title + genres` before embedding |
| `[MODEL_SELECTION]` | Embedding model quality/type | Switch from sparse to dense, or upgrade model size |
| `[SEARCH_PIPELINE]` | Hybrid weights, normalization | Shift from 0.8/0.2 to 0.5/0.5 balanced |
| `[QUERY_TUNING]` | Field boosts, fuzziness, filter placement | Move filters to `bool.filter` to avoid score pollution |

## Completion Criteria

The evaluation passes if **any** of:
- Mean nDCG@k across all methods > 0.7
- All findings are LOW severity only
- No HIGH severity findings and setup matches the use case

## After Evaluation

Present the evaluation results, then offer the user these options:

> "Based on the evaluation, here's what you can do next:"
> 1. **Restart with improvements** — I'll apply the recommended fixes and rebuild the search setup with a new index.
> 2. **Deploy to Amazon OpenSearch Service** (Phase 5) — Deploy the current configuration as-is.
> 3. **Done for now** — Keep experimenting with the Search Builder UI.

If HIGH severity findings exist, recommend option 1 and explain the specific fix. If only LOW findings, note that the setup is acceptable and any option is reasonable.

### Restart Flow

When the user chooses to restart:

1. **Record the current index name** — do not delete it. The user can compare against it later.
2. Restart from Phase 3 with the recommended fixes. During Phase 4, create the new index with a **different name** (e.g. append `-v2` or `-improved` to the original name).
3. **After Phase 4 completes**, launch the UI normally:

```bash
uv run python scripts/opensearch_ops.py launch-ui --index <new-index-name>
```

4. Let the user know they can compare the old and new indices using the Compare toggle:

> "The improved search setup is live. You can use the **Compare** toggle in the Search Builder to select the old index alongside the new one and compare results side by side. Both indices are available in the index dropdowns."

After the user reviews the results, offer:
> 1. **Re-evaluate** — Run the evaluation again on the improved index to measure the impact.
> 2. **Deploy to Amazon OpenSearch Service** (Phase 5) — Deploy the improved configuration.
> 3. **Done for now** — Keep experimenting with the Search Builder UI.
