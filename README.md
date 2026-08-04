# OpenSearch Agent Skills

A collection of [Agent Skills](https://agentskills.io/specification) for building search applications and analyzing observability data with OpenSearch. Works with Claude Code, Cursor, Kiro, and any agent that supports the Agent Skills standard.

---

## Available Skills

Skills are organized in a tree — install the whole collection or pick individual skills.

| Category | Skill | Description |
|----------|-------|-------------|
| **Search** | [opensearch-launchpad](skills/opensearch-skills/search/opensearch-launchpad/) | Build search apps from scratch — BM25, semantic, hybrid, agentic search |
| **Search** | [opensearch-blueprint](skills/opensearch-skills/search/opensearch-blueprint/) | Compile requirements into a linted, cluster-verified index design — mappings, analyzers, k-NN, pipelines, ISM |
| **Observability** | [log-analytics](skills/opensearch-skills/observability/log-analytics/) | Query and analyze logs with PPL — error patterns, anomaly detection |
| **Observability** | [trace-analytics](skills/opensearch-skills/observability/trace-analytics/) | Investigate distributed traces — slow spans, service maps, agent invocations |
| **Cloud** | [aws-setup](skills/opensearch-skills/cloud/aws-setup/) | Deploy to Amazon OpenSearch Service or Serverless |
| **Cloud** | [managed-ingestion-service](skills/opensearch-skills/cloud/managed-ingestion-service/) | Ingest chunks at scale via OSIS pipelines with ASE |

> More skills coming soon — contributions welcome! See [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).

---

## Install

Install using [`npx skills`](https://agentskills.io):

```bash
# Install all skills
npx skills add opensearch-project/opensearch-agent-skills

# Install a specific skill
npx skills add opensearch-project/opensearch-agent-skills@opensearch-launchpad --full-depth
npx skills add opensearch-project/opensearch-agent-skills@opensearch-blueprint --full-depth
npx skills add opensearch-project/opensearch-agent-skills@log-analytics --full-depth
npx skills add opensearch-project/opensearch-agent-skills@trace-analytics --full-depth
npx skills add opensearch-project/opensearch-agent-skills@aws-setup --full-depth
npx skills add opensearch-project/opensearch-agent-skills@managed-ingestion-service --full-depth
```

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

### Claude Community Marketplace (Claude Code)

```bash
# Add the community marketplace (one-time setup)
/plugin marketplace add anthropics/claude-plugins-community

# Install the plugin
/plugin install opensearch-agent-skills@claude-community

# Reload to apply
/reload-plugins
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
  opensearch-skills/                  # Top-level meta-skill
    SKILL.md                          # Routes to category skills
    cli-reference.md                  # Shared CLI command reference
    scripts/                          # Shared scripts, UI, sample data
    search/                           # Category: Search
      SKILL.md
      opensearch-launchpad/           # Search app builder
        SKILL.md
        *.md                          # Model guides, evaluation, strategies
      opensearch-blueprint/           # Index design compiler + validator
        SKILL.md
        blueprint-format.md           # Bundle schema and density rules
        opensearch-vocabulary.md      # Field types, analysis, k-NN, pipelines
        example-bundle.json           # Reference hybrid blueprint
    observability/                    # Category: Observability
      SKILL.md
      log-analytics/                  # Log querying & analysis
        SKILL.md
        log-analytics.md
        ppl-reference.md
      trace-analytics/                # Distributed trace investigation
        SKILL.md
        traces.md
        ppl-reference.md
    ingest/                           # Category: Ingest
      SKILL.md
      document-processing/            # Local document processing (Docling)
        SKILL.md
        document_processing_guide.md
    cloud/                            # Category: Cloud deployment
      SKILL.md
      aws-setup/                      # AWS provisioning & deployment
        SKILL.md
        aos/                          # Amazon OpenSearch Service guides
        aoss/                         # Amazon OpenSearch Serverless guides
        reference.md
      managed-ingestion-service/      # Cloud-scale ingestion via OSIS
        SKILL.md
        iam-setup.md
tests/                                # pytest test suite
```

---

## Contributing

We welcome new skills and improvements! See the [Developer Guide](DEVELOPER_GUIDE.md) for instructions on creating skills, conventions, testing, and the contribution process.

---

## License

This project is licensed under the Apache License, Version 2.0. See [LICENSE.txt](LICENSE.txt) for details.
