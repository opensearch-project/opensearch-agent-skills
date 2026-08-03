# Query Optimization Techniques

## Core Concepts

OpenSearch query performance optimization involves query structure design, cache utilization, aggregation optimization, and pagination strategies. Understanding the difference between query context and filter context is key to optimization.

## Common Issues

### Issue 1: Query Context vs Filter Context

**Symptoms**:
- Slow query speed
- Cache not taking effect
- Unnecessary relevance score calculations

**Cause**:
Query context calculates relevance scores, while filter context only performs boolean matching and can be cached.

**Solution**:

Use filter context for exact matching:
```json
{
  "query": {
    "bool": {
      "must": [
        {
          "match": {
            "title": "machine learning"
          }
        }
      ],
      "filter": [
        {
          "term": {
            "status": "published"
          }
        },
        {
          "range": {
            "price": {
              "gte": 10,
              "lte": 100
            }
          }
        }
      ]
    }
  }
}
```

**Comparison**:
```json
// Slow - using must (calculates scores)
{
  "query": {
    "bool": {
      "must": [
        {"term": {"status": "published"}},
        {"range": {"price": {"gte": 10}}}
      ]
    }
  }
}

// Fast - using filter (no score calculation, cacheable)
{
  "query": {
    "bool": {
      "filter": [
        {"term": {"status": "published"}},
        {"range": {"price": {"gte": 10}}}
      ]
    }
  }
}
```

**Best Practices**:
- Use `filter` for exact matching (term, range, exists)
- Use `must` for full-text search (match, multi_match)
- Use `must_not` for exclusion conditions
- Filter queries are automatically cached
- Place filters in the filter clause of a bool query

### Issue 2: Deep Pagination Performance Problems

**Symptoms**:
- Queries slow down when navigating to later pages
- High memory usage
- Query timeouts

**Cause**:
When using from/size pagination, results must be sorted and preceding results skipped on every shard.

**Solution**:

1. Use search_after instead of from/size:
```json
// First query
{
  "size": 10,
  "query": {
    "match_all": {}
  },
  "sort": [
    {"timestamp": "desc"},
    {"_id": "asc"}
  ]
}

// Subsequent queries
{
  "size": 10,
  "query": {
    "match_all": {}
  },
  "search_after": [1609459200000, "doc_123"],
  "sort": [
    {"timestamp": "desc"},
    {"_id": "asc"}
  ]
}
```

2. Use the scroll API (suitable for exporting large volumes of data):
```json
// Initialize scroll
POST /my_index/_search?scroll=1m
{
  "size": 1000,
  "query": {
    "match_all": {}
  }
}

// Get next batch
POST /_search/scroll
{
  "scroll": "1m",
  "scroll_id": "DXF1ZXJ5QW5kRmV0Y2gBAAAAAAAAAD4WYm9laVYtZndUQlNsdDcwakFMNjU1QQ=="
}
```

3. Limit max_result_window:
```json
{
  "settings": {
    "max_result_window": 10000
  }
}
```

**Best Practices**:
- Avoid using from > 10000
- Use search_after for real-time pagination
- Use the scroll API for bulk exports
- Provide "next page" instead of "jump to page N"
- Use a unique field (e.g., _id) as the last sort field

### Issue 3: Aggregation Query Optimization

**Symptoms**:
- Slow aggregation queries
- High memory usage
- Inaccurate results (approximate values)

**Cause**:
Aggregations need to process large amounts of data in memory.

**Solution**:

1. Use filters to reduce the volume of data being aggregated:
```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        {
          "range": {
            "timestamp": {
              "gte": "2024-01-01"
            }
          }
        }
      ]
    }
  },
  "aggs": {
    "categories": {
      "terms": {
        "field": "category",
        "size": 10
      }
    }
  }
}
```

2. Use composite aggregation for pagination:
```json
{
  "size": 0,
  "aggs": {
    "my_buckets": {
      "composite": {
        "size": 100,
        "sources": [
          {"category": {"terms": {"field": "category"}}},
          {"date": {"date_histogram": {"field": "timestamp", "calendar_interval": "day"}}}
        ]
      }
    }
  }
}
```

3. Adjust precision parameters:
```json
{
  "aggs": {
    "categories": {
      "terms": {
        "field": "category",
        "size": 10,
        "shard_size": 50,  // Increase the number of buckets at the shard level
        "show_term_doc_count_error": true
      }
    }
  }
}
```

**Best Practices**:
- Set `size: 0` to return only aggregation results without documents
- Use filters to narrow data before aggregating
- Use composite aggregation for high-cardinality fields
- Adjust `shard_size` to improve accuracy
- Use `execution_hint: map` to optimize memory usage
- Avoid deeply nested aggregations (< 3 levels)

### Issue 4: Caching Strategies

**Symptoms**:
- Identical queries are repeatedly slow
- Low cache hit rate
- Unreasonable memory usage

**Cause**:
OpenSearch's multi-level caching mechanism is not being fully utilized.

**Solution**:

