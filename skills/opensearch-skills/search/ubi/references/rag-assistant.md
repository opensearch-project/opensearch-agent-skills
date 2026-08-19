# The RAG branch: UBI for a retrieval-augmented assistant

The `ext` collision below was measured 2026-08-13 (throwaway OpenSearch
3.8.0, UBI 3.8.0.0, ml-commons); the store, join, chunking, and judgment
behavior 2026-08-14, live on a 3.8.0 plugin cluster, every probe
self-cleaned. This file is an overlay on
[ubi-schema.md](ubi-schema.md): the stores, field names, join semantics,
and traps there apply unchanged. What changes is what the words mean, and
who builds the query record.

## When this branch runs

The Audit's search call site is a retriever feeding a model (a LangChain
or LlamaIndex retriever, an ml-commons agent, a search pipeline with a
`retrieval_augmented_generation` processor), and the user sees an answer
rather than a results page. The seven steps run unchanged, with this
reading:

| The steps say | This app has |
|---|---|
| the typed query (`user_query`) | the user's question, as typed |
| the results | the retrieved chunks |
| the presented ranking (`query_response_hit_ids`) | chunk ids, in retrieval order |
| an impression | a chunk entering the model's context |
| a click | a citation opened |
| `position.ordinal` | the chunk's retrieval rank |

The gap this closes is otherwise unserved: which retrieved chunks actually
entered the model's context, and which of those a human bothered to open.
Retrieval usually hands back more than the prompt keeps, so the hit-ID list
is what retrieval returned and the impressions are the subset that made it
in. The difference between those two lists is the branch's own metric, and
no other instrument the app has can compute it.

On an Amazon OpenSearch Service domain this overlay composes with
[aws-managed.md](aws-managed.md): this file says what each record means,
that one says how records travel.

## The rule that shapes the branch

**The RAG search never carries `ext.ubi`.** On 3.8.0 as shipped, a search
whose `ext` holds both `ubi` and `generative_qa_parameters` dies whole with
HTTP 500, with or without the RAG pipeline attached: hits, generated
answer, and query row all lost, the LLM call already spent. Measured at
trace level: ml-commons' ext serializer throws on the re-serialization the
plugin's response-path capture performs, and query-insights hits the same
exception on the same request, so the broken serializer is ml-commons'
own. The failure is loud but total:
instrumenting the RAG request the plugin way breaks the application's own
search.

So on the RAG leg the plugin's query capture moves into the app: the
managed path's mechanism, on whatever cluster this branch finds. When
retrieval returns, the backend builds the query record
([aws-managed.md](aws-managed.md)'s shape, [ubi-schema.md](ubi-schema.md)'s
fields) and indexes it into `ubi_queries` directly, under the credentials
it already searches with. Measured live on a plugin cluster: the record
lands under the `dynamic: false` mapping, a `term` on `query_id` finds it,
`query_response_hit_ids` stays a keyword array a `term` filter can probe
for one chunk id, and a `flat_object` leaf in `query_attributes` (a
conversation id, say) term-filters exactly.

The bar is per-request, not per-application: a plain search box beside the
assistant keeps the plugin path unchanged, and the preflight's four checks
run as written; `initialize` is still what creates correct stores.

## The chunk identity leg: where this branch usually breaks

Everything above assumes each retrieved chunk has a stable external
identifier to be `object_id`. Most chunking pipelines never mint one. The
Audit settles which of two shapes the corpus is in, and the answer decides
what behavior, and any judgment built from it, can ever be about:

