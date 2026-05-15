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

> `_explain` accepts an optional `mode` (`standard` / `simple` / `cost` / `extended`). `simple`, `cost`, and `extended` require the v3 engine (`plugins.calcite.enabled=true`); `standard` works on both v2 and v3.

## Core Commands

| Command | Syntax | Description |
|---|---|---|
| `source` | `source=<index>` | Start query from index pattern |
| `search` | `search source=<index> [<expr>]` | Alternative first command; supports search-expression syntax (`field=value`, `AND/OR/NOT`, time modifiers) |
| `where` | `where <condition>` | Filter rows |
| `regex` | `regex <field> = '<pattern>'` (or `!=`) | Filter rows by Java regex on a field |
| `fields` | `fields [+\|-] <list>` | Select/exclude fields |
| `table` | `table [+\|-] <list>` | Alias for `fields` (SPL ergonomics) |
| `stats` | `stats <agg>... [by <field>]` | Aggregate data |
| `sort` | `sort [+\|-] <field>` | Order results (+ asc, - desc) |
| `reverse` | `reverse` | Reverse result order (⚠️ no-op without preceding `sort` or `@timestamp`; collation-destroying ops like `stats`/`join` make it a no-op) |
| `head` | `head [N]` | Limit results (default 10) |
| `eval` | `eval <new> = <expr>` | Compute new fields |
| `fieldformat` | `fieldformat <field>=[(prefix).]<expr>[.(suffix)]` | `eval` alias with prefix/suffix string concat for display |
| `dedup` | `dedup [N] <field>` | Remove duplicates |
| `rename` | `rename <old> AS <new>` | Rename fields |
| `replace` | `replace '<pat>' WITH '<repl>' IN <field>` | Literal/wildcard string replace in fields (supports `*`) |
| `convert` | `convert <fn>(<field>) [AS <field>]` | Type-coerce fields (`auto()`, `num()`, `mktime()`, `ctime()`, `dur2sec()`, `mstime()`, `memk()`, `rmcomma()`, `rmunit()`, `none()`) |
| `top` | `top [N] <field>` | Most frequent values |
| `rare` | `rare <field>` | Least frequent values |

## Time-Series Commands

| Command | Syntax | Description |
|---|---|---|
| `bin` | `bin <field> [span=<int>] [bins=<n>] [minspan=<int>] [aligntime=...] [start=<v>] [end=<v>]` | Bucket numeric/time values into equal-width bins (⚠️ `bins=` on timestamps requires `plugins.calcite.pushdown.enabled=true` *and* the binned field must be in a `stats` aggregation; otherwise use `span=`) |
| `timechart` | `timechart span=<interval> <agg> [by <field>]` | Time-bucketed aggregation |
| `chart` | `chart <agg> [by <row> <col>] \| [over <row> [by <col>]] [limit=topN] [useother=<bool>] [usenull=<bool>]` | Aggregate + pivot (row split × column split) for 2D charts |
| `span()` | `span(<field>, <interval>)` | Bucket numeric/date values |
| `trendline` | `trendline sort <field> sma(<N>, <field>)` | Moving average |
| `streamstats` | `streamstats <agg> [by <field>]` | Running statistics (⚠️ memory-intensive) |
| `eventstats` | `eventstats <agg> [by <field>]` | Add agg as field without collapsing (⚠️ memory-intensive) |

### Span Time Units

`ms`, `s`, `m`, `h`, `d`, `w`, `M`, `q`, `y`. The `bin` command also accepts `us`, `cs`, `ds`, plus longhand forms (`sec`, `seconds`, `min`, `minutes`, `hr`, `hours`, etc.).

### Timechart Rate Functions

`per_second()`, `per_minute()`, `per_hour()`, `per_day()`

## Parse/Extract Commands

| Command | Syntax | Description |
|---|---|---|
| `parse` | `parse <field> '<regex>'` | Regex extraction (⚠️ may drop fields on some versions) |
| `grok` | `grok <field> '<pattern>'` | Grok pattern extraction (⚠️ memory-intensive) |
| `rex` | `rex field=<field> '<regex>'` | Named capture groups |
| `patterns` | `patterns <field>` | Auto-discover log patterns |
| `spath` | `spath input=<field> [output=<field>] [path=<path>]` | Extract from structured JSON (path-based or auto-extract) (⚠️ runs on coordinator node — slow on large datasets; prefer indexing fields directly) |

