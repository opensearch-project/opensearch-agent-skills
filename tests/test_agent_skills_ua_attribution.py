"""Content-lint tests for cloud usage attribution.

Guards the `AWS_SDK_UA_APP_ID=opensearch-agent-skills` attribution scheme wired
into the cloud skills. See docs/aoss_metrics_collection.md.

Scope: attribution applies to ALL cloud/AWS requests (any service), not just
AOSS. It is delivered via two mechanisms:
  1. Config — `AWS_SDK_UA_APP_ID` is set in the `awslabs.aws-api-mcp-server`
     MCP `env` block, so every AWS call routed through that server is tagged.
  2. Instruction — an always-loaded directive tells the agent to prefix every
     shell `aws` command with `AWS_SDK_UA_APP_ID=opensearch-agent-skills`
     (per-command, never exported), regardless of service.

Design decision protected here (instruction-only for the shell path): example
commands are NOT individually prefixed — the agent applies the rule from the
directive. This keeps the pattern uniform across every skill file.

No cluster, no network, no LLM — pure filesystem checks.
"""

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLOUD = _REPO_ROOT / "skills" / "opensearch-skills" / "cloud"

_APP_ID_VALUE = "opensearch-agent-skills"
_APP_ID_ENV = f"AWS_SDK_UA_APP_ID={_APP_ID_VALUE}"

# SKILL.md files that must carry the shell attribution directive. Each of these
# can be installed independently, so each must state the rule itself.
_DIRECTIVE_FILES = [
    _CLOUD / "SKILL.md",
    _CLOUD / "aws-setup" / "SKILL.md",
    _CLOUD / "aws-setup" / "aoss" / "aoss-nextgen-provisioning" / "SKILL.md",
]

# File whose MCP config must carry the app id in the aws-api-mcp-server env.
_MCP_CONFIG_FILE = _CLOUD / "aws-setup" / "SKILL.md"

# All markdown files under cloud/ — used to assert the instruction-only pattern.
_ALL_CLOUD_MDS = sorted(_CLOUD.rglob("*.md"))

# Matches an example command line individually prefixed with the app id, e.g.
# "AWS_SDK_UA_APP_ID=opensearch-agent-skills aws opensearchserverless ...".
# Anchored at start-of-line so it only flags actual command invocations in code
# blocks, not prose or the directive's inline example.
_PREFIXED_CMD_RE = re.compile(
    rf"^{re.escape(_APP_ID_ENV)}\s+aws\s+", re.MULTILINE
)


class TestFilesExist:
    @pytest.mark.parametrize("path", _DIRECTIVE_FILES, ids=lambda p: str(p.relative_to(_CLOUD)))
    def test_directive_file_exists(self, path):
        assert path.is_file(), f"expected cloud skill file at {path}"


class TestShellDirectivePresent:
    """Every independently-installable cloud SKILL.md states the shell rule."""

    @pytest.mark.parametrize("path", _DIRECTIVE_FILES, ids=lambda p: str(p.relative_to(_CLOUD)))
    def test_app_id_directive_present(self, path):
        text = path.read_text(encoding="utf-8")
        assert _APP_ID_ENV in text, (
            f"{path.relative_to(_REPO_ROOT)}: missing usage-attribution directive "
            f"containing {_APP_ID_ENV!r}"
        )

    @pytest.mark.parametrize("path", _DIRECTIVE_FILES, ids=lambda p: str(p.relative_to(_CLOUD)))
    def test_directive_is_service_agnostic(self, path):
        """The rule must not be scoped to a single service (broadened from AOSS-only)."""
        text = path.read_text(encoding="utf-8").lower()
        assert "attribution" in text, (
            f"{path.relative_to(_REPO_ROOT)}: expected a usage-attribution section"
        )
        # Guard against regressing to the old collection-only carve-out wording.
        assert "do not add it to security-policy" not in text, (
            f"{path.relative_to(_REPO_ROOT)}: directive still contains the old "
            f"collection-only exclusion; attribution now applies to all AWS commands"
        )


class TestMcpEnvAttribution:
    """The aws-api-mcp-server MCP config must carry the app id in its env."""

    def _extract_mcp_json(self, text: str) -> dict:
        """Pull the first ```json ... ``` block that defines mcpServers."""
        for block in re.findall(r"```json\s*(.*?)```", text, re.DOTALL):
            if "mcpServers" in block:
                return json.loads(block)
        pytest.fail("no mcpServers JSON block found in aws-setup/SKILL.md")

    def test_mcp_server_env_has_app_id(self):
        text = _MCP_CONFIG_FILE.read_text(encoding="utf-8")
        config = self._extract_mcp_json(text)
        servers = config.get("mcpServers", {})
        assert "awslabs.aws-api-mcp-server" in servers, (
            "aws-api-mcp-server missing from MCP config"
        )
        env = servers["awslabs.aws-api-mcp-server"].get("env", {})
        assert env.get("AWS_SDK_UA_APP_ID") == _APP_ID_VALUE, (
            f"awslabs.aws-api-mcp-server env must set "
            f'AWS_SDK_UA_APP_ID="{_APP_ID_VALUE}" so MCP-routed AWS calls are '
            f"attributed; found env={env!r}"
        )


class TestInstructionOnlyPattern:
    """Example commands must NOT be individually prefixed (instruction-only)."""

    @pytest.mark.parametrize("path", _ALL_CLOUD_MDS, ids=lambda p: str(p.relative_to(_CLOUD)))
    def test_no_prefixed_example_commands(self, path):
        text = path.read_text(encoding="utf-8")
        prefixed = _PREFIXED_CMD_RE.findall(text)
        assert not prefixed, (
            f"{path.relative_to(_REPO_ROOT)}: found {len(prefixed)} example command(s) "
            f"individually prefixed with the app id. Attribution is instruction-only for "
            f"the shell path — the directive lives in the SKILL.md files; example "
            f"commands should stay clean."
        )