- **Chunks inside the parent, OpenSearch's own shape.** The
  `text_chunking` ingest processor writes the chunks back onto the parent
  document as a plain string array (measured: dynamic-mapped ordinary
  `text`, not `nested`), a search over them returns the parent as the hit,
  and no chunk-level identifier exists in the source, the mapping, or the
  hit: a highlight can show the matched text, but nothing supplies an
  identifier for it. Here
  `object_id` can only be the parent document's id: behavior lands at
  document grain, and which chunk entered the context travels as an event
  attribute (where the app can say at all), declared `keyword` before
  the first event ([ubi-schema.md](ubi-schema.md)'s rule).
- **Chunk-per-document.** Framework ingestion (LangChain, LlamaIndex,
  most homegrown pipelines) indexes each chunk as its own document, and
  the chunk id is whatever the pipeline minted, often fresh on every
  ingest run. Require a stable derivation, such as source document id plus
  position or a content hash, string-typed like any `object_id`.
  **Re-chunking orphans behavior:** new ids mean every accumulated
  impression, click, and judgment names chunks that no longer exist; the
  joins still hold and nothing errors, the rows just point at nothing
  retrievable. Put that beside retention when Map settles how long the
  stores keep behavior.

## Audit deltas

Same job, different words. What the step locates in this app:

- the retriever call, wherever the chain hides it. That is the search call
  site, and its index is the chunk corpus.
- the context-assembly point: where retrieved chunks are cut down to what
  actually enters the prompt. Impressions are known exactly here, and it
  is backend code.
- the citation affordance: whether the answer cites its chunks, and what
  opening one does. An assistant that never shows sources has no click:
  the floor shrinks to impressions, and Elicit hears that before goals are
  chosen, with the citation UI named as the product feature that would
  restore the signal.
- the feedback affordance: whether the answer itself can be rated (a
  thumbs pair, a "was this helpful?"). A rating is an audited UI action
  like any other; an assistant without one has no explicit signal, and
  the affordance is named to Elicit exactly as the missing citation UI
  is.
- conversation identity: a thread or memory id, where the app keeps one,
  rides in `query_attributes` (exact term filters; the aggregation caveat
  in [ubi-schema.md](ubi-schema.md)'s identity section applies). Each
  execution is its own query record (a follow-up, a rephrase, and a
  regenerate each mint a fresh `query_id`), and the conversation id is
  what groups them. The UBI specification has an open RFC to make
  `conversation_id` and `turn_number` first-class fields (o19s/ubi#47,
  unlanded as of 2026-08-16): until it lands, `query_attributes` stays
  the home, and a later session reads the spec's answer before
  inventing a parallel shape.

## Elicit deltas

Behavior here speaks to retrieval and context assembly, and — where a
feedback affordance exists — to whether the answer satisfied. Whether
it was *right*, grounded, or hallucinated never reaches these stores: a
rating is the user's verdict on the answer, not a measurement of the
answer against its sources, and grounding checks are a different
instrument, run on the model's output rather than on behavior. A goal
about answer correctness has no signal this session can map, and the
table hears that plainly rather than being left to infer otherwise.

And the click changes meaning. On a results page a click is the point of
the search; here an unopened citation is ambiguous (the answer sufficed,
or it was not trusted enough to check), and an opened one is as much
verification as interest. Citation metrics are read with that ambiguity
named, never as satisfaction.

**A rated answer is the branch's one explicit signal.** Where the Audit
found the affordance, each rating is an event under the standard
contract: `action_name` `feedback`, joined to its question by
`query_id`, the verdict in `event_attributes` under a field declared
`keyword` before the first event ([ubi-schema.md](ubi-schema.md)'s
rule). A rating keyed to the response's own id, kept as telemetry, is
the shape production feedback practice has converged on, and the
published work sets two bounds on reading it. Ratings rate the answer,
never the chunks that fed it — answer-grain signals are their own
research field, where document-click models are shown not to transfer
(Microsoft's web-QA implicit-feedback study, arXiv:2006.07581) — so the
feedback rate sits beside the funnel, not inside it. And satisfaction
reads at the conversation grain: in the assistant-evaluation
literature, task-level interaction sequences predict satisfaction where
per-query clicks do not (Kiseleva et al., CHIIR and SIGIR 2016), while
explicit thumbs arrive sparse and skewed enough to be unsound as the
sole quality verdict (CIKM 2023). The room hears the plain sentences,
never the papers: a feedback rate is a real signal, read beside its
volume, and it never stands alone for quality.

What the joined stores carry honestly: the two funnel rates
(retrieved-to-context, and context-to-opened), the floor metrics over
questions instead of searches, and the feedback rate where the
affordance exists. The no-click populations map cleanly:
questions that retrieved nothing and questions whose citations nobody
opened are this branch's zero-result and never-clicked lists, and the
review visit's inventory reads them unchanged because the rows are the
same shape. The plan file and the dashboard run unchanged for the same
reason: the records keep the pinned field names, so every query derives
as on the main path.

## Implement deltas

- **Server side:** no `ext.ubi` anywhere on the RAG request. The backend
  writes the query record when retrieval returns, and emits the
  context-entry impressions at prompt assembly: one `_bulk` for the
  batch, once per chunk per `query_id`. Both are backend-observed writes,
  so no relay is involved
  ([Emitting events](ubi-schema.md#emitting-events)); a retry or a
  regenerate is a new execution and mints a new `query_id` rather than
  re-firing under the old one.
- **Client side:** the citation open, under the standard contract,
  unchanged: a `click` carrying the chunk's `object_id`, its
  retrieval-rank `position.ordinal`, and the question as `user_query`.
  Where the feedback affordance exists, its rating is a second emitter
  under the same contract: the question's `query_id` and `user_query`,
  the verdict in `event_attributes`, and no `object_id`, because it
  rates the answer and no chunk.

## Verify deltas

The real user pair is one question asked and one citation opened. The six
checks run unchanged under this file's reading of the words. An assistant
with no citation affordance has no click: check 3 has no row to run, and
check 6 builds a list rating everything zero. That row is red, and stays
red, with the missing citation UI named as the reason and as the product
feature that would clear it. On a red row, work these before the base
catalog:

- **The search itself 500s once instrumentation lands:** `ext.ubi` crept
  onto the RAG request. This branch never sends it; the query record is
  app-built.
- **More impressions than the context held:** assembly emitted per
  retrieval attempt rather than per prompt, or a regenerate re-fired under
  the old `query_id`.
- **Click `object_id`s that match no document in the corpus:** the corpus
  was re-chunked since the rows were written (the identity leg above). The
  joins hold and nothing errors; recognition is by fetching what a row
  names, not by any check the stores can run.

## The judgments hand-off

The Workbench never asks what an `object_id` denotes. Measured: a COEC
judgment list built over RAG-shaped rows rated the opened chunk `4.000`
and the in-context, unopened chunk `0.000` under the question string:
chunk-grain judgments, from the same build ([judgments.md](judgments.md))
the storefronts use. The grain follows the identity leg: chunks where
chunks are documents, parent documents where they are not.

Three cautions belong in the report beside the volumes:

- The COEC normalizer is store-wide and crosses applications
  ([judgments.md](judgments.md)): an assistant sharing stores with a
  search UI reads ratings shaped by the other surface's clicks.
- `position.ordinal` is the retrieval rank on every event, impressions and
  clicks alike: one scale, or the rank curve compares nothing. The human
  chose among rendered citations, though, not the retrieval order, so
  where the two orders differ the position correction is approximate.
- The citation ambiguity above rides into every rating: these judgments
  rank the chunks people opened, which is the retrieval signal available,
  not the retrieval signal wanted.

A fourth is a gap in evidence rather than a measured caveat: whether
the Workbench's COEC build ignores an `action_name` it does not model
(`feedback`) or miscounts it has not been run. Until it has, a store
carrying feedback events is named as such before check 6 or the
judgments visit is promised over it: **unmeasured** in
[reachability.md](reachability.md)'s sense, a derivation expected to
hold and not yet demonstrated.

What the list is for is the boundary SKILL.md already draws: building it
from the assistant's own behavior is this skill's; tuning the retriever
with it is opensearch-launchpad's.
