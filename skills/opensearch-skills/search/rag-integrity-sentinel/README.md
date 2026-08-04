# RAG Integrity Sentinel

RAG Integrity Sentinel is a read-only OpenSearch Agent Skill for investigating
indirect prompt injection, provenance drift, checksum mismatches, Unicode
concealment, active content, and exact or near-duplicate poisoning in retrieval
corpora. It treats retrieved text as untrusted evidence and produces a bounded,
machine-readable report plus a human-approved containment plan. It never
mutates an OpenSearch cluster.

## Run it

Run these commands from this directory. Scan a UTF-8 JSONL export without a
cluster:

```bash
uv run python scripts/rag_integrity.py scan-jsonl \
  --input sample.jsonl \
  --text-fields content,title \
  --provenance-fields source_uri,ingested_at,content_sha256 \
  --output rag-integrity-report.json
```

For a live read-only scan, set `OPENSEARCH_URL` in the process environment. If
authentication is required, also set `OPENSEARCH_USERNAME` and
`OPENSEARCH_PASSWORD`; authenticated endpoints must use verified HTTPS. Then
run:

```bash
uv run python scripts/rag_integrity.py scan-cluster \
  --index knowledge-base-read \
  --size 250 \
  --text-fields content,title \
  --provenance-fields source_uri,ingested_at,content_sha256 \
  --output rag-integrity-report.json
```

Optional neural expansion requires both a deployed model and an embedding
field:

```bash
uv run python scripts/rag_integrity.py scan-cluster \
  --index knowledge-base-read \
  --size 250 \
  --text-fields content,title \
  --provenance-fields source_uri,ingested_at,content_sha256 \
  --semantic-field content_embedding \
  --model-id "<deployed-model-id>" \
  --semantic-k 20 \
  --semantic-seeds 5 \
  --output rag-integrity-report.json
```

Reproduce the bundled 20-document regression benchmark:

```bash
uv run python scripts/benchmark.py --output rag-integrity-benchmark.json
```

## Sampling and interpretation

`scan-cluster` issues one bounded `match_all` search sorted by `_doc`. The
default is **250 documents** and the hard maximum is **1,000 documents** per
invocation. It does not randomize, paginate, or attempt a full-index scan. The
selection is deterministic for the index state and shard layout observed by
that request. Operators should target an appropriate index, alias, or
caller-produced export for the ingest window under investigation.

A clean result means only that no configured deterministic signal was found in
the sampled fields. It does **not** establish global safety for an index or
corpus. Semantic similarity generates review candidates; it is never treated
as proof that a document is malicious.

## Integration model

The primary workflow is an ad-hoc investigation initiated by an engineer. The
scanner is not a daemon, ingestion plugin, or autonomous quarantine service.
Callers may also run it as a caller-controlled CI gate over a deliberate JSONL
export:

```bash
uv run python scripts/rag_integrity.py scan-jsonl \
  --input sample.jsonl \
  --output rag-integrity-report.json \
  --fail-on high
```

The command exits `2` when a finding meets the selected threshold, `1` for an
operational or input error, and `0` otherwise. The caller owns export scope,
scheduling, and any decision to block ingestion. All containment mutations
remain outside this tool and require exact human approval.

See [SKILL.md](SKILL.md) for the complete investigation workflow and the
`references/` directory for the threat model, benchmark methodology, and
verified query patterns.
