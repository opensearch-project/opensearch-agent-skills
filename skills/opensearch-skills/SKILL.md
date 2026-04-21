---
name: opensearch-skills
description: >
  Build search applications and query log analytics data with OpenSearch.
  Use this skill when the user mentions OpenSearch, search app, index setup,
  search architecture, semantic search, vector search, hybrid search, BM25,
  dense vector, sparse vector, agentic search, RAG, embeddings, KNN, PDF
  ingestion, document processing, or any related search topic. Also use for
  log analytics and observability — when the user wants to set up log
  ingestion, query logs with PPL, analyze error patterns, set up index
  lifecycle policies, investigate traces, or check stack health. Activate
  even if the user says log analysis, Fluent Bit, Fluentd, Logstash, syslog,
  traceId, OpenTelemetry, or log analytics without mentioning OpenSearch.
compatibility: Requires Docker and uv. AWS deployment requires AWS credentials.
metadata:
  author: opensearch-project
  version: "2.0"
---

# OpenSearch Skills

This is the top-level skill for OpenSearch. It contains three category skills that can also be installed and used independently:

| Category | Skill | Install individually |
|---|---|---|
| [search](search/SKILL.md) | [opensearch-launchpad](search/opensearch-launchpad/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@opensearch-launchpad` |
| [observability](observability/SKILL.md) | [log-analytics](observability/log-analytics/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@log-analytics` |
| [observability](observability/SKILL.md) | [trace-analytics](observability/trace-analytics/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@trace-analytics` |
| [cloud](cloud/SKILL.md) | [aws-setup](cloud/aws-setup/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@aws-setup` |

## Routing

Route to the right skill based on user intent:

| User Intent | Skill |
|---|---|
| Build a search app, set up an index, choose a search strategy | [opensearch-launchpad](search/opensearch-launchpad/SKILL.md) |
| Analyze logs, query with PPL, discover error patterns | [log-analytics](observability/log-analytics/SKILL.md) |
| Investigate traces, debug spans, analyze service maps | [trace-analytics](observability/trace-analytics/SKILL.md) |
| Deploy to AWS, provision a domain or collection | [aws-setup](cloud/aws-setup/SKILL.md) |
| General OpenSearch question | Search docs first, then route to the relevant skill |

If the user's intent spans multiple skills (e.g., "build a search app and deploy it to AWS"), start with the appropriate skill and transition to the next when ready.

## Shared Resources

All skills share these resources:

- **Scripts**: `scripts/opensearch_ops.py` — CLI for all OpenSearch operations
- **Docker bootstrap**: `scripts/start_opensearch.sh` — Start a local OpenSearch cluster
- **CLI Reference**: [cli-reference.md](cli-reference.md) — Full command reference with examples
- **Search Builder UI**: `scripts/ui/` — React frontend served on port 8765

```bash
bash scripts/start_opensearch.sh
uv run python scripts/opensearch_ops.py <command> [options]
uv run python scripts/opensearch_ops.py --help
```

## Optional MCP Servers

```json
{
  "mcpServers": {
    "ddg-search": {
      "command": "uvx",
      "args": ["duckduckgo-mcp-server"]
    },
    "awslabs.aws-api-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.aws-api-mcp-server@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    },
    "aws-knowledge-mcp-server": {
      "command": "uvx",
      "args": ["fastmcp", "run", "https://knowledge-mcp.global.api.aws"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    },
    "opensearch-mcp-server": {
      "command": "uvx",
      "args": ["opensearch-mcp-server-py@latest"],
      "env": { "FASTMCP_LOG_LEVEL": "ERROR" }
    }
  }
}
```

## Auto-Installing Missing MCP Servers

Before using any MCP tool, check if the server is available. If missing:

1. Locate the MCP config file:
   - Kiro: `.kiro/settings/mcp.json`
   - Cursor: `.cursor/mcp.json`
   - Claude Code: `.mcp.json`
   - VS Code (Copilot): `.vscode/mcp.json`
   - Windsurf: `~/.codeium/windsurf/mcp_config.json`
2. Read the existing config (or start with `{"mcpServers": {}}`).
3. Merge in the missing server entry. Do not overwrite existing entries.
4. Save and inform the user to restart or reconnect MCP servers.

## Answering OpenSearch Knowledge Questions

```bash
uv run python scripts/opensearch_ops.py search-docs --query "<your query>"
uv run python scripts/opensearch_ops.py search-docs --query "<query>" --site docs.aws.amazon.com
```
