# Developer Guide

This guide covers how to contribute new skills, local development, testing, and conventions.

Two ways to contribute a skill:

1. **Author it here** — write a skill directly in this repo under `skills/`. See *Contributing a New Skill* below.
2. **Mirror it from an upstream repo** — register a YAML source under `sync/sources/` and the sync framework replays the upstream history into `skills/` every hour. See *Mirroring an Upstream Skill* further down.

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
| `test_agent_skills_spec_compliance.py` | Validates every `SKILL.md` against the [agentskills.io spec](https://agentskills.io/specification) — frontmatter fields, naming rules, body line count, file references |

### Skill eval tests (LLM-based)

Eval tests live in `tests/evals/` and use a real LLM to verify that skill instructions produce correct agent behavior. They require `ANTHROPIC_API_KEY` and are **not** run as part of the regular `pytest tests/` suite.

```bash
# Install eval dependencies
uv sync --group evals

# Run eval cases (collects results, individual failures don't abort)
uv run --group evals pytest tests/evals/ --run-eval -v

# Analyze aggregated results and enforce pass-rate thresholds
uv run --group evals pytest tests/evals/ --run-eval-analysis
```

Two eval test files:

| File | What it tests |
|---|---|
| `tests/evals/test_skill_routing.py` | Top-level router correctly identifies the right leaf skill for a given prompt (≥80% accuracy) |
| `tests/evals/test_skill_rules.py` | Each leaf skill's key rules are followed — e.g. preflight-check first, no "scales to zero", dotted field quoting (≥80% compliance) |

Golden test cases live in `tests/evals/fixtures/`:
- `routing.json` — 12 prompt → expected-skill cases (3 per skill)
- `skill_rules.json` — 11 rule-compliance cases drawn from each skill's "Key Rules" section

CI runs evals weekly (Monday 06:00 UTC) and on any push that touches `skills/**` or `tests/evals/**`. See `.github/workflows/evals.yml`.

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

## Mirroring an Upstream Skill

Some skills live in their home project's repo (e.g. an integration skill shipped alongside the tool it wraps). Rather than duplicating the content here and letting it rot, this repo can **sync subdirectories from upstream repos** directly into `skills/` on a schedule, preserving per-commit authorship and history. Synced skills sit side-by-side with skills authored here — from an agent's perspective they're all just entries under `skills/`.

### How it works (1-minute version)

- One YAML file per upstream source under `sync/sources/` declares `url`, `branch`, `src_path`, `dest_path`.
- A scheduled GitHub Action (`Sync Skills`) runs every hour.
- For each source, the engine enumerates upstream commits that touched `src_path` since the last-synced SHA, replays each as its own commit here via `git format-patch | git am --directory=<dest_path>`, prefixes the subject with `[<source-name>]`, and appends `Source-Repo` / `Source-Commit` / `Co-authored-by` trailers. The original author and date survive — the GitHub contributor graph credits upstream authors.
- `sync/state.json` tracks the last-synced SHA per source so subsequent runs are incremental.
- Each source is isolated: a failure in one (bad patch, spec violation, upstream outage) opens a tracking issue and does not block the others.

Full engine semantics are documented in [`sync/README.md`](sync/README.md). Engine source + tests live in [`sync-bot/`](sync-bot/).

### Adding a new upstream source

The entire flow is: drop one YAML file, open a PR.

1. Create `sync/sources/<short-name>.yaml`:

   ```yaml
   # Sync source: <short-name>
   name: <short-name>                              # unique id (state key + commit-subject prefix)
   url: https://github.com/<org>/<repo>.git
   branch: main
   src_path: skills/<upstream-skill-dir>           # subdir in upstream to mirror
   dest_path: skills/<upstream-skill-dir>          # where it lands here (sibling of authored skills)
   ```

   Rules:
   - `name` must be unique across `sync/sources/` (hard error otherwise).
   - `dest_path`'s **leaf** directory name must equal the upstream `SKILL.md`'s `name:` field — the Agent Skills Spec validator enforces this and rolls back the import on mismatch.
   - Files are processed in lexicographic order, so filenames double as a sync-order knob.

2. Commit the YAML on a branch, push, open a PR.

3. `Sync Skills` auto-fires on PRs that touch `sync/sources/**`. It replays the upstream history into `dest_path`, pushes those commits onto your PR branch, and re-runs CI + dry-run spec validation against the post-sync HEAD. Review the replayed commits, then merge.

PRs opened from forks skip the auto-push (GitHub denies write tokens to forks) but still run dry-run validation, so config mistakes surface before merge. The fork owner can still preview the replayed commits before merge by dispatching `Sync Skills` on their own fork against the PR branch — that run executes under the fork's write-scoped token and pushes the imports onto the PR branch:

```bash
gh workflow run sync-skills.yml \
  --repo <you>/opensearch-agent-skills \
  --ref <your-pr-branch> \
  -f only=<new-source-name>
```

Note: enabling "Allow edits and access to secrets by maintainers" on the PR does **not** unblock this — that toggle applies to human pushes; `pull_request`-event workflow tokens from forks are read-only regardless.

### Running the sync locally

The engine is a standalone [uv](https://docs.astral.sh/uv/)-managed Python package under `sync-bot/`.

```bash
# Dry run (prints planned imports, writes nothing)
uv run --project sync-bot opensearch-skills-sync --dry-run

# Full sync (writes state.json + creates commits)
uv run --project sync-bot opensearch-skills-sync

# Sync a single source
uv run --project sync-bot opensearch-skills-sync --only <source-name>

# Custom sources directory (useful for experimentation)
uv run --project sync-bot opensearch-skills-sync --sources-dir path/to/sources
```

Tests for the engine itself:

```bash
uv run --project sync-bot pytest
```

A dedicated CI workflow (`sync-bot-ci.yml`) runs these tests on Linux and macOS against the pinned `uv.lock` — independently of the skill-contents test suite.

### Resetting a source

To force a full re-import of an upstream (e.g. you changed `src_path` or the upstream did a history rewrite), delete that source's entry from `sync/state.json.sources` and commit. The next run treats it as a first-time sync and replays the upstream history bounded by the blob-filtered clone.

### Conventions for synced skills

- **Do not hand-edit** files in a synced skill's directory. Which skills are synced is declared in `sync/sources/*.yaml` — check there before editing. Changes to a synced skill will be overwritten on the next sync, or — worse — cause `git am` conflicts that abort the source. Fix issues upstream and let the sync pull them in.
- **Synced commits are prefixed** with `[<source-name>]` in the subject line (LLVM-monorepo style) so mixed history is greppable: `git log --oneline | grep '^\w* \[anthropic-skill-creator\]'`.
- **Sync-bot commits** (state.json advances, framework housekeeping) are authored by `opensearch-ci-bot` with a stable noreply email. Content commits keep their upstream author.
- `sync/state.json` is committed to the repo. Do not add it to `.gitignore` — incremental sync depends on it being in HEAD.

---

## Conventions

- Skill names: lowercase, hyphens only, max 64 chars
- Skill folder name must match the `name` field in SKILL.md frontmatter
- SKILL.md body under 500 lines
- Reference files should be focused and single-purpose
- Scripts should handle errors gracefully and include helpful error messages