## Join/Lookup/Set Commands

| Command | Syntax | Description |
|---|---|---|
| `join` | `join left=a right=b ON a.f = b.f <index>` | Cross-index join |
| `lookup` | `lookup <index> <field> [OUTPUT <fields>]` | Enrich from another index |
| `subquery` | `where <f> IN [source=<idx> \| ... \| fields <f>]` | Nested query filter |
| `union` | `union [maxout=<n>] <ds1> <ds2> [...]` | UNION ALL across datasets/subsearches; auto type-coerces conflicting schemas |
| `multisearch` | `multisearch [<sub1>] [<sub2>] [...]` | Run + merge subsearches; supports timestamp-based interleaving |
| `append` | `append [source=<idx> \| ...]` | Append results from another query |
| `appendcol` | `appendcol [override=<bool>] [<subsearch>]` | Append subsearch result as additional **columns** |
| `appendpipe` | `appendpipe [<subpipeline>]` | Append subpipeline results to main results (subpipeline runs lazily) |
| `graphLookup` | `graphLookup <idx> start=<expr> edge=<from><op><to> [maxDepth=<n>] ... as <out>` | (Experimental) Recursive BFS graph traversal |

> **Caveat:** Cross-index `join` may return 0 rows on OpenSearch 3.x. Use separate queries + correlate by traceId as fallback.

## Transform Commands

| Command | Description |
|---|---|
| `fillnull` | Replace nulls (⚠️ backtick fields not supported in field list) |
| `flatten` | Flatten nested fields to top-level |
| `expand` | Expand arrays into separate rows |
| `mvexpand` | Expand each value of a multivalue (array) field into a separate row (`mvexpand <field> [limit=<n>]`) |
| `mvcombine` | Group rows identical except for target field; combine target into multivalue array |
| `nomv` | Convert multivalue field to single-value string (joined by `\n`) |
| `transpose` | Pivot rows into columns |
| `addtotals` | `addtotals [field-list] [row=<bool>] [col=<bool>] [label=<s>] [labelfield=<f>] [fieldname=<f>]` — row/column totals (numeric fields only) |
| `addcoltotals` | Column-only totals; equivalent to `addtotals row=false col=true` |

## Aggregation Functions

| Function | Description |
|---|---|
| `count()` | Count of events |
| `sum(field)` | Sum |
| `avg(field)` | Mean |
| `max(field)` / `min(field)` | Max / Min (aggregate context) |
| `distinct_count(field)` | Count distinct values |
| `percentile(field, pct)` | Value at percentile |
| `var_samp(field)` / `stddev_samp(field)` | Sample variance / std dev |
| `earliest(field)` / `latest(field)` | First / last chronological value |
| `values(field)` | Distinct values as list |

## Statistical Functions (eval-context, scalar)

> ⚠️ **Distinct from aggregates.** These take N arguments and return a single value within `eval` — they do **not** aggregate across rows. Use aggregate `max(field)` / `min(field)` inside `stats`.

| Function | Description |
|---|---|
| `MAX(x, y, ...)` | Largest of the supplied arguments (strings rank greater than numbers; for strings, lexicographic comparison) |
| `MIN(x, y, ...)` | Smallest of the supplied arguments |

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

## Collection Functions (multivalue / array)

| Function | Description |
|---|---|
| `array(v1, v2, ...)` | Construct an array; mixed types coerced to least-restrictive type |
| `array_length(arr)` | Number of elements |
| `mvjoin(arr, sep)` | Join multivalue field with separator |
| `mvfilter(expr)` | Keep only elements matching the expression |
| `mvindex(arr, start [, end])` | Element at index (or slice) |
| `mvappend(v1, v2, ...)` | Concatenate values into one multivalue |

## JSON Functions

> **JSON path notation:** `<key1>{<idx1>}.<key2>{<idx2>}...`. `{}` (no index) means *all elements* in the array at that level (wildcard).

| Function | Description |
|---|---|
| `json(value)` | Validate + parse a JSON string; returns `NULL` if invalid |
| `json_extract(json, path)` | Extract value at JSON path |
| `json_array(v1, v2, ...)` | Construct a JSON array |
| `json_object(k1, v1, k2, v2, ...)` | Construct a JSON object |
| `json_keys(json)` | Return array of top-level keys |

