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

# Agent harness configuration
_MAX_AGENT_TURNS = 10  # Max tool-use loops before stopping
_MAX_USER_TURNS = 5    # Max follow-up user replies


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
# Skill loading helpers
# ---------------------------------------------------------------------------

def load_skill_md(skill_name: str) -> str:
    """Return the full text of a SKILL.md by skill name."""
    for path in _SKILLS_ROOT.rglob("SKILL.md"):
        if path.parent.name == skill_name:
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        f"No SKILL.md found for skill '{skill_name}' under {_SKILLS_ROOT}"
    )


def _find_skill_dir(skill_name: str) -> Path | None:
    """Find the directory containing a skill's SKILL.md."""
    for path in _SKILLS_ROOT.rglob("SKILL.md"):
        if path.parent.name == skill_name:
            return path.parent
    return None


# Keep for backward compatibility with test_skill_routing.py
def load_skill_with_references(skill_name: str, references: list[str] | None = None) -> str:
    """Return skill SKILL.md content with optional reference files appended."""
    skill_md = load_skill_md(skill_name)
    if not references:
        return skill_md
    skill_dir = _find_skill_dir(skill_name)
    if not skill_dir:
        return skill_md
    parts = [skill_md]
    for ref in references:
        ref_path = _resolve_reference(skill_dir, ref)
        parts.append(f"\n\n---\n## Reference: {ref}\n\n{ref_path.read_text(encoding='utf-8')}")
    return "\n".join(parts)


def _resolve_reference(skill_dir: Path, ref: str) -> Path:
    """Locate a case's reference file, or raise saying which one is missing.

    Tried in order: the skill's own directory and its two parents, then the
    whole skill tree by filename — a reference may live under a different
    category than the skill that cites it. Never resolving is an error: a
    reference that loads nothing leaves the case measuring the skill without
    the guide it names, and says so nowhere.
    """
    for search_dir in [skill_dir, skill_dir.parent, skill_dir.parent.parent]:
        candidate = search_dir / ref
        if candidate.exists():
            return candidate
    matches = sorted(_SKILLS_ROOT.rglob(ref))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(
            f"Reference '{ref}' cited by a case for skill '{skill_dir.name}' "
            f"was not found under {_SKILLS_ROOT}"
        )
    raise FileNotFoundError(
        f"Reference '{ref}' cited by a case for skill '{skill_dir.name}' is "
        f"ambiguous — {len(matches)} files share that name: "
        + ", ".join(str(m.relative_to(_SKILLS_ROOT)) for m in matches)
    )


# ---------------------------------------------------------------------------
# Agent harness — simulates a real agent with tool access
# ---------------------------------------------------------------------------

_TOOLS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the skill directory tree. Use relative paths. "
            "Available files include SKILL.md, reference docs (*.md), and "
            "sub-skill directories. Use this to read reference documentation "
            "mentioned in the skill instructions before answering questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Relative path from the skill root. Examples: "
                        "'document_processing_guide.md', 'agentic_search_guide.md', "
                        "'../ppl-reference.md', '../../cloud/aws-setup/SKILL.md'"
                    )
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "list_files",
        "description": (
            "List files and directories available in the skill directory tree. "
            "Use this to discover what reference files are available."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path to list. Use '.' for current skill directory."
                }
            },
            "required": ["path"]
        }
    }
]


def _resolve_file_path(skill_dir: Path, relative_path: str) -> Path | None:
    """Resolve a relative path from the skill directory, safely.

    Allows traversal within the skills tree but not outside it.
    """
    target = (skill_dir / relative_path).resolve()

    # Security: ensure it's still within the skills root
    if not str(target).startswith(str(_SKILLS_ROOT.resolve())):
        return None

    if target.exists():
        return target
    return None


def _handle_tool_call(tool_name: str, tool_input: dict, skill_dir: Path) -> str:
    """Execute a tool call and return the result string."""
    if tool_name == "read_file":
        path = tool_input.get("path", "")
        resolved = _resolve_file_path(skill_dir, path)
        if resolved is None:
            return f"Error: File not found: {path}"
        if resolved.is_dir():
            return f"Error: {path} is a directory, not a file. Use list_files to see contents."
        try:
            content = resolved.read_text(encoding="utf-8")
            # Truncate very large files to avoid context explosion
            if len(content) > 15000:
                content = content[:15000] + "\n\n... [truncated — file too large]"
            return content
        except Exception as e:
            return f"Error reading file: {e}"

    elif tool_name == "list_files":
        path = tool_input.get("path", ".")
        resolved = _resolve_file_path(skill_dir, path)
        if resolved is None or not resolved.is_dir():
            return f"Error: Directory not found: {path}"
        entries = []
        for entry in sorted(resolved.iterdir()):
            if entry.name.startswith("."):
                continue
            rel = entry.relative_to(skill_dir) if str(entry).startswith(str(skill_dir)) else entry.relative_to(resolved)
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"  {rel}{suffix}")
        return "\n".join(entries) if entries else "(empty directory)"

    return f"Error: Unknown tool: {tool_name}"


