# OpenSearch Query Patterns

Use these only after mapping and plugin discovery. Replace every placeholder
with a value verified from the target cluster.

## Neural Neighbor Expansion

OpenSearch's `neural` query converts `query_text` with a deployed model and
searches the configured embedding field.

```json
GET /<index>/_search
{
  "_source": {
    "excludes": ["<embedding-field>"]
  },
  "size": 20,
  "query": {
    "bool": {
      "must": [
        {
          "neural": {
            "<embedding-field>": {
              "query_text": "<bounded suspicious seed text>",
              "model_id": "<deployed-model-id>",
              "k": 20
            }
          }
        }
      ],
      "must_not": [
        {
          "ids": {
            "values": ["<seed-document-id>"]
          }
        }
      ]
    }
  }
}
```

Reference:
https://docs.opensearch.org/latest/vector-search/searching-data/

## Hybrid Candidate Search

A hybrid query can combine exact instruction markers with semantic similarity.
It requires a compatible search pipeline for score normalization.

```json
POST /<index>/_search?search_pipeline=<verified-pipeline>
{
  "_source": {
    "excludes": ["<embedding-field>"]
  },
  "size": 50,
  "query": {
    "hybrid": {
      "queries": [
        {
          "multi_match": {
            "query": "ignore previous instructions system prompt",
            "fields": ["<text-field>"]
          }
        },
        {
          "neural": {
            "<embedding-field>": {
              "query_text": "<confirmed poisoned seed text>",
              "model_id": "<deployed-model-id>",
              "k": 50
            }
          }
        }
      ]
    }
  }
}
```

Reference:
https://docs.opensearch.org/latest/query-dsl/compound/hybrid/

## Exact Evidence Retrieval

Retrieve exact IDs when a report must be verified. Avoid broad search results
when taking containment decisions.

```json
GET /<index>/_mget
{
  "ids": ["<document-id-1>", "<document-id-2>"]
}
```

## Ingest Fingerprinting

OpenSearch provides an ingest `fingerprint` processor. A future approved
pipeline can populate a checksum at ingestion, but the sentinel must first
inspect available processors and test the pipeline with `_simulate`.

```json
GET /_nodes/ingest?filter_path=nodes.*.ingest.processors
```

Reference:
https://docs.opensearch.org/latest/ingest-pipelines/processors/index-processors/

Do not create or attach a fingerprint pipeline during the read-only
investigation.
