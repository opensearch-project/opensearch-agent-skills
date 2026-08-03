# Indexing Strategies and Best Practices

## Core Concepts

OpenSearch index design directly impacts query performance, storage efficiency, and cluster stability. Proper mapping configuration, sharding strategy, and index lifecycle management form the foundation of building a high-performance search system.

## Common Issues

### Issue 1: How to Choose the Right Number of Shards

**Symptoms**:
- Poor query performance
- Unbalanced cluster load
- Cannot modify shard count after index creation

**Cause**:
The number of shards affects parallelism, resource allocation, and cluster scalability.

**Solution**:

Rule-of-thumb formula for calculating shard count:
```
Number of shards = Total data size (GB) / Target shard size (GB)
Recommended shard size: 10-50 GB
```

Set shards when creating an index:
```json
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1
  }
}
```

**Best Practices**:
- Small indexes (< 50GB): 1-3 shards
- Medium indexes (50-500GB): 3-10 shards
- Large indexes (> 500GB): 10+ shards
- Keep each shard size between 10-50GB
- Shard count should be a multiple of the number of data nodes (for even distribution)
- Avoid over-sharding which wastes resources

### Issue 2: Choosing Mapping Field Types

**Symptoms**:
- Inaccurate query results
- Wasted storage space
- Unable to perform certain types of queries

**Cause**:
Field types determine how data is stored and indexed.

**Solution**:

Common field type configurations:
```json
{
  "mappings": {
    "properties": {
      "title": {
        "type": "text",
        "analyzer": "standard",
        "fields": {
          "keyword": {
            "type": "keyword"
          }
        }
      },
      "status": {
        "type": "keyword"
      },
      "price": {
        "type": "float"
      },
      "quantity": {
        "type": "integer"
      },
      "created_at": {
        "type": "date",
        "format": "yyyy-MM-dd HH:mm:ss||epoch_millis"
      },
      "tags": {
        "type": "keyword"
      },
      "description": {
        "type": "text",
        "analyzer": "standard"
      },
      "metadata": {
        "type": "object",
        "enabled": false
      }
    }
  }
}
```

**Field Type Selection Guide**:
- `text`: Full-text search fields (tokenized)
- `keyword`: Exact match, aggregation, sorting (not tokenized)
- `integer/long`: Integers
- `float/double`: Floating-point numbers
- `date`: Date and time
- `boolean`: Boolean values
- `object`: Nested objects
- `nested`: Independently indexed nested objects (for complex queries)

**Best Practices**:
- Use `text` for fields that require full-text search
- Use `keyword` for fields that require exact matching, aggregation, or sorting
- Use multi-field to support both full-text search and exact matching simultaneously
- Set `enabled: false` for fields that don't need to be searched to save space
- Specify explicit formats for date fields
- Avoid using the `_all` field (deprecated)

### Issue 3: Dynamic Mapping vs Explicit Mapping

**Symptoms**:
- Field types don't match expectations
- Index bloat (field explosion)
- Unable to control field behavior

**Cause**:
Dynamic mapping automatically infers field types, which may not match actual requirements.

**Solution**:

1. Disable dynamic mapping (recommended for production):
```json
{
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "known_field": {
        "type": "text"
      }
    }
  }
}
```

2. Use dynamic templates:
```json
{
  "mappings": {
    "dynamic_templates": [
      {
        "strings_as_keywords": {
          "match_mapping_type": "string",
          "mapping": {
            "type": "keyword"
          }
        }
      },
      {
        "integers": {
          "match_mapping_type": "long",
          "mapping": {
            "type": "integer"
          }
        }
      }
    ]
  }
}
```

**Best Practices**:
- Use `dynamic: "strict"` in production to prevent field explosion
- Use `dynamic: true` in development for rapid iteration
- Use dynamic templates to uniformly handle unknown fields
- Regularly review mappings and remove unnecessary fields

### Issue 4: Index Aliases and Zero-Downtime Reindexing

**Symptoms**:
- Need to modify mapping but cannot do so online
- Reindexing causes service interruption
- Unable to smoothly switch indexes

**Cause**:
OpenSearch does not support modifying the type of existing fields; reindexing is required.

**Solution**:

Use index aliases for zero-downtime reindexing:

1. Create a new index:
```bash
PUT /my_index_v2
{
  "mappings": {
    "properties": {
      "field": {
        "type": "keyword"  // 新的类型
      }
    }
  }
}
```

2. Reindex the data:
```bash
POST /_reindex
{
  "source": {
    "index": "my_index_v1"
  },
  "dest": {
    "index": "my_index_v2"
  }
}
```

