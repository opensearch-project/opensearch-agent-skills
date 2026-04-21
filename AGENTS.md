# AGENTS.md

This file provides guidance for AI coding agents working on the opensearch-agent-skills repository.

## Project Overview

A collection of [Agent Skills](https://agentskills.io/specification) for building search applications and analyzing observability data with OpenSearch. Skills are organized in a tree structure under `skills/` — users can install the entire tree or individual skills at any level.

## Tech Stack

- **Language:** Python 3.11+
- **Package manager:** [uv](https://docs.astral.sh/uv/)
- **Testing:** pytest
- **CI:** GitHub Actions (Linux, macOS, Windows)
- **Dependencies:** `opensearch-py` (runtime), `pytest>=7.0` (dev)

## Repository Structure

```
skills/
  SKILL.md                        # Top-level meta-skill, routes to categories
  cli-reference.md                # CLI command reference
  scripts/                        # Shared scripts, UI, sample data
    opensearch_ops.py             # Main CLI tool
    start_opensearch.sh           # Docker bootstrap
    lib/                          # Core Python modules
      client.py                   # Connection, auth, preflight
      operations.py               # Index/model/pipeline ops
      search.py                   # Query building, UI logic
      evaluate.py                 # Search quality metrics
      samples.py                  # Sample data loading
      ui.py                       # Search Builder UI server
    ui/                           # React frontend (index.html, app.jsx, styles.css)
    sample_data/                  # Bundled IMDB sample dataset
  search/                         # Category: Search
    SKILL.md                      # Category router
    opensearch-launchpad/         # Leaf skill: search app builder
      SKILL.md
      *.md                        # Reference files (models, strategies, evaluation)
  observability/                  # Category: Observability
    SKILL.md                      # Category router
    log-analytics/                # Leaf skill: log querying & analysis
      SKILL.md
      log-analytics.md            # Full workflow reference
      ppl-reference.md            # PPL syntax reference
    trace-analytics/              # Leaf skill: distributed trace investigation
      SKILL.md
      traces.md                   # Trace query templates
      ppl-reference.md            # PPL syntax reference
  cloud/                          # Category: Cloud deployment
    SKILL.md                      # Category router
    aws-setup/                    # Leaf skill: AWS provisioning & deployment
      SKILL.md
      aos/                        # Amazon OpenSearch Service guides
      aoss/                       # Amazon OpenSearch Serverless guides
      reference.md                # Cost, security, troubleshooting
tests/                            # pytest test suite (no cluster required)
```

## Build & Test Commands

```bash
# Install dependencies (automatic on first run)
uv sync

# Run full test suite
uv run pytest tests/ -v

# Run tests for a specific module
uv run pytest tests/test_agent_skills_client.py -v

# Run tests matching a keyword
uv run pytest tests/ -v -k "preflight"

# Run a single test
uv run pytest tests/test_agent_skills_evaluate.py::test_ndcg_perfect_ranking -v
```

## Before Committing

1. **Run all tests** and ensure they pass:
   ```bash
   uv run pytest tests/ -v
   ```
2. **Update CHANGELOG.md** with a summary of your changes under `## [Unreleased]`.
3. **Do not commit** `.env`, `.mcp.json`, credentials, or secrets.

## Before Raising a PR

- All tests pass on your local machine.
- Commit messages are clear and descriptive.
- Include [DCO signoff](https://github.com/apps/dco) on all commits (`git commit -s`).
- If adding a new skill, follow the conventions in [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md).
- If adding new Python modules under `scripts/lib/`, add corresponding test files named `test_agent_skills_<module>.py`.

## Code Conventions

- **Skill names:** lowercase with hyphens, max 64 chars, must match folder name.
- **Test files:** named `test_agent_skills_<module>.py` to match `scripts/lib/<module>.py`.
- **Tests must not require a running OpenSearch cluster** — use mocks/fakes.
- **Imports in tests:** insert scripts dir onto `sys.path` (see existing test files for pattern).
- **Scripts:** use `uv run python` to execute; include `--help` flag for discoverability.
- **SKILL.md body:** keep under 500 lines; use separate reference files for detail.

## Architecture Notes

- Skills are organized as a tree: top-level meta-skill → category skills → leaf skills. Each level has its own SKILL.md. Users can install at any level.
- Skills follow the [Agent Skills specification](https://agentskills.io/specification) with three-level progressive disclosure: metadata (~100 tokens) -> SKILL.md body (<5000 tokens) -> bundled reference files (loaded on demand).
- Category SKILL.md files are lightweight routers (~30 lines) that describe child skills and when to use them.
- Leaf SKILL.md files contain the actual workflow instructions for agents.
- The main CLI (`opensearch_ops.py`) uses PEP 723 inline script dependencies and is designed to be run directly by AI agents via `uv run`.
- The React UI (`scripts/ui/`) is served by a lightweight Python HTTP server (`lib/ui.py`) on port 8765.
- MCP server integration is optional and configured per-IDE.
