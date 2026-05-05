"""Shared fixtures for skill eval tests.

Uses AWS Bedrock (Claude via boto3) as the LLM backend, consistent with
how other opensearch-project repos call Bedrock (e.g. opensearch-build's
code-diff-reviewer workflow).

Authentication follows the same pattern used across the opensearch-project
org: GitHub OIDC → assume a Bedrock-scoped IAM role via
aws-actions/configure-aws-credentials. No static API keys are stored.

Locally, standard AWS credential resolution applies (profile, env vars,
instance metadata, etc.). Tests are skipped automatically when no
credentials are available, so the eval suite never blocks the regular CI run.

Run evals locally (requires AWS credentials with bedrock:InvokeModel):
    uv run --group evals pytest tests/evals/ --run-eval -v
    uv run --group evals pytest tests/evals/ --run-eval-analysis
"""

import json
from pathlib import Path

import pytest

_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills" / "opensearch-skills"

# Bedrock model to use as the judge. Haiku is cheap and fast.
# Use the US cross-region inference profile — required for newer models
# that don't support on-demand throughput directly.
_BEDROCK_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_BEDROCK_REGION = "us-east-1"


# ---------------------------------------------------------------------------
# LLM client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def bedrock_client():
    """Return a boto3 bedrock-runtime client, or None if credentials unavailable.

    Tests that receive None should call pytest.skip() themselves.
    Using None instead of pytest.skip() in the fixture avoids pytest-evals
    recording the case as 'failed' with an empty ResultsBag.
    """
    try:
        import boto3
        return boto3.client("bedrock-runtime", region_name=_BEDROCK_REGION)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Skill loading helpers (available to all eval test modules)
# ---------------------------------------------------------------------------

def load_skill_md(skill_name: str) -> str:
    """Return the full text of a SKILL.md by skill name."""
    for path in _SKILLS_ROOT.rglob("SKILL.md"):
        if path.parent.name == skill_name:
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"No SKILL.md found for skill '{skill_name}' under {_SKILLS_ROOT}"
    )


def call_skill(skill_md: str, prompt: str, client, model_id: str = _BEDROCK_MODEL_ID) -> str:
    """Simulate an agent with skill_md loaded as the system prompt.

    Calls Bedrock using the Messages API (anthropic_version bedrock-2023-05-31),
    matching the pattern used in opensearch-build's AIReleaseNotesGenerator.
    """
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": skill_md,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = client.invoke_model(
        modelId=model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    response_body = json.loads(response["body"].read())
    return response_body["content"][0]["text"]
