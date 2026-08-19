# Intent labels: every metric, read by what people came to do

The room names the things people come to this app to do (five to fifteen
labels, in its own words), and the review visit can then report every plan
metric per label: each distinct query string in `ubi_queries` assigned to
its nearest label by embedding, so phrasing nobody has seen before lands on
a bucket the room already owns. This file is the contract: what the labels
must be, where the embedding runs, the assignment procedure, and what the
result can and cannot say. Every measured figure below was taken on
OpenSearch 3.8.0 with the bundled ml-commons plugin and the pretrained
`huggingface/sentence-transformers/all-MiniLM-L6-v2` model (384
dimensions). The figures are that model's on that bed: provenance for
the traps below, never thresholds to reuse.

**This is not clustering, and the difference is the design.** A clustering
run over the query log invents its own buckets and leaves the room a
"cluster 7" to puzzle over; here the buckets exist before the log is read,
they are in the team's ubiquitous language, and they are stable across
visits, which is what makes them valid as a reporting key. The log never
names a bucket. And it is not retrieval: the embedding classifies strings
for reporting, and the no-click inventory's diagnosis two sections over in
[return-visits.md](return-visits.md) stays lexical; this file is no
license to rebuild the semantic leg that fence turns down.

## The labels, and the seeds that make them assignable

Labels come from the room, never from the log, asked as one question:
what do people come to this app to do? Five to fifteen answers, each in
the room's own words, each with **three to five seed phrasings**: what
would someone type into the search box when they come to do this? The
seeds are not decoration; they are the classifier. The centroid a query
is assigned to is the mean of its label's seed embeddings, and measured
assignment quality turns almost entirely on them:

- **Embedding the label sentence alone is refuted.** A label like "find a
  gift for someone" describes behavior; a query names a thing, and the
  two sit in different registers of the embedding space. Measured:
  against label-sentence embeddings, "cheap batteries" assigned to the
  gift label at 0.290, a service query drew a *confident* wrong label
  (margin 0.140), and correct assignments barely cleared noise. Against
  seed centroids the same strings assigned correctly, including
  phrasings no seed contains ("how do I keep bread from going stale" →
  the pantry label at 0.324, "something to keep my food fresh" → the
  same at 0.459). Query-register seeds are what make zero-shot work.
