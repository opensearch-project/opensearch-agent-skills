# Developer Guide

This guide covers how to contribute new skills, local development, testing, and conventions.

---

## Contributing a New Skill

### 1. Create the skill directory

```
skills/<skill-name>/
    SKILL.md              # Required — entry point
    scripts/              # Optional: scripts the agent executes
    references/           # Optional: detailed docs loaded on demand
    assets/               # Optional: sample data, templates, configs
```

### 2. Write SKILL.md

Every skill needs a `SKILL.md` with YAML frontmatter and markdown instructions:

```yaml
---
name: your-skill-name
description: >
  What the skill does and when to activate it. Include keywords users
  might say so the agent can match this skill to the task. Max 1024 chars.
compatibility: Any prerequisites (e.g., Docker, uv, Python 3.11+).
metadata:
  author: your-github-handle
  version: "1.0"
---

# Skill Title

You are a [role]. You help users [do X].

## Key Rules

- Rule 1
- Rule 2

## Workflow

### Step 1 — ...
### Step 2 — ...
```

**Constraints:**
- `name`: max 64 chars, lowercase + hyphens only, must match folder name
- `description`: max 1024 chars — this is the sole trigger for agent discovery
- `SKILL.md` body: under 500 lines — use separate reference files for detail
- Use relative paths from the skill root for file references

### 3. Add scripts (optional)

If your skill needs to execute operations, add scripts under `scripts/`:

- Prefer Python scripts run via `uv run python scripts/your_script.py`
- Include a `--help` flag for discoverability
- Scripts should be self-contained or clearly document dependencies

### 4. Structure for progressive disclosure

Skills should follow the three-level progressive disclosure pattern:

1. **Metadata** (~100 tokens) — name and description, always loaded
2. **SKILL.md body** (< 5000 tokens) — loaded when skill activates
3. **Bundled files** — loaded only when the agent decides it needs them

Keep your main SKILL.md lean and route detail into reference files.

### 5. Add tests

Add tests under `tests/` following the naming convention `test_<skill-name>_*.py`. Tests must not require a running OpenSearch cluster — use mocks/fakes.

```bash
uv run pytest tests/test_your_skill.py -v
```

### 6. Submit a PR

- Ensure all tests pass: `uv run pytest -q`
- Include a brief description of what the skill does
- Include an example prompt that triggers it

---

## Testing

All tests live in the `tests/` directory and run with [pytest](https://docs.pytest.org/) via [uv](https://docs.astral.sh/uv/).

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (dependency manager / task runner)

No additional setup is needed — `uv run` automatically creates a virtual environment and installs all dependencies (including `opensearch-py` and `pytest`) from `pyproject.toml` on first run.

### Running the full test suite

```bash
uv run pytest tests/ -v
```

### Running a subset of tests

```bash
# Run tests for a specific module
uv run pytest tests/test_agent_skills_client.py -v
uv run pytest tests/test_agent_skills_search.py -v

# Run tests matching a keyword
uv run pytest tests/ -v -k "preflight"

# Run a single test
uv run pytest tests/test_agent_skills_evaluate.py::test_ndcg_perfect_ranking -v
```

### Available test files

| Test file | Module under test |
|---|---|
| `test_agent_skills_client.py` | `lib/client.py` — connection, auth, text normalization |
| `test_agent_skills_evaluate.py` | `lib/evaluate.py` — search quality metrics, diagnostics, reporting |
| `test_agent_skills_operations.py` | `lib/operations.py` — index CRUD, bulk indexing, pipelines, model deployment |
| `test_agent_skills_preflight.py` | `lib/client.py` — preflight cluster detection and credential management |
| `test_agent_skills_samples.py` | `lib/samples.py` — file loading (JSON/CSV/TSV), text field inference |
| `test_agent_skills_search.py` | `lib/search.py` — query building, suggestions, autocomplete, search UI |
| `test_agent_skills_standalone_assets.py` | Verifies UI assets and sample data are bundled correctly |

### Writing new tests

- **No cluster required.** Tests must not require a running OpenSearch cluster. Use fake/mock clients (see existing tests for patterns).
- **Naming convention.** Name test files `test_agent_skills_<module>.py` to match the skill's `scripts/lib/` modules.
- **Importing skill code.** Insert the scripts directory onto `sys.path` at the top of your test file:
  ```python
  import sys
  from pathlib import Path

  _SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
  sys.path.insert(0, str(_SCRIPTS_DIR))

  from lib.client import normalize_text  # example import
  ```
- **Monkeypatching.** Use pytest's `monkeypatch` fixture to stub out `create_client` and other functions that would connect to a real cluster.

### CI

GitHub Actions runs the full test suite on every push and PR across Linux, macOS, and Windows. See `.github/workflows/ci.yml`.

---

## Conventions

- Skill names: lowercase, hyphens only, max 64 chars
- Skill folder name must match the `name` field in SKILL.md frontmatter
- SKILL.md body under 500 lines
- Reference files should be focused and single-purpose
- Scripts should handle errors gracefully and include helpful error messages
