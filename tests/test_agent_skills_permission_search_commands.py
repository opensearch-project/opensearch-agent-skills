"""Command workflow tests for the permission-aware-search CLI."""

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# Make the scripts dir importable (permission_search.py + lib/ package)
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

import permission_search

_SKILL_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "opensearch-skills"
    / "search"
    / "permission-aware-search"
)


class ProviderError(RuntimeError):
    def __init__(self, provider, category, message):
        super().__init__(message)
        self.provider = provider
        self.category = category


def _profile(**overrides):
    profile = {
        "opensearch": {
            "url": "https://localhost:9200",
            "admin_username": "admin",
            "admin_password": "pw",
            "index": "permission-aware-search",
        },
        "embedding": {"mode": "none", "dimension": 384},
    }
    profile.update(overrides)
    return profile

# ---------------------------------------------------------------------------
# permission_search ingest - document ACLs never define user memberships
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "argv",
    [
        ["permission_search.py", "query", "--question", "q", "--password", "pw"],
        ["permission_search.py", "query", "--question", "q", "--user", "alice"],
        ["permission_search.py", "benchmark", "--user", "alice"],
    ],
)
def test_query_commands_require_complete_end_user_credentials(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as exc:
        permission_search.main()

    assert exc.value.code == 2


def test_refresh_acl_rejects_removed_additive_only_mode(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "permission_search.py",
        "refresh-acl",
        "--no-delete",
    ])

    with pytest.raises(SystemExit) as exc:
        permission_search.main()

    assert exc.value.code == 2


def test_refresh_acl_rejects_demo_only_alfresco_flags(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "permission_search.py",
        "refresh-acl",
        "--alfresco-url",
        "http://localhost:8080",
    ])

    with pytest.raises(SystemExit) as exc:
        permission_search.main()

    assert exc.value.code == 2


def test_refresh_acl_rejects_removed_ldap_flags(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "permission_search.py",
        "refresh-acl",
        "--ldap-url",
        "ldap://directory.example",
    ])

    with pytest.raises(SystemExit) as exc:
        permission_search.main()

    assert exc.value.code == 2


def test_check_security_help_exposes_environment_compatible_connection_contract(capsys):
    parser = permission_search._build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["check-security", "--help"])

    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "--profile" not in help_text
    assert "--opensearch-url" in help_text
    assert "--index" in help_text
    assert "--ssl-verify" in help_text
    assert "--username" not in help_text
    assert "--password" not in help_text


def test_check_security_accepts_direct_non_secret_connection_flags():
    parser = permission_search._build_parser()
    args = parser.parse_args([
        "check-security",
        "--opensearch-url",
        "https://search.example:9200",
        "--index",
        "documents",
        "--ssl-verify",
    ])

    config = permission_search._runtime_config(args)
    assert config["opensearch"] == {
        "url": "https://search.example:9200",
        "admin_username": "admin",
        "admin_password": "myStrongPassword123!",
        "ssl_verify": True,
        "index": "documents",
    }


def test_commands_do_not_expose_profile_arguments():
    parser = permission_search._build_parser()
    subparsers = next(
        action for action in parser._actions
        if isinstance(action, permission_search.argparse._SubParsersAction)
    )

    assert set(subparsers.choices) == {
        "benchmark",
        "check-llm",
        "check-security",
        "create-users",
        "eval-dls",
        "ingest",
        "query",
        "refresh-acl",
        "setup",
        "sync-acl",
    }
    for command_parser in subparsers.choices.values():
        assert all(action.dest != "profile" for action in command_parser._actions)


def test_runtime_config_reads_existing_opensearch_environment(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_HOST", "search.internal")
    monkeypatch.setenv("OPENSEARCH_PORT", "9443")
    monkeypatch.setenv("OPENSEARCH_USER", "operator")
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "secret")
    monkeypatch.setenv("OPENSEARCH_INDEX", "documents")
    monkeypatch.setenv("OPENSEARCH_SSL_VERIFY", "true")

    config = permission_search._runtime_config(SimpleNamespace(command="setup"))

    assert config["opensearch"] == {
        "url": "https://search.internal:9443",
        "admin_username": "operator",
        "admin_password": "secret",
        "ssl_verify": True,
        "index": "documents",
    }