def call_skill(skill_md: str, prompt: str, client, model_id: str = _BEDROCK_MODEL_ID,
               skill_name: str | None = None, criteria: str = "", **kwargs) -> str:
    """Run an agent loop with tool access simulating a real skill interaction.

    The agent:
    1. Receives the skill's SKILL.md as its system prompt
    2. Has access to read_file and list_files tools scoped to the skill directory
    3. Can read reference docs on demand (just like a real agent would)
    4. Responds to follow-up questions via a criteria-aware eval user agent
    5. Returns the full conversation for the judge to evaluate

    Falls back to simple mode (no tools) if skill_name is not provided.
    """
    skill_dir = _find_skill_dir(skill_name) if skill_name else None

    # If no skill directory found, fall back to simple single-turn
    if skill_dir is None:
        return _call_skill_simple(skill_md, prompt, client, model_id)

    return _call_skill_agentic(skill_md, prompt, client, model_id, skill_dir, criteria)


def _call_skill_simple(skill_md: str, prompt: str, client, model_id: str) -> str:
    """Simple single-turn call (fallback when no skill directory available)."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "system": skill_md,
        "messages": [{"role": "user", "content": prompt}],
    })
    response = client.invoke_model(
        modelId=model_id, body=body,
        contentType="application/json", accept="application/json",
    )
    response_body = json.loads(response["body"].read())
    return response_body["content"][0]["text"]


def _call_skill_agentic(skill_md: str, prompt: str, client, model_id: str, skill_dir: Path, criteria: str = "") -> str:
    """Run an agentic loop: the agent can use tools and the eval user replies to questions."""
    messages = [{"role": "user", "content": prompt}]
    user_turns_used = 0
    conversation_parts = [f"[User]: {prompt}"]

    for turn in range(_MAX_AGENT_TURNS):
        # Prompt caching: the system prompt (SKILL.md + any preloaded references)
        # is resent every turn, so cache it, plus a moving breakpoint on the last
        # message so each turn reads the prior turns from cache. Strip stale
        # markers first — the API allows at most 4 breakpoints per request.
        for m in messages:
            if isinstance(m["content"], list):
                for block in m["content"]:
                    if isinstance(block, dict):
                        block.pop("cache_control", None)
        last_content = messages[-1]["content"]
        if isinstance(last_content, list) and last_content and isinstance(last_content[-1], dict):
            last_content[-1]["cache_control"] = {"type": "ephemeral"}

        # Call the model with tools
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "system": [{"type": "text", "text": skill_md, "cache_control": {"type": "ephemeral"}}],
            "tools": _TOOLS,
            "messages": messages,
        })
        response = client.invoke_model(
            modelId=model_id, body=body,
            contentType="application/json", accept="application/json",
        )
        response_body = json.loads(response["body"].read())
        stop_reason = response_body["stop_reason"]
        content_blocks = response_body["content"]

        # Add assistant message
        messages.append({"role": "assistant", "content": content_blocks})

        # If the model wants to use a tool, handle it
        if stop_reason == "tool_use":
            tool_results = []
            for block in content_blocks:
                if block["type"] == "tool_use":
                    result = _handle_tool_call(block["name"], block["input"], skill_dir)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # Model produced a text response (end_turn or stop)
        assistant_text = ""
        for block in content_blocks:
            if block["type"] == "text":
                assistant_text += block["text"]

        conversation_parts.append(f"[Assistant]: {assistant_text}")

        # Check if the assistant is asking a follow-up question
        if user_turns_used < _MAX_USER_TURNS and _is_follow_up_question(assistant_text):
            user_reply = _generate_eval_reply(prompt, assistant_text, client, model_id, criteria)
            messages.append({"role": "user", "content": user_reply})
            conversation_parts.append(f"[User]: {user_reply}")
            user_turns_used += 1
            continue

        # Done — agent produced a final response
        break

    return "\n\n".join(conversation_parts)


# ---------------------------------------------------------------------------
# Follow-up question handling
# ---------------------------------------------------------------------------

def _is_follow_up_question(text: str) -> bool:
    """Heuristic: does the assistant response look like it's asking for more info?"""
    lines = text.strip().split("\n")
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


def _generate_eval_reply(original_prompt: str, assistant_question: str, client, model_id: str,
                         criteria: str = "") -> str:
    """Generate a reasonable user reply to a follow-up question.

    The eval agent is criteria-aware: it knows what the test is validating and
    steers the conversation to give the model every opportunity to demonstrate
    the expected behavior.
    """
    system = (
        "You are simulating a user in a test scenario. The user originally asked "
        "something and the assistant asked a follow-up question. Generate a short, "
        "reasonable reply that answers the question so the assistant can proceed. "
        "Be concise — 1-3 sentences max. Pick the simplest option if given choices. "
        "Don't add new requirements.\n\n"
        "IMPORTANT: Stay consistent with the values and parameters in the original "
        "request. If the original request specified particular values (names, numbers, "
        "regions, types), restate those same values — do not change or 'fix' them.\n\n"
        "CONTEXT: This conversation is being evaluated against specific criteria. "
        "Your reply should give the assistant the information it needs to proceed "
        "toward satisfying these criteria. Provide relevant details that enable "
        "the assistant to demonstrate the expected behavior."
    )
    user_msg = (
        f"Original user request: {original_prompt}\n\n"
        f"Assistant asked: {assistant_question}\n\n"
    )
    if criteria:
        user_msg += f"Test criteria (what we're evaluating): {criteria}\n\n"
    user_msg += "Generate a brief, cooperative reply that helps the assistant proceed:"

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 256,
        "system": system,
        "messages": [{"role": "user", "content": user_msg}],
    })
    response = client.invoke_model(
        modelId=model_id, body=body,
        contentType="application/json", accept="application/json",
    )
    response_body = json.loads(response["body"].read())
    return response_body["content"][0]["text"]
