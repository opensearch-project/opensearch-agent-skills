# AGENTS.md

This file provides guidance for AI coding agents working on the opensearch-agent-skills repository.

## Project Overview

A collection of [Agent Skills](https://agentskills.io/specification) for building search applications and analyzing observability data with OpenSearch. Currently contains one skill (`opensearch-skills`) under `skills/opensearch-skills/`.

## Tech Stack

- **Language:** Python 3.11+
- **Package manager:** [uv](https://docs.astral.sh/uv/)
- **Testing:** pytest
- **CI:** GitHub Actions (Linux, macOS, Windows)
- **Dependencies:** `opensearch-py` (runtime), `pytest>=7.0` (dev)

## Repository Structure

```
skills/
  opensearch-skills/           # Main skill
    SKILL.md                   # Skill entry point (instructions for agents)
    cli-reference.md           # CLI command reference
    aws/                       # AWS deployment guides
    launchpad/                 # Search architecture guides
    observability/             # Log analytics & trace guides
    scripts/
      opensearch_ops.py        # Main CLI tool
      start_opensearch.sh      # Docker bootstrap
      lib/                     # Core Python modules
        client.py              # Connection, auth, preflight
        operations.py          # Index/model/pipeline ops
        search.py              # Query building, UI logic
        evaluate.py            # Search quality metrics
        samples.py             # Sample data loading
        ui.py                  # Search Builder UI server
      ui/                      # React frontend (index.html, app.jsx, styles.css)
      sample_data/             # Bundled IMDB sample dataset
tests/                         # pytest test suite (no cluster required)
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

- Skills follow the [Agent Skills specification](https://agentskills.io/specification) with three-level progressive disclosure: metadata (~100 tokens) -> SKILL.md body (<5000 tokens) -> bundled reference files (loaded on demand).
- The main CLI (`opensearch_ops.py`) uses PEP 723 inline script dependencies and is designed to be run directly by AI agents via `uv run`.
- The React UI (`scripts/ui/`) is served by a lightweight Python HTTP server (`lib/ui.py`) on port 8765.
- MCP server integration is optional and configured per-IDE.