def test_main_reports_configuration_errors_without_traceback(monkeypatch, capsys):
    monkeypatch.setenv("OPENSEARCH_SSL_VERIFY", "sometimes")

    with pytest.raises(SystemExit) as exc:
        permission_search.main(["check-security"])

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: OPENSEARCH_SSL_VERIFY")
    assert "Traceback" not in captured.err


def test_cli_reference_uses_meta_skill_relative_commands():
    documents = [
        (_SKILL_DIR / "SKILL.md").read_text(),
        (_SKILL_DIR / "references" / "cli-reference.md").read_text(),
    ]

    for document in documents:
        assert ".../permission_search.py" not in document
        assert "--profile" not in document
        # Commands run from skills/opensearch-skills/, so use the relative path.
        assert "search/permission-aware-search/scripts/permission_search.py" not in document
    assert "--opensearch-url" in documents[1]
    assert "uv run python scripts/permission_search.py" in documents[0]
    assert "permission_search.py check-security" in documents[0]
    assert "opensearch_ops.py preflight-check" not in documents[0]


def test_ingest_does_not_write_acl_lookup_documents(tmp_path, capsys):
    input_path = tmp_path / "documents.jsonl"
    records = [
        {"content": "shared", "allowed_users": ["alice", "bob"]},
        {"content": "bob private", "allowed_users": ["bob"]},
    ]
    input_path.write_text("".join(json.dumps(record) + "\n" for record in records))

    class FakeWriter:
        def __init__(self):
            self.documents = []

        def bulk_index(self, documents):
            self.documents.extend(documents)

        def replace_acl_documents(self, documents):
            raise AssertionError("ingest must not write user principal documents")

    writer = FakeWriter()
    args = SimpleNamespace(
        command="ingest",
        input=str(input_path),
        acl_file=None,
        batch_size=50,
    )

    permission_search.cmd_ingest(
        args,
        writer_factory=lambda profile: writer,
        chunk_text_fn=lambda text, chunk_size, chunk_overlap: [text],
    )

    assert [doc["allowed_users"] for doc in writer.documents] == [
        ["alice", "bob"],
        ["bob"],
    ]
    assert json.loads(capsys.readouterr().out) == {"indexed": 2, "skipped": 0}


def test_sync_acl_replaces_authoritative_snapshot(tmp_path, capsys):
    acl_path = tmp_path / "principals.json"
    acl_path.write_text(json.dumps({
        "alice": ["alice", "GROUP_Finance"],
        "bob": ["bob"],
    }))
    writer = MagicMock()
    writer.replace_acl_documents.return_value = "permission-aware-search-acl-v2"
    args = SimpleNamespace(
        command="sync-acl",
        acl_file=str(acl_path),
    )

    permission_search.cmd_sync_acl(args, writer_factory=lambda profile: writer)

    writer.replace_acl_documents.assert_called_once_with([
        {"_id": "alice", "allowed_users": ["alice", "GROUP_Finance"]},
        {"_id": "bob", "allowed_users": ["bob"]},
    ])
    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "users_synced": 2,
        "acl_backing_index": "permission-aware-search-acl-v2",
    }


def test_eval_dls_audits_effective_roles_and_write_permissions(capsys):
    runner_passwords = {}

    class FakeRunner:
        def __init__(self, config, username, password):
            self.username = username
            runner_passwords[username] = password

        def find_document(self, document_id):
            return self.username == "alice"

    class FakeTransport:
        def __init__(self, username):
            self.username = username

        def perform_request(self, method, path, **kwargs):
            if path == "/_plugins/_security/authinfo":
                return {
                    "user_name": self.username,
                    "roles": ["permission-aware-search-reader", "own_index"],
                }
            assert method == "PUT"
            assert path == "/permission-aware-search/_doc/__permission_check"
            assert kwargs["params"] == {"perform_permission_check": "true"}
            return {
                "accessAllowed": False,
                "missingPrivileges": ["indices:data/write/index"],
            }

    class FakeClient:
        def __init__(self, username):
            self.transport = FakeTransport(username)

    args = SimpleNamespace(
        command="eval-dls",
        allowed_user="alice",
        forbidden_user="bob",
        document_id="doc-1",
        password=None,
        allowed_password="alice-secret",
        forbidden_password="bob-secret",
    )

    permission_search.cmd_eval_dls(
        args,
        runner_factory=FakeRunner,
        client_factory=lambda config, username, password: FakeClient(username),
    )

    result = json.loads(capsys.readouterr().out)
    assert result["allowed_user_sees_document"] is True
    assert result["forbidden_user_sees_document"] is False
    assert result["pass"] is True
    assert runner_passwords == {
        "alice": "alice-secret",
        "bob": "bob-secret",
    }
    assert [check["user"] for check in result["effective_user_checks"]] == [
        "alice",
        "bob",
    ]
    assert all(
        check["expected_role_assigned"] and check["write_blocked"]
        for check in result["effective_user_checks"]
    )


