# PPL Language Reference for Observability

## Overview

Comprehensive reference for PPL (Piped Processing Language) used by OpenSearch. Queries follow pipe-delimited syntax: `source=<index> | command1 | command2 ...`

Grammar sourced from [opensearch-project/sql](https://github.com/opensearch-project/sql) `docs/user/ppl/`.

## Field Name Escaping

Dotted field names must be backtick-quoted:

```
`attributes.gen_ai.operation.name`
`status.code`
`@timestamp`
`resource.attributes.service.name`
```

## API Endpoints

### Query

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | stats count() by serviceName"}'
```

### Explain (query plan debugging)

```bash
curl -sk -u "$OPENSEARCH_USER:$OPENSEARCH_PASSWORD" \
  -X POST "$OPENSEARCH_ENDPOINT/_plugins/_ppl/_explain" \
  -H 'Content-Type: application/json' \
  -d '{"query": "source=otel-v1-apm-span-* | where `status.code` = 2 | stats count() by serviceName"}'
```

## Core Commands

| Command | Syntax | Description |
|---|---|---|
| `source` | `source=<index>` | Start query from index pattern |
| `where` | `where <condition>` | Filter rows |
| `fields` | `fields [+\|-] <list>` | Select/exclude fields |
| `stats` | `stats <agg>... [by <field>]` | Aggregate data |
| `sort` | `sort [+\|-] <field>` | Order results (+ asc, - desc) |
| `head` | `head [N]` | Limit results (default 10) |
| `eval` | `eval <new> = <expr>` | Compute new fields |
| `dedup` | `dedup [N] <field>` | Remove duplicates |
| `rename` | `rename <old> AS <new>` | Rename fields |
| `top` | `top [N] <field>` | Most frequent values |
| `rare` | `rare <field>` | Least frequent values |

## Time-Series Commands

| Command | Syntax | Description |
|---|---|---|
| `timechart` | `timechart span=<interval> <agg> [by <field>]` | Time-bucketed aggregation |
| `span()` | `span(<field>, <interval>)` | Bucket numeric/date values |
| `trendline` | `trendline sort <field> sma(<N>, <field>)` | Moving average |
| `streamstats` | `streamstats <agg> [by <field>]` | Running statistics (⚠️ memory-intensive) |
| `eventstats` | `eventstats <agg> [by <field>]` | Add agg as field without collapsing (⚠️ memory-intensive) |

### Span Time Units

`ms`, `s`, `m`, `h`, `d`, `w`, `M`, `q`, `y`

### Timechart Rate Functions

`per_second()`, `per_minute()`, `per_hour()`, `per_day()`

## Parse/Extract Commands

| Command | Syntax | Description |
|---|---|---|
| `parse` | `parse <field> '<regex>'` | Regex extraction (⚠️ may drop fields on some versions) |
| `grok` | `grok <field> '<pattern>'` | Grok pattern extraction (⚠️ memory-intensive) |
| `rex` | `rex field=<field> '<regex>'` | Named capture groups |
| `patterns` | `patterns <field>` | Auto-discover log patterns |

## Join/Lookup Commands

| Command | Syntax | Description |
|---|---|---|
| `join` | `join left=a right=b ON a.f = b.f <index>` | Cross-index join |
| `lookup` | `lookup <index> <field> [OUTPUT <fields>]` | Enrich from another index |
| `subquery` | `where <f> IN [source=<idx> \| ... \| fields <f>]` | Nested query filter |
| `append` | `append [source=<idx> \| ...]` | Append results from another query |

> **Caveat:** Cross-index `join` may return 0 rows on OpenSearch 3.x. Use separate queries + correlate by traceId as fallback.

## Transform Commands

| Command | Description |
|---|---|
| `fillnull` | Replace nulls (⚠️ backtick fields not supported in field list) |
| `flatten` | Flatten nested fields to top-level |
| `expand` | Expand arrays into separate rows |
| `transpose` | Pivot rows into columns |

## Aggregation Functions

| Function | Description |
|---|---|
| `count()` | Count of events |
| `sum(field)` | Sum |
| `avg(field)` | Mean |
| `max(field)` / `min(field)` | Max / Min |
| `distinct_count(field)` | Count distinct values |
| `percentile(field, pct)` | Value at percentile |
| `var_samp(field)` / `stddev_samp(field)` | Sample variance / std dev |
| `earliest(field)` / `latest(field)` | First / last chronological value |
| `values(field)` | Distinct values as list |

## Condition Functions

| Function | Description |
|---|---|
| `isnull(f)` / `isnotnull(f)` | Null checks |
| `if(cond, true_val, false_val)` | Conditional |
| `case(c1, v1, c2, v2, ..., else)` | Multi-branch conditional |
| `coalesce(v1, v2, ...)` | First non-null value |
| `like` / `in` / `between` | Pattern / set / range checks |

## Conversion Functions

`cast(f AS type)`, `tostring()`, `toint()`, `tolong()`, `tofloat()`, `todouble()`

Types: STRING, INT, LONG, FLOAT, DOUBLE, BOOLEAN, DATE, TIMESTAMP

## Datetime Functions

| Function | Description |
|---|---|
| `now()` | Current timestamp |
| `date_format(date, fmt)` | Format date (`%Y-%m-%d %H:%i:%s`) |
| `date_add(date, INTERVAL n unit)` | Add interval |
| `date_sub(date, INTERVAL n unit)` | Subtract interval |
| `datediff(d1, d2)` | Difference in days |
| `day()`, `month()`, `year()`, `hour()`, `minute()`, `second()` | Extract components |

## String Functions

| Function | Description |
|---|---|
| `concat(s1, s2, ...)` | Concatenate |
| `length(s)` / `lower(s)` / `upper(s)` / `trim(s)` | Basic string ops |
| `substring(s, start, len)` | Extract substring |
| `replace(s, from, to)` | Replace occurrences |
| `regexp_extract(s, pattern, group)` | Regex capture group |
| `regexp_replace(s, pattern, repl)` | Regex replace |

## Relevance Functions

| Function | Description |
|---|---|
| `match(field, query)` | Full-text match |
| `match_phrase(field, phrase)` | Exact phrase match |
| `multi_match([f1, f2], query)` | Match across fields |
| `query_string([f1, f2], query)` | Lucene query syntax |
| `wildcard_query(field, pattern)` | Wildcard match (`*`, `?`) |

## Math Functions

`abs()`, `ceil()`, `floor()`, `round(val, decimals)`, `sqrt()`, `pow()`, `mod()`, `log()`, `log10()`, `exp()`

## ML Commands

| Command | Description |
|---|---|
| `ad` | Anomaly detection (auto-detects input fields from pipeline) |
| `kmeans` | K-means clustering (operates on all numeric fields) |

> `ml action=rcf` is not valid in OpenSearch 3.x. Use `ad` command directly.

## System Commands

| Command | Description |
|---|---|
| `describe <index>` | Inspect index mapping and field types |
| `show datasources` | List configured data sources |

## Observability Examples

### Error rate by service over time

```
source=otel-v1-apm-span-* | stats count() as total, sum(case(`status.code` = 2, 1 else 0)) as errors by span(startTime, 1h), serviceName
```

### Duration in milliseconds with percentiles

```
source=otel-v1-apm-span-* | eval duration_ms = durationInNanos / 1000000 | stats avg(duration_ms) as avg_ms, percentile(duration_ms, 95) as p95_ms by serviceName
```

### Log pattern discovery

```
source=logs-otel-v1-* | where severityText = 'ERROR' | patterns body | fields body, patterns_field | head 20
```

### Recent spans with time filter

```
source=otel-v1-apm-span-* | where startTime > DATE_SUB(NOW(), INTERVAL 1 HOUR) | stats count() by serviceName
```

## Looking Up PPL Documentation

This reference covers the most common commands and functions. If a PPL command isn't listed here, a query fails with a syntax error, or you need to check version-specific behavior:

1. Search OpenSearch docs:
   ```bash
   uv run python scripts/opensearch_ops.py search-docs --query "PPL <command_name> syntax"
   ```

2. Search specifically for PPL grammar:
   ```bash
   uv run python scripts/opensearch_ops.py search-docs --query "site:opensearch.org PPL <command_name>"
   ```

3. If a web search tool is available, search directly:
   ```
   site:opensearch.org PPL <command_name> command
   ```

4. The canonical PPL grammar source is the [opensearch-project/sql](https://github.com/opensearch-project/sql) repository under `docs/user/ppl/`. Fetch the relevant page if you need exact syntax for a specific command.

Always verify PPL syntax against the docs when a query returns an error — syntax can vary between OpenSearch versions.