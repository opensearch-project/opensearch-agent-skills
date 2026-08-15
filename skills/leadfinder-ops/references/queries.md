# Query Reference — LeadFinder Ops

Full OpenSearch DSL used by `scripts/leadsearch.py`, for agents that need to
compose their own queries.

## 1. Unanswered-leads query (the money query)

Every lead with no `responded_at`, oldest first:

```json
POST /leads/_search
{
  "size": 50,
  "sort": [{"received_at": "asc"}],
  "query": {
    "bool": {
      "must": [
        {"range": {"received_at": {"gte": "now-30d/d"}}},
        {"bool": {"must_not": {"exists": {"field": "responded_at"}}}}
      ]
    }
  }
}
```

Add `{"term": {"category": "urgent"}}` to `must` for the emergency-only view.

## 2. Hybrid semantic search (BM25 + k-NN)

Requires `message_embedding` populated (384-dim; e.g., all-MiniLM-L6-v2).
Combine lexical + vector scores with a `should` clause and normalize:

```json
POST /leads/_search
{
  "size": 10,
  "query": {
    "bool": {
      "should": [
        {"match": {"message": {"query": "water heater quote", "boost": 1.0}}},
        {"knn": {"message_embedding": {"vector": <384-dim>, "k": 10}}}
      ],
      "minimum_should_match": 1
    }
  }
}
```

The CLI ships BM25-only by default (no embedding service dependency); swap in
the `knn` clause when embeddings are ingested.

## 3. Aging buckets — which cohort to re-engage first

```json
POST /leads/_search
{
  "size": 0,
  "query": {"range": {"received_at": {"gte": "now-90d/d"}}},
  "aggs": {
    "age_cohorts": {
      "range": {
        "field": "received_at",
        "ranges": [
          {"to": "now-60d"}, {"from": "now-60d", "to": "now-30d"},
          {"from": "now-30d", "to": "now-7d"}, {"from": "now-7d"}
        ]
      },
      "aggs": {
        "unanswered": {"filter": {"bool": {"must_not": {"exists": {"field": "responded_at"}}}}}
      }
    }
  }
}
```

## 4. Spam filter for recovery lists

Exclude obvious spam before drafting replies:

```json
{"bool": {"must_not": [{"term": {"category": "spam"}}]}}
```

## 5. Speed-to-lead metric (responded within 5 minutes?)

```json
POST /leads/_search
{
  "size": 0,
  "query": {"range": {"received_at": {"gte": "now-30d/d"}}},
  "aggs": {
    "responded": {
      "filter": {"exists": {"field": "responded_at"}},
      "aggs": {
        "within_5m": {
          "range": {
            "field": "responded_at",
            "script": {"source": "doc['responded_at'].value.toInstant().toEpochMilli() - doc['received_at'].value.toInstant().toEpochMilli()"},
            "ranges": [{"to": 300000}]
          }
        }
      }
    }
  }
}
```

## Index mapping notes

- `message_embedding` uses `nmslib` hnsw cosinesimil; switch `engine` to
  `faiss` if your cluster build favors it.
- `responded_at` null-means-unanswered is the core invariant — never write
  `responded_at` until a human-confirmed response exists.
- Keep `contact` as `keyword` (exact match for callbacks), `message` as `text`
  (analyzed for BM25).
