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
| [search](search/SKILL.md) | [opensearch-launchpad](search/opensearch-launchpad/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@opensearch-launchpad --full-depth` |
| [observability](observability/SKILL.md) | [log-analytics](observability/log-analytics/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@log-analytics --full-depth` |
| [observability](observability/SKILL.md) | [trace-analytics](observability/trace-analytics/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@trace-analytics --full-depth` |
| [cloud](cloud/SKILL.md) | [aws-setup](cloud/aws-setup/SKILL.md) | `npx skills add opensearch-project/opensearch-agent-skills@aws-setup --full-depth` |

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

## Feedback Collection (Required Behavior)

**This applies to ALL skills in this collection** — opensearch-launchpad, log-analytics, trace-analytics, and aws-setup. Regardless of which skill is active, you MUST follow these rules.

You MUST proactively collect feedback during every interaction. This is not optional — treat it as a core part of the workflow, not an afterthought.

### Rules

1. **Monitor continuously** — watch for failures, confusion, and unmet needs throughout the conversation, not just at the end.
2. **Offer immediately on failure** — when any command errors or a step doesn't work, immediately offer to capture feedback before troubleshooting.
3. **Offer on uncertainty** — if you're unsure how to proceed or the skill doesn't cover the user's request, flag it as a potential gap and offer to submit.
4. **Ask at natural breakpoints** — after completing a major phase (not just at the very end), ask "Is this working as expected? Any friction so far?"
5. **Always ask at end** — when the user says they're done or the workflow completes, ask for a 1-5 rating.
6. **Never send without consent** — show the preview, get explicit "yes".

### Triggers

| When | What to do |
|------|------------|
| Command returns non-zero exit or error | → Immediately: "That failed. Can I capture this as feedback?" |
| User says "that's not what I wanted" / "this is confusing" / expresses frustration | → "Sounds like friction. Can I note what went wrong?" |
| User asks for something you can't do | → "This isn't supported yet. Can I flag this as a feature gap?" |
| A workaround is needed (something should be simpler) | → "That was more steps than it should be. Can I flag this as friction?" |
| Major phase completes | → "How's it going so far? Any issues?" |
| User says "done" or workflow ends | → "How was the overall experience? (1-5)" |

### How to Submit

1. Compose the feedback (type + context).
2. Show preview to user.
3. Ask: "May I submit this anonymous feedback?"
4. On consent:

```bash
uv run python scripts/opensearch_ops.py submit-feedback \
  --type <failure|gap|friction|success> \
  --skill <skill-name> \
  --context "<error message, command, what happened>" \
  --comment "<user's words>" \
  --rating "<1-5, for success only>"
```

### Feedback Types

- `failure` — A command or step produced an error
- `gap` — User needs something the skill doesn't support
- `friction` — Workflow was confusing, slow, or required workarounds
- `success` — Workflow completed, user satisfied

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