1. Enable request cache (for aggregation queries):
```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        {"term": {"status": "published"}}
      ]
    }
  },
  "aggs": {
    "categories": {
      "terms": {"field": "category"}
    }
  }
}
```

2. Use query cache (for filter queries):
```json
{
  "query": {
    "bool": {
      "filter": [
        {"term": {"status": "published"}}  // Automatically cached
      ]
    }
  }
}
```

3. Configure cache size:
```json
{
  "settings": {
    "index.queries.cache.enabled": true,
    "index.requests.cache.enable": true
  }
}
```

4. Monitor cache effectiveness:
```bash
GET /_stats/request_cache,query_cache
```

**Best Practices**:
- Filter queries automatically use the query cache
- Aggregation queries use the request cache (size=0)
- Queries using `now` are not cached; use `now/d` to round down
- Regularly monitor cache hit rates and eviction rates
- Set cache size appropriately (default is 10% of heap memory)

### Issue 5: Multi-Field Search Optimization

**Symptoms**:
- Slow multi-field searches
- Suboptimal relevance ranking
- Complex and hard-to-maintain queries

**Cause**:
Searching across multiple fields and merging results is required.

**Solution**:

1. Use multi_match:
```json
{
  "query": {
    "multi_match": {
      "query": "machine learning",
      "fields": ["title^3", "content", "tags^2"],
      "type": "best_fields",
      "tie_breaker": 0.3
    }
  }
}
```

2. Use bool query combinations:
```json
{
  "query": {
    "bool": {
      "should": [
        {
          "match": {
            "title": {
              "query": "machine learning",
              "boost": 3
            }
          }
        },
        {
          "match": {
            "content": "machine learning"
          }
        }
      ],
      "minimum_should_match": 1
    }
  }
}
```

3. Use copy_to fields:
```json
{
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "copy_to": "full_text"
      },
      "content": {
        "type": "text",
        "copy_to": "full_text"
      },
      "full_text": {
        "type": "text"
      }
    }
  }
}

// Query
{
  "query": {
    "match": {
      "full_text": "machine learning"
    }
  }
}
```

**Best Practices**:
- Use `^` to set field weights (boost)
- `best_fields`: Best field matching (default)
- `most_fields`: Multi-field matching
- `cross_fields`: Cross-field matching (suitable for name searches)
- Use `tie_breaker` to factor in scores from other fields
- For fixed multi-field searches, use copy_to to simplify queries

## Configuration Examples

### High-Performance Query Template

```json
{
  "size": 20,
  "from": 0,
  "query": {
    "bool": {
      "must": [
        {
          "multi_match": {
            "query": "{{search_term}}",
            "fields": ["title^3", "content"],
            "type": "best_fields"
          }
        }
      ],
      "filter": [
        {
          "term": {
            "status": "published"
          }
        },
        {
          "range": {
            "created_at": {
              "gte": "{{start_date}}",
              "lte": "{{end_date}}"
            }
          }
        }
      ]
    }
  },
  "sort": [
    {"_score": "desc"},
    {"created_at": "desc"}
  ],
  "_source": ["title", "summary", "created_at"],
  "highlight": {
    "fields": {
      "title": {},
      "content": {
        "fragment_size": 150,
        "number_of_fragments": 3
      }
    }
  }
}
```

### Aggregation Query Template

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        {
          "range": {
            "timestamp": {
              "gte": "now-7d/d",
              "lte": "now/d"
            }
          }
        }
      ]
    }
  },
  "aggs": {
    "daily_stats": {
      "date_histogram": {
        "field": "timestamp",
        "calendar_interval": "day"
      },
      "aggs": {
        "total_amount": {
          "sum": {
            "field": "amount"
          }
        },
        "avg_amount": {
          "avg": {
            "field": "amount"
          }
        }
      }
    },
    "top_categories": {
      "terms": {
        "field": "category",
        "size": 10,
        "order": {"_count": "desc"}
      }
    }
  }
}
```

## Performance Monitoring

### Slow Query Logs

Configure slow query thresholds:
```json
{
  "settings": {
    "index.search.slowlog.threshold.query.warn": "10s",
    "index.search.slowlog.threshold.query.info": "5s",
    "index.search.slowlog.threshold.query.debug": "2s",
    "index.search.slowlog.threshold.fetch.warn": "1s"
  }
}
```

View slow query logs:
```bash
tail -f /var/log/opensearch/my-cluster_index_search_slowlog.log
```

### Query Performance Analysis

Use the profile API:
```json
{
  "profile": true,
  "query": {
    "match": {
      "title": "machine learning"
    }
  }
}
```

### Key Metrics

- Query latency: < 100ms (simple queries), < 500ms (complex queries)
- Cache hit rate: > 80%
- Slow query count: < 1%
- Aggregation queries: < 1s

## Reference Resources

- [OpenSearch Query DSL](https://opensearch.org/docs/latest/query-dsl/)
- [Performance Tuning Guide](https://opensearch.org/docs/latest/tuning-your-cluster/)
- [Cache Mechanism Details](https://opensearch.org/docs/latest/api-reference/index-apis/clear-cache/)
