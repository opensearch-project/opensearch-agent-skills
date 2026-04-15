# Asynchronous Search

The Asynchronous Search plugin lets you run long-running search queries in the background and retrieve results later. This is useful for expensive queries (large aggregations, complex analytics) that would otherwise time out.

## Key Concepts

- **Async search request** — Submit a search query that runs asynchronously. Returns an ID immediately that you use to check status and retrieve results.
- **Search ID** — A unique identifier for the async search. Used to poll for results, get partial results, or delete the search.
- **Partial results** — Async search can return intermediate results as shards complete, so you can see progress before the full query finishes.
- **Keep alive** — How long the async search results are retained after completion. Default is 5 days. Extendable via the API.
- **Completion** — When all shards have responded, the search is marked complete and the full results are available.
- **Monitoring** — Check the status of running async searches (running, completed, failed) via the stats API.
- **Deletion** — Explicitly delete an async search to free resources before the keep-alive expires.

## Common Use Cases

- Running large aggregation queries across months or years of data
- Complex analytics queries that exceed the default search timeout
- Scheduled background analytics where results are consumed later
- Queries across very large indices where shard responses are slow

## Official Documentation

- [Asynchronous search overview](https://docs.opensearch.org/latest/search-plugins/async/index/)
- [API reference](https://docs.opensearch.org/latest/search-plugins/async/api/)
- [Settings reference](https://docs.opensearch.org/latest/search-plugins/async/settings/)
- [Security](https://docs.opensearch.org/latest/search-plugins/async/security/)
