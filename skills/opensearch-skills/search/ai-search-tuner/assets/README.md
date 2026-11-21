# Demo assets

A tiny synthetic corpus + qrels used only by the **offline demo**
(`--offline`) and tests, so the skill can be exercised end-to-end with no
running cluster. These are **not** a benchmark of retrieval quality — they are
sized and shaped to make each mode's tuning story visible deterministically.

## `corpus.jsonl`
Each line is `{"id", "text", "vector"}`. The corpus is built in three regimes:

- **Dense regime** (`v*`): tight vector clusters with generic shared text — the
  dense k-NN recall / quantization story.
- **Sparse regime** (`t*`): distinct tokens but near-collinear vectors — the
  sparse `prune_ratio` / index-size story.
- **Hybrid regime** (`hQ`, `hA*`, `hB*`): a deliberately **cross-modal** query.

## Why `hB*` looks "unrelated" but is graded relevant (intentional)

For the hybrid query `q::hQ` (text `"neural network training"`, vector on the
`[0.707, 0.707, …]` axis) the relevant set in `qrels.json` is **both**:

- `hA*` — **text matches** ("neural network training …") but the vector is far
  (`[0,0,…]`), so **only the sparse leg** retrieves them; and
- `hB*` — text is **intentionally unrelated** ("unrelated ledger inventory …")
  but the vector is **exactly aligned** with the query, so **only the dense
  leg** retrieves them.

Both groups are labeled `relevance = 2` **on purpose**: neither dense-only nor
sparse-only can retrieve all six relevant docs, so a balanced hybrid weight
strictly beats either standalone. This is what lets the offline demo show a real
hybrid "lift". Labeling `hB*` as non-relevant (because its *text* looks
unrelated) would collapse that signal — the low text relevance is the point, and
the vector alignment is what makes them relevant to a hybrid retriever.