## IP Functions

| Function | Description |
|---|---|
| `cidrmatch(ip, cidr)` | True if `ip` falls within the CIDR range (IPv4 or IPv6) |
| `geoip(ip)` | Geographic enrichment (where supported) |

## Cryptographic Functions

`md5(str)`, `sha1(str)`, `sha2(str, bits)` — return hex-encoded digest as STRING.

## System Functions

| Function | Description |
|---|---|
| `typeof(expr)` | Returns the data type of the expression as a STRING (useful for debugging) |

## Expressions & Operators

Arithmetic: `+`, `-`, `*`, `/`, `%`. Use parentheses to control precedence.

> ⚠️ **Division behavior depends on cluster setting.** When `plugins.ppl.syntax.legacy.preferred=true` (default), integer / integer is *truncated*. When `false`, operands are promoted to floating-point and the fractional part is preserved. **Division by zero returns `NULL`, not an error.**
>
> ⚠️ **Modulo (`%`) is integer-only.** Applying `%` to floats raises a type error.

Implicit type coercion follows function-signature matching (e.g., `int + double` resolves to `+(double, double)` and returns `double`).

## ML Commands

| Command | Description |
|---|---|
| `ad` | Anomaly detection (auto-detects input fields from pipeline) |
| `kmeans` | K-means clustering (operates on all numeric fields) |

> `ml action=rcf` is not valid in OpenSearch 3.x. Use `ad` command directly.

## System / Inspection Commands

| Command | Description |
|---|---|
| `describe <index>` | Inspect index mapping and field types |
| `show datasources` | List configured data sources |
| `explain [<mode>] <query>` | Display execution plan (must be the first command). `mode` ∈ `standard` (default) / `simple` / `cost` / `extended`. Non-`standard` modes require v3 engine. |

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

> **PPL syntax varies between OpenSearch versions.** The `opensearch-project/sql` repository is the canonical grammar source — always verify upstream when a query returns an error or when the user's cluster version differs from this cheatsheet's reference state.

This reference covers common commands and functions. **If a command or function isn't listed here, the canonical bleeding-edge source is the [opensearch-project/sql](https://github.com/opensearch-project/sql) repository under `docs/user/ppl/`.** Fetch the raw markdown directly:

- **Commands:** `https://raw.githubusercontent.com/opensearch-project/sql/main/docs/user/ppl/cmd/<command>.md`
- **Functions:** `https://raw.githubusercontent.com/opensearch-project/sql/main/docs/user/ppl/functions/<category>.md`
  Categories: `aggregations`, `collection`, `condition`, `conversion`, `cryptographic`, `datetime`, `expressions`, `ip`, `json`, `math`, `relevance`, `statistical`, `string`, `system`.

**The agent MUST consult this upstream source if:**

- The command/function isn't in this cheatsheet.
- A query the agent emitted fails with a syntax error.
- The user asks about behavior that may be version-specific.

Always prefer the upstream `opensearch-project/sql` source over `opensearch.org` documentation pages, which may trail the SQL repo by one or more releases.

Secondary fallbacks (only if the upstream raw URL is unreachable):

```bash
uv run python scripts/opensearch_ops.py search-docs --query "PPL <command_name> syntax"
```

Or a web search scoped to `site:opensearch.org PPL <command_name>`.

## Verifying Queries Against a Cluster

When a cluster endpoint is available (provided by the user, configured via `OPENSEARCH_URL`, or wired via the `opensearch-mcp-server` MCP), every PPL query the agent emits **must** be verified before being returned to the user. Use a **best-effort cascade**:

1. **Execute via `_plugins/_ppl`** and capture row count and any error.
2. **If the query succeeds but returns 0 rows** (target index empty or filter overly strict), fall back to **`_plugins/_ppl/_explain`** to confirm the plan parses and resolves field references. Surface the empty-result observation to the user along with the validated query.
3. **If `_plugins/_ppl` errors**, fix the query (consult upstream docs as needed) and re-validate. Do not return unverified PPL.
4. **If no endpoint is available**, state explicitly that the query is unverified and recommend the user run `_explain` against their cluster before relying on it.