3. Switch the alias:
```bash
POST /_aliases
{
  "actions": [
    {
      "remove": {
        "index": "my_index_v1",
        "alias": "my_index"
      }
    },
    {
      "add": {
        "index": "my_index_v2",
        "alias": "my_index"
      }
    }
  ]
}
```

4. Delete the old index:
```bash
DELETE /my_index_v1
```

**Best Practices**:
- Always use aliases instead of directly using index names
- Use version numbers in index naming (e.g., my_index_v1)
- Use the `_reindex` API when rebuilding indexes
- Verify data integrity in the new index before switching the alias
- Keep the old index for a period of time to allow rollback

### Issue 5: Index Template Management

**Symptoms**:
- Inconsistent configuration across multiple indexes
- Tedious creation of time-series indexes
- Difficult to manage index settings uniformly

**Cause**:
Manually creating each index is error-prone and inefficient.

**Solution**:

Create an index template:
```json
{
  "index_patterns": ["logs-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "refresh_interval": "30s"
    },
    "mappings": {
      "properties": {
        "timestamp": {
          "type": "date"
        },
        "level": {
          "type": "keyword"
        },
        "message": {
          "type": "text"
        },
        "host": {
          "type": "keyword"
        }
      }
    }
  },
  "priority": 100
}
```

Apply the template:
```bash
PUT /_index_template/logs_template
{
  // Template configuration
}
```

**Best Practices**:
- Create templates for similar indexes
- Use wildcards to match index names
- Set a reasonable priority
- Use index templates + rollover strategy for time-series data
- Regularly review and update templates

## Configuration Examples

### Production Environment Index Configuration

```json
{
  "settings": {
    "number_of_shards": 5,
    "number_of_replicas": 1,
    "refresh_interval": "30s",
    "max_result_window": 10000,
    "index": {
      "codec": "best_compression",
      "mapping": {
        "total_fields": {
          "limit": 2000
        }
      }
    }
  },
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "id": {
        "type": "keyword"
      },
      "title": {
        "type": "text",
        "analyzer": "standard",
        "fields": {
          "keyword": {
            "type": "keyword",
            "ignore_above": 256
          }
        }
      },
      "content": {
        "type": "text",
        "analyzer": "standard"
      },
      "category": {
        "type": "keyword"
      },
      "tags": {
        "type": "keyword"
      },
      "price": {
        "type": "float"
      },
      "stock": {
        "type": "integer"
      },
      "created_at": {
        "type": "date",
        "format": "yyyy-MM-dd HH:mm:ss"
      },
      "updated_at": {
        "type": "date",
        "format": "yyyy-MM-dd HH:mm:ss"
      },
      "metadata": {
        "type": "object",
        "enabled": false
      }
    }
  }
}
```

### Time-Series Index Template

```json
{
  "index_patterns": ["metrics-*"],
  "template": {
    "settings": {
      "number_of_shards": 3,
      "number_of_replicas": 1,
      "refresh_interval": "5s",
      "index": {
        "lifecycle": {
          "name": "metrics_policy",
          "rollover_alias": "metrics"
        }
      }
    },
    "mappings": {
      "properties": {
        "@timestamp": {
          "type": "date"
        },
        "metric_name": {
          "type": "keyword"
        },
        "value": {
          "type": "double"
        },
        "host": {
          "type": "keyword"
        },
        "tags": {
          "type": "keyword"
        }
      }
    }
  }
}
```

## Index Lifecycle Management

### ISM Policy Example

```json
{
  "policy": {
    "description": "Hot-Warm-Delete policy",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_index_age": "1d",
              "min_primary_shard_size": "50gb"
            }
          }
        ],
        "transitions": [
          {
            "state_name": "warm",
            "conditions": {
              "min_index_age": "7d"
            }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "replica_count": {
              "number_of_replicas": 0
            }
          },
          {
            "force_merge": {
              "max_num_segments": 1
            }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": {
              "min_index_age": "30d"
            }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [
          {
            "delete": {}
          }
        ]
      }
    ]
  }
}
```

## Performance Optimization Tips

1. **Bulk Indexing**: Use the bulk API with batch sizes of 5-15MB
2. **Disable Refresh**: Set `refresh_interval: -1` during bulk imports
3. **Add Replicas Later**: Increase replica count after import is complete
4. **Use Compression**: Set `codec: best_compression` to save space
5. **Limit Field Count**: Set `mapping.total_fields.limit` to prevent field explosion

## Reference Resources

- [OpenSearch Mapping Documentation](https://opensearch.org/docs/latest/field-types/)
- [Index Settings Reference](https://opensearch.org/docs/latest/api-reference/index-apis/create-index/)
- [Index Lifecycle Management](https://opensearch.org/docs/latest/im-plugin/)
