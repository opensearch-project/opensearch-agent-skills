# OpenSearch Agent Skills

A collection of [Agent Skills](https://agentskills.io/specification) for building search applications and analyzing observability data with OpenSearch. Works with Claude Code, Cursor, Kiro, and any agent that supports the Agent Skills standard.

---

## Available Skills

| Skill | Description |
|-------|-------------|
| **[opensearch-skills](skills/opensearch-skills/)** | Build search apps (semantic, hybrid, neural, agentic) and analyze logs/traces with OpenSearch. Includes local execution and optional AWS deployment. |
| **[opensearch-plugins](skills/opensearch-plugins/)** | OpenSearch plugin reference and guidance. Covers 17 plugins including anomaly detection, ML Commons, alerting, flow framework, k-NN, neural search, index management, security, and more. |

> More skills coming soon — contributions welcome! See [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

---

## Install

Install any skill using [`npx skills`](https://agentskills.io):

```bash
npx skills add opensearch-project/opensearch-agent-skills
```

This discovers skills under `skills/` and symlinks them into your agent's skill directory (`.claude/skills/`, `.cursor/skills/`, `.kiro/skills/`, etc.).

### Install options

```bash
# Install to a specific agent
npx skills add opensearch-project/opensearch-agent-skills -a claude-code

# Install globally (available across all projects)
npx skills add opensearch-project/opensearch-agent-skills -g

# Install to all detected agents
npx skills add opensearch-project/opensearch-agent-skills --all

# List available skills before installing
npx skills add opensearch-project/opensearch-agent-skills --list
```

After installing, try:

> *"I want to build a semantic search app with OpenSearch"*

Your agent reads the skill instructions and runs the scripts directly — no MCP server required.

---

## Prerequisites

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- **Docker** installed and running ([Download Docker](https://docs.docker.com/get-docker/))
- **For AWS deployment (optional):** AWS credentials configured

---

## Repo Structure

```
skills/
  opensearch-skills/         # Main skill
    SKILL.md                 # Skill instructions (entry point)
    cli-reference.md         # CLI command reference
    aws/                     # AWS deployment guides (loaded on demand)
    launchpad/               # Search architecture guides (loaded on demand)
    observability/            # Log analytics & trace guides (loaded on demand)
    scripts/                 # Execution scripts
  opensearch-plugins/        # Plugin reference skill
    SKILL.md                 # Routing entry point (keyword table)
    references/              # Per-plugin reference files (loaded on demand)
```

---

## Contributing

We welcome new skills and improvements! See the [Developer Guide](DEVELOPER_GUIDE.md) for instructions on creating skills, conventions, testing, and the contribution process.

---

## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE.txt](LICENSE.txt) for details.
