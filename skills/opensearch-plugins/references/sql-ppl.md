# SQL and PPL

The SQL/PPL plugin lets you query OpenSearch using familiar SQL syntax or Piped Processing Language (PPL). It translates SQL and PPL queries into OpenSearch DSL queries, making OpenSearch accessible to users who prefer relational query languages.

## Key Concepts

- **SQL support** — Write SELECT queries against OpenSearch indices. Supports WHERE, GROUP BY, HAVING, ORDER BY, LIMIT, JOINs (limited), subqueries, and many SQL functions.
- **PPL (Piped Processing Language)** — A pipe-based query language inspired by SPL. Commands are chained with `|` to filter, transform, and aggregate data. Designed for log analytics and observability.
- **SQL Workbench** — A Dashboards UI for writing and running SQL/PPL queries with result tables and visualizations.
- **JDBC / ODBC drivers** — Connect external tools (Tableau, Excel, custom apps) to OpenSearch via standard database drivers.
- **Explain API** — View the translated OpenSearch DSL query for a given SQL/PPL query. Useful for debugging and optimization.
- **Cursor / Pagination** — SQL queries support cursor-based pagination for large result sets.
- **Key PPL commands** — `search`, `where`, `stats`, `dedup`, `sort`, `top`, `rare`, `eval`, `fields`, `rename`, `head`, `tail`, `parse`, `patterns`, `ad` (anomaly detection), `ml` (machine learning).
- **Key SQL functions** — Mathematical, string, date/time, aggregate, conditional, type conversion, and relevance functions (`match`, `match_phrase`, `multi_match`).

## Common Use Cases

- Ad-hoc log analysis using PPL in OpenSearch Dashboards
- Business analysts querying OpenSearch indices with familiar SQL
- Connecting BI tools (Tableau, Excel) via JDBC/ODBC
- Exploratory data analysis with the SQL Workbench
- Building observability queries with PPL pipe syntax

## Guides

- [PPL commands reference](https://docs.opensearch.org/latest/sql-and-ppl/ppl/commands/index/) — All PPL commands with syntax and examples
- [PPL functions reference](https://docs.opensearch.org/latest/sql-and-ppl/ppl/functions/index/) — Aggregation, string, date, math, and other functions
- [SQL Workbench](https://docs.opensearch.org/latest/dashboards/query-workbench/) — Interactive query editor in Dashboards

## Official Documentation

- [SQL/PPL overview](https://docs.opensearch.org/latest/sql-and-ppl/)
- [SQL reference](https://docs.opensearch.org/latest/sql-and-ppl/sql/index/)
- [PPL reference](https://docs.opensearch.org/latest/sql-and-ppl/ppl/index/)
- [JDBC driver](https://docs.opensearch.org/latest/sql-and-ppl/sql/jdbc/)
- [ODBC driver](https://docs.opensearch.org/latest/sql-and-ppl/sql/odbc/)
- [Settings reference](https://docs.opensearch.org/latest/sql-and-ppl/settings/)
- [Troubleshooting](https://docs.opensearch.org/latest/sql-and-ppl/troubleshoot/)
