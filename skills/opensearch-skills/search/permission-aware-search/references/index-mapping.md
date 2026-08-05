# Index Mapping Reference

## Content Index: `<index>` (default: `permission-aware-search`)

### Combined BM25 + kNN Mode

```json
{
  "settings": {
    "index": {
      "knn": true,
      "knn.algo_param.ef_search": 100
    }
  },
  "mappings": {
    "properties": {
      "title":          { "type": "text", "analyzer": "english" },
      "content":        { "type": "text", "analyzer": "english" },
      "content_vector": {
        "type": "knn_vector",
        "dimension": 384,
        "method": { "engine": "faiss", "name": "hnsw", "space_type": "l2" }
      },
      "allowed_users":  { "type": "keyword" },
      "path":           { "type": "keyword" },
      "source_file":    { "type": "keyword" },
      "chunk_id":       { "type": "integer" },
      "metadata":       { "type": "object", "enabled": false }
    }
  }
}
```

**Dimension note:** 384 matches `sentence-transformers/all-MiniLM-L6-v2`.
Adjust for other models:

| Model | Dimension |
|-------|-----------|
| `all-MiniLM-L6-v2` | 384 |
| `all-mpnet-base-v2` | 768 |
| `amazon.titan-embed-text-v2:0` (Bedrock) | 1024 |

### BM25-only Mode (embedding: `none`)

Same mapping but omit `content_vector` and set `"knn": false`.

## ACL Lookup Alias: `<index>-acl` (default: `permission-aware-search-acl`)

This stable administrative alias points to one versioned backing index named
`<index>-acl-<version>` with the following mapping:

```json
{
  "settings": { "index": { "number_of_shards": 1 } },
  "mappings": {
    "properties": {
      "allowed_users": { "type": "keyword" }
    }
  }
}
```

Documents are keyed by username (`_id`). Example:

```json
{ "_id": "alice", "allowed_users": ["alice", "GROUP_Finance", "GROUP_Everyone"] }
```

The DLS Terms Lookup targets the active concrete backing because the Security
plugin does not resolve an alias in this DLS expression. Keep each snapshot small
and fast - one document per user. `sync-acl` and `refresh-acl` build a complete
replacement, update the role, and rotate the alias, so never write to a backing
index directly.

## `allowed_users` Field - Content Side

`allowed_users` on a content document is the union of all principals with at
least READ access to that document:

```json
{ "allowed_users": ["alice", "bob", "GROUP_Finance", "GROUP_Everyone"] }
```

Rules:
- Include individual usernames AND group names.
- Use the same string format in both content documents and ACL lookup documents.
- For "world-readable" documents, include a sentinel like `GROUP_Everyone` or
  `group:everyone` and add that sentinel to every user's ACL document.
- Never leave `allowed_users` empty - an empty array means no one can read the document.

## Chunk Strategy

Long documents are split into overlapping chunks. Each chunk is a separate
OpenSearch document sharing the same `path` and `source_file` (and therefore the
same `allowed_users`). `chunk_id` (0-based) distinguishes chunks within one source.

Default: 512 words per chunk, 64-word overlap. Override with `--chunk-size` and
`--chunk-overlap`, or the matching `PERMISSION_SEARCH_*` environment variables.
