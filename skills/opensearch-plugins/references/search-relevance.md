# Search Relevance

The Search Relevance plugin provides tools for evaluating and comparing search quality. It includes a query comparison tool in OpenSearch Dashboards and APIs for running search quality evaluations.

## Key Concepts

- **Compare Search Results** — A Dashboards tool that lets you run two queries side by side against the same index and visually compare the results. Useful for A/B testing query configurations.
- **Search evaluation** — Programmatic evaluation of search quality using relevance metrics (nDCG, precision, MRR) against judgment lists.
- **Judgment list** — A set of query-document relevance ratings used to evaluate search quality. Can be human-labeled or generated.
- **nDCG (Normalized Discounted Cumulative Gain)** — A ranking metric that measures how well search results are ordered by relevance.
- **Precision@k** — The fraction of relevant documents in the top-k results.
- **MRR (Mean Reciprocal Rank)** — The average of the reciprocal rank of the first relevant result across queries.

## Common Use Cases

- Comparing BM25 vs. hybrid search quality on the same dataset
- Evaluating the impact of query changes or pipeline modifications
- Building judgment lists and running offline relevance evaluations
- Tracking search quality metrics over time

## Tutorials

- [Optimizing hybrid search](https://docs.opensearch.org/latest/tutorials/search-plugins/search-relevance/optimizing-hybrid-search/) — Tuning normalization and combination for hybrid queries
- [Search Relevance Workbench](https://docs.opensearch.org/latest/search-plugins/search-relevance/using-search-relevance-workbench/) — Interactive query comparison UI (links to query rewriting, Learning to Rank, and more)

## Official Documentation

- [Search relevance overview](https://docs.opensearch.org/latest/search-plugins/search-relevance/index/)
- [Compare search results](https://docs.opensearch.org/latest/search-plugins/search-relevance/compare-search-results/)
- [Search evaluation](https://docs.opensearch.org/latest/search-plugins/search-relevance/search-evaluation/)
