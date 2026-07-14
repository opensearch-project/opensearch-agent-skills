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

# Bedrock model configuration:
# - Skill model: Used to invoke the skill (the agent under test). Sonnet
#   provides strong instruction-following at reasonable cost.
# - Judge model: Used by GEval to score responses. Haiku is cheap and fast.
# Use the US cross-region inference profile — required for newer models
# that don't support on-demand throughput directly.
_BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
_BEDROCK_JUDGE_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
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


def load_skill_with_references(skill_name: str, references: list[str] | None = None) -> str:
    """Return skill SKILL.md content with optional reference files appended.

    In a real agent, reference files are loaded on demand when the agent reads
    them. For evals, we include them in the system prompt to simulate the agent
    having already read the reference material.
    """
    skill_md = load_skill_md(skill_name)
    if not references:
        return skill_md

    # Find the skill directory
    skill_dir = None
    for path in _SKILLS_ROOT.rglob("SKILL.md"):
        if path.parent.name == skill_name:
            skill_dir = path.parent
            break

    if not skill_dir:
        return skill_md

    # Append reference files
    parts = [skill_md]
    for ref in references:
        # Search in skill dir, parent, and grandparent (for shared references)
        for search_dir in [skill_dir, skill_dir.parent, skill_dir.parent.parent]:
            ref_path = search_dir / ref
            if ref_path.exists():
                parts.append(f"\n\n---\n## Reference: {ref}\n\n{ref_path.read_text(encoding='utf-8')}")
                break

    return "\n".join(parts)


def call_skill(skill_md: str, prompt: str, client, model_id: str = _BEDROCK_MODEL_ID, max_turns: int = 3) -> str:
    """Simulate a multi-turn conversation with skill_md as the system prompt.

    If the skill asks follow-up questions instead of executing, an eval agent
    generates a reasonable user reply and the conversation continues until
    the skill produces a substantive response (commands, refusals, or
    explanations) or max_turns is reached.

    Returns the full conversation as a formatted string for the judge to evaluate.
    """
    messages = [{"role": "user", "content": prompt}]

    for turn in range(max_turns):
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "system": skill_md,
            "messages": messages,
        })
        response = client.invoke_model(
            modelId=model_id,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        response_body = json.loads(response["body"].read())
        assistant_text = response_body["content"][0]["text"]
        messages.append({"role": "assistant", "content": assistant_text})

        # If this is the last allowed turn, stop
        if turn >= max_turns - 1:
            break

        # Check if the assistant is asking a follow-up question rather than
        # executing. Use a simple heuristic: if the response ends with a
        # question mark or contains common question patterns, generate a reply.
        if not _is_follow_up_question(assistant_text):
            break

        # Generate a contextual user reply to the follow-up question
        user_reply = _generate_eval_reply(prompt, assistant_text, client, model_id)
        messages.append({"role": "user", "content": user_reply})

    # Return the full conversation formatted for the judge
    return _format_conversation(messages)


def _is_follow_up_question(text: str) -> bool:
    """Heuristic: does the assistant response look like it's asking for more info?"""
    # Check if the response is primarily asking questions rather than executing
    lines = text.strip().split("\n")
    # Look at the last few non-empty lines for question indicators
    tail = [l.strip() for l in lines[-5:] if l.strip()]
    if not tail:
        return False

    question_indicators = [
        "?",
        "Which would you prefer",
        "Which option",
        "Would you like",
        "Could you provide",
        "Can you provide",
        "Please provide",
        "Please specify",
        "What would you like",
        "Do you want",
        "Let me know",
    ]
    tail_text = " ".join(tail)
    return any(indicator in tail_text for indicator in question_indicators)


def _generate_eval_reply(original_prompt: str, assistant_question: str, client, model_id: str) -> str:
    """Use the LLM to generate a reasonable user reply to a follow-up question.

    The eval agent acts as a cooperative user who provides sensible defaults
    to keep the conversation moving toward execution.
    """
    system = (
        "You are simulating a user in a test scenario. The user originally asked "
        "something and the assistant asked a follow-up question. Generate a short, "
        "reasonable reply that answers the question with sensible defaults so the "
        "assistant can proceed. Be concise — 1-2 sentences max. Pick the simplest "
        "option if given choices. Don't add new requirements. "
        "IMPORTANT: Stay consistent with the values and parameters in the original "
        "request. If the original request specified particular values (names, numbers, "
        "regions, types), restate those same values — do not change or 'fix' them."
    )
    user_msg = (
        f"Original user request: {original_prompt}\n\n"
        f"Assistant asked: {assistant_question}\n\n"
        f"Generate a brief, cooperative reply:"
    )
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 256,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    })
    response = client.invoke_model(
        modelId=model_id,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    response_body = json.loads(response["body"].read())
    return response_body["content"][0]["text"]


def _format_conversation(messages: list) -> str:
    """Format a multi-turn conversation into a readable string for the judge."""
    parts = []
    for msg in messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        parts.append(f"[{role}]: {msg['content']}")
    return "\n\n".join(parts)