- **Labels must differ in subject matter, not in shopping mode.** "Find a
  specific product" versus "browse for ideas" is a difference in the
  person's head, not in the string: both intents type "headphones", and
  measured, that string's best-versus-second margin across such a pair
  was 0.008, a coin flip presented as an assignment. When the room offers
  a mode pair, say plainly that the strings cannot carry it and ask what
  the two modes are *about*; subject-distinct labels ("upgrade their
  tech", "keep the pantry stocked", "find a present") assigned the same
  test strings correctly, the narrowest margin 0.054 against that 0.008.
- **A seed leaks every register it carries.** One gift seed phrased
  "gifts under 20 dollars" pulled "cheap batteries" into the gift label
  at 0.382 with a wide margin: the price word, not the subject, did the
  matching. Seeds name the subject; qualities like cheap, best, or fast
  attract every query that shares the quality, whatever it is about.

The labels and seeds are named at Elicit when the room is already
assembled, before any log exists to bias them, which is what keeps the
buckets the room's rather than the data's. They are recorded in
`ubi-metrics-plan.md` under the pinned shape in
[metrics-plan.md](metrics-plan.md). A team past Elicit names them at the
review visit instead, the same one question, recorded the same way; the
plan file is what makes them durable, and the user's edits to it govern
here as everywhere.

## Where the embedding runs: the room's decision

Two homes, put to the room plainly before anything is registered. The
recommendation is the in-cluster model, and the reasons are the room's to
weigh:

- **In-cluster pretrained model** (recommend): free per call, nothing
  leaves the cluster, no credential stored anywhere. ml-commons ships a
  pretrained catalog; registering fetches the artifact from the model
  repository, so the cluster node needs outbound internet once.
  Measured, the full register took 89 seconds including the ~90 MB
  download, and the deploy 7 seconds. An air-gapped cluster registers
  from a URL it can reach instead. The deployed model held roughly 190
  MiB of steady-state memory on the measured bed (transiently more while
  registering), and its chunks occupy ~116 MB in `.plugins-ml-model`.
- **Remote connector**: an external embedding API behind an ml-commons
  connector. It costs per call, and it persists the provider credential
  inside the cluster as stored state; name both to the room. It is the
  shape to reach for only where the cluster cannot run a local model.

The measured bed carried three persistent settings for the local path:
`plugins.ml_commons.only_run_on_ml_node: false` (a dev cluster has no ML
node), a raised `plugins.ml_commons.native_memory_threshold` (the default
90 trips on a busy host), and
`plugins.ml_commons.model_access_control_enabled: false` (no security
plugin). The cycle was not attempted without them.
On an Amazon OpenSearch Service domain, whether a local model is
available is the domain's own question (instance types gate it), and this
procedure was not measured there.

Registering and deploying the model creates cluster state: a Critical
Rule 5 write, one setup named in one plain sentence, alone in its turn.
So is deleting it later. Two facts shape the announcement: a model, once
deployed, comes back on its own after a node restart
(`plugins.ml_commons.model_auto_redeploy.enable` defaults true at 3.8,
observed surviving one), so it is standing state the team keeps until
someone removes it, not a session-scoped probe; and an undeployed model
answers `_predict` with a 400 ("Model not ready yet") rather than
silently redeploying, so the explicit deploy is the write and stays the
only one. Check first whether a text-embedding model is already deployed
(`POST /_plugins/_ml/models/_search`, a free read) and use what is
there rather than registering a second copy.

## The assignment, and reading it with the room

1. **The distinct strings.** A terms aggregation on `user_query` in
   `ubi_queries`, sized past the store's distinct strings and excluding
   the empty string; the truncation and population traps of the
   no-click inventory apply unchanged
   ([return-visits.md](return-visits.md)). A store holding fewer distinct
   strings than the room has labels has nothing to spread yet: say so and
   stop. This is structurally a feature of an accumulated log, and at
   the end of a first session the read returns the room's own test
   searches.
2. **One `_predict` call embeds everything.** `text_docs` takes the whole
   list, seeds and query strings together; thirty texts embedded in
   0.37 seconds, measured. Each label's centroid is the mean of its seed
   vectors. The model's own outputs are unit vectors, but **a mean of
   unit vectors is not one** (measured norms 0.57-0.78): compare by
   cosine, never by raw dot product, or the shorter centroids lose every
   assignment.
3. **The assignment table is read with the room before any metric is
   grouped.** Every string, its label, its similarity, sorted ascending,
   so the misfits surface at the top. Two measured facts govern the
   reading: there is a floor, and it is thin. A query with no honest
   label ("return policy", against five shopping labels) fell to 0.070
   while the weakest correct assignment sat at 0.324, but keyboard mash
   landed at 0.20-0.24, inside shouting distance of correct-but-weak. So
   the cut is not a constant this file can hand you: propose it where the
   gap is visible in the sorted list, and the room approves it like any
   other cell. Strings below it are reported as their own list, ranked by
   query volume; "none of these" is a finding (service queries surfacing
   there means people come to do something no label covers), never a
   silent drop. And a misspelled string never assigns well: "hedphones"
   drew a wrong label in every probe. The embedding is not a
   spell-checker, and typos belong to the lexical diagnosis, not to a
   label.
4. **Then every metric, per label.** Assignment gives each label its set
   of strings; a `terms` filter on `user_query` over that set slots into
   any plan metric's query unchanged, because `user_query` is `keyword`
   in both stores. Measured composing live: one intent's strings filtered
   `ubi_events` to 25 rows, aggregated cleanly by `action_name`. The
   review's own rules govern the rendering: each number beside how much
   data it stands on, the three word-not-figure rules, and no strategy
   dressed over the arithmetic. And because the labels are stable across
   visits, they hold as a reporting key beyond the conversation: a
   later dashboard ask is [Step 7](../SKILL.md#step-7-dashboard)'s to
   serve, and these same filtered queries are what it would panel.

## What the result cannot say

Said to the room with the first by-intent table, because every
over-reading starts here. The assignment is per *string*, not per person:
everyone who typed "headphones" lands in one bucket, whatever each of
them wanted, and a distinction the string cannot carry (the mode pairs
above) is not in the report however carefully the labels were named. A
similarity is not a confidence: 0.3 from this model on these seeds is a
sound assignment, and the same number elsewhere may not be. And the
report inherits capture's blind spots: a search whose query row never
landed is in no bucket, not a low one.

The model itself is the other thing to leave said: it is standing cluster
state the team now owns, doing nothing between reviews. Undeploying frees
the memory and a later visit redeploys in seconds; deleting the model
removes its chunks. Either is theirs to choose, recorded, like every
choice here, by saying it in the room.