@pytest.mark.parametrize(
    "roles,write_allowed",
    [
        (["own_index"], False),
        (["permission-aware-search-reader"], True),
    ],
)
def test_eval_dls_fails_for_unsafe_effective_permissions(
    roles, write_allowed, capsys
):
    class FakeRunner:
        def __init__(self, config, username, password):
            self.username = username

        def find_document(self, document_id):
            return self.username == "alice"

    class FakeClient:
        class Transport:
            def __init__(self, username):
                self.username = username

            def perform_request(self, method, path, **kwargs):
                if path == "/_plugins/_security/authinfo":
                    return {"user_name": self.username, "roles": roles}
                return {"accessAllowed": write_allowed}

        def __init__(self, username):
            self.transport = self.Transport(username)

    args = SimpleNamespace(
        command="eval-dls",
        allowed_user="alice",
        forbidden_user="bob",
        document_id="doc-1",
        password="secret",
    )

    with pytest.raises(SystemExit) as exc:
        permission_search.cmd_eval_dls(
            args,
            runner_factory=FakeRunner,
            client_factory=lambda config, username, password: FakeClient(username),
        )

    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out)["pass"] is False


def _refresh_args(**overrides):
    values = {
        "command": "refresh-acl",
        "file": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_refresh_acl_replaces_resolved_authoritative_snapshot(tmp_path, capsys):
    writer = MagicMock()
    writer.replace_acl_documents.return_value = "permission-aware-search-acl-v3"
    resolver = MagicMock()
    resolver.get_all_user_principals.return_value = {
        "alice": ["alice", "GROUP_Finance"],
        "bob": ["bob"],
    }
    args = _refresh_args(file=str(tmp_path / "groups.json"))

    permission_search.cmd_refresh_acl(
        args,
        writer_factory=lambda profile: writer,
        resolver_factory=lambda profile: resolver,
    )

    writer.replace_acl_documents.assert_called_once_with([
        {"_id": "alice", "allowed_users": ["alice", "GROUP_Finance"]},
        {"_id": "bob", "allowed_users": ["bob"]},
    ])
    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "users_refreshed": 2,
        "source": "file",
        "acl_backing_index": "permission-aware-search-acl-v3",
    }


def test_refresh_acl_empty_directory_fails_before_writing(tmp_path, capsys):
    resolver = MagicMock()
    resolver.get_all_user_principals.return_value = {}
    writer_factory = MagicMock(side_effect=AssertionError("must not build writer"))

    with pytest.raises(SystemExit) as exc:
        permission_search.cmd_refresh_acl(
            _refresh_args(file=str(tmp_path / "groups.json")),
            writer_factory=writer_factory,
            resolver_factory=lambda profile: resolver,
        )

    assert exc.value.code == 1
    writer_factory.assert_not_called()
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "message": "Directory returned no users",
    }


def test_cmd_query_rag_provider_error_is_structured_and_nonzero(monkeypatch, capsys):
    class FailingRunner:
        def __init__(self, profile, username, password):
            pass

        def query(self, question, top_k, rag):
            raise ProviderError(
                "bedrock", "provider", "Amazon Bedrock request failed."
            )

    fake_module = types.ModuleType("lib.search_runner")
    fake_module.SearchRunner = FailingRunner
    fake_module.LLMProviderError = ProviderError
    monkeypatch.setitem(sys.modules, "lib.search_runner", fake_module)
    monkeypatch.setattr(permission_search, "_runtime_config", lambda args: _profile())
    args = SimpleNamespace(
        command="query",
        user="alice",
        password="password",
        question="question",
        top_k=5,
        rag=True,
        json=True,
    )

    with pytest.raises(SystemExit) as exc:
        permission_search.cmd_query(args)

    assert exc.value.code == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "provider": "bedrock",
        "category": "provider",
        "message": "Amazon Bedrock request failed.",
    }


def test_script_metadata_does_not_install_optional_boto3():
    metadata = Path(permission_search.__file__).read_text().split("# ///", 2)[1]
    assert "boto3" not in metadata
