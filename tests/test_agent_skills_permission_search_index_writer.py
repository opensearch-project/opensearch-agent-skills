"""Index mappings, model lifecycle, and ACL snapshot tests."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make the scripts/lib package importable
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib import index_writer


def _writer(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: client)
    profile = {
        "opensearch": {
            "url": "https://localhost:9200",
            "admin_username": "admin",
            "admin_password": "password",
            "index": "permission-aware-search",
        },
        "embedding": {"mode": "local", "dimension": 384},
    }
    return index_writer.IndexWriter(profile), client


def test_wait_task_returns_completed_task(monkeypatch):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.side_effect = [
        {"state": "CREATED"},
        {"state": "RUNNING"},
        {"state": "COMPLETED", "model_id": "model-1"},
    ]
    monkeypatch.setattr(index_writer.time, "sleep", lambda _seconds: None)

    assert writer._wait_task("task-1")["model_id"] == "model-1"


@pytest.mark.parametrize(
    "state", ["FAILED", "CANCELLED", "COMPLETED_WITH_ERROR", "EXPIRED", "UNREACHABLE"]
)
def test_wait_task_raises_for_unsuccessful_terminal_state(monkeypatch, state):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.return_value = {
        "state": state,
        "error": "model operation failed",
    }

    with pytest.raises(RuntimeError, match=rf"{state}.*model operation failed"):
        writer._wait_task("task-1")


def test_wait_for_state_raises_on_timeout(monkeypatch):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.return_value = {"state": "RUNNING"}

    with pytest.raises(TimeoutError, match="timed out after 0s.*RUNNING"):
        writer._wait_for_state(
            path="/_plugins/_ml/tasks/task-1",
            state_field="state",
            success_state="COMPLETED",
            pending_states={"CREATED", "RUNNING"},
            description="ML task task-1",
            timeout=0,
        )


def test_wait_for_state_rejects_missing_state(monkeypatch):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.return_value = {"task_id": "task-1"}

    with pytest.raises(RuntimeError, match="entered state None"):
        writer._wait_task("task-1")


def test_deploy_requires_task_id(monkeypatch):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.return_value = {"status": "CREATED"}

    with pytest.raises(RuntimeError, match="did not return a task_id"):
        writer._deploy_and_wait("model-1")


def test_registration_requires_task_id(monkeypatch):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.side_effect = [
        {"hits": {"hits": []}},
        {"status": "CREATED"},
    ]

    with pytest.raises(RuntimeError, match="registration did not return a task_id"):
        writer._get_or_deploy_model()


def test_registration_reuses_completed_task_response(monkeypatch):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.side_effect = [
        {"hits": {"hits": []}},
        {"task_id": "register-1", "status": "CREATED"},
    ]
    writer._wait_task = MagicMock(return_value={
        "state": "COMPLETED",
        "model_id": "model-1",
    })
    writer._deploy_and_wait = MagicMock()

    assert writer._get_or_deploy_model() == "model-1"
    assert client.transport.perform_request.call_count == 2
    writer._wait_task.assert_called_once_with("register-1")
    writer._deploy_and_wait.assert_called_once_with("model-1")


def test_deploy_waits_for_task_and_deployed_model(monkeypatch):
    writer, client = _writer(monkeypatch)
    client.transport.perform_request.side_effect = [
        {"task_id": "task-1", "status": "CREATED"},
        {"state": "COMPLETED"},
        {"model_state": "DEPLOYING"},
        {"model_state": "DEPLOYED"},
    ]
    monkeypatch.setattr(index_writer.time, "sleep", lambda _seconds: None)

    writer._deploy_and_wait("model-1")

    assert client.transport.perform_request.call_args_list[-1].args == (
        "GET",
        "/_plugins/_ml/models/model-1",
    )


@pytest.mark.parametrize(
    "documents,error",
    [
        ([{"_id": "", "allowed_users": ["alice"]}], "non-empty string _id"),
        ([{"_id": "alice", "allowed_users": "alice"}], "list of non-empty principals"),
        ([{"_id": "alice", "allowed_users": ["alice", ""]}], "list of non-empty principals"),
        (
            [
                {"_id": "alice", "allowed_users": ["alice"]},
                {"_id": "alice", "allowed_users": ["alice"]},
            ],
            "Duplicate ACL document",
        ),
    ],
)
def test_acl_snapshot_validates_every_document_before_writing(
    monkeypatch, documents, error
):
    writer, client = _writer(monkeypatch)

    with pytest.raises(ValueError, match=error):
        writer.replace_acl_documents(documents)

    client.indices.create.assert_not_called()


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
# index_writer - mapping varies by embedding mode
# ---------------------------------------------------------------------------
def test_content_mapping_local_has_vector(monkeypatch):
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: MagicMock())
    w = index_writer.IndexWriter(_profile(embedding={"mode": "local", "dimension": 384}))
    props = w._content_mapping()["mappings"]["properties"]
    assert "content_vector" in props
    assert props["content_vector"]["dimension"] == 384


def test_content_mapping_none_omits_vector(monkeypatch):
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: MagicMock())
    w = index_writer.IndexWriter(_profile(embedding={"mode": "none"}))
    props = w._content_mapping()["mappings"]["properties"]
    assert "content_vector" not in props


def test_setup_disables_and_removes_legacy_normalization_pipeline(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    writer = index_writer.IndexWriter(_profile())

    writer._disable_legacy_search_pipeline()

    fake.indices.put_settings.assert_called_once_with(
        index="permission-aware-search",
        body={"index": {"search.default_pipeline": "_none"}},
    )
    fake.transport.perform_request.assert_called_once_with(
        "DELETE",
        "/_search/pipeline/permission-aware-search-search",
    )


def test_setup_creates_acl_alias_with_versioned_backing(monkeypatch):
    fake = MagicMock()
    fake.indices.exists_alias.return_value = False
    fake.indices.exists.return_value = False
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    writer = index_writer.IndexWriter(_profile())
    monkeypatch.setattr(
        writer,
        "_new_acl_backing_name",
        lambda: "permission-aware-search-acl-snapshot",
    )
    monkeypatch.setattr(
        writer,
        "_acl_target_indexes",
        MagicMock(side_effect=[[], ["permission-aware-search-acl-snapshot"]]),
    )

    writer.setup()

    fake.indices.create.assert_any_call(
        index="permission-aware-search-acl-snapshot",
        body={
            **writer._acl_mapping(),
            "aliases": {
                "permission-aware-search-acl": {"is_write_index": True},
            },
        },
    )


def test_replace_acl_snapshot_removes_revoked_principals_and_deleted_users(
    monkeypatch,
):
    fake = MagicMock()
    fake.indices.exists_alias.return_value = True
    fake.indices.get_alias.return_value = {
        "permission-aware-search-acl-old": {
            "aliases": {"permission-aware-search-acl": {}},
        },
    }
    fake.count.return_value = {"count": 1}
    bulk = MagicMock()
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    monkeypatch.setattr(index_writer.helpers, "bulk", bulk)
    manager = MagicMock()
    monkeypatch.setattr(index_writer, "DLSManager", lambda profile: manager)
    writer = index_writer.IndexWriter(_profile())
    monkeypatch.setattr(
        writer,
        "_new_acl_backing_name",
        lambda: "permission-aware-search-acl-new",
    )

    result = writer.replace_acl_documents([
        {"_id": "alice", "allowed_users": ["alice", "alice"]},
    ])

    assert result == "permission-aware-search-acl-new"
    manager.create_role.assert_called_once_with(
        acl_lookup_index="permission-aware-search-acl-new",
    )
    bulk.assert_called_once_with(fake, [{
        "_index": "permission-aware-search-acl-new",
        "_id": "alice",
        "_source": {"allowed_users": ["alice"]},
    }])
    fake.indices.update_aliases.assert_called_once_with(body={"actions": [
        {"remove_index": {"index": "permission-aware-search-acl-old"}},
        {"add": {
            "index": "permission-aware-search-acl-new",
            "alias": "permission-aware-search-acl",
            "is_write_index": True,
        }},
    ]})


def test_replace_acl_snapshot_migrates_legacy_concrete_index(monkeypatch):
    fake = MagicMock()
    fake.indices.exists_alias.return_value = False
    fake.indices.exists.side_effect = lambda index: index == "permission-aware-search-acl"
    fake.count.return_value = {"count": 0}
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    manager = MagicMock()
    monkeypatch.setattr(index_writer, "DLSManager", lambda profile: manager)
    writer = index_writer.IndexWriter(_profile())
    monkeypatch.setattr(
        writer,
        "_new_acl_backing_name",
        lambda: "permission-aware-search-acl-new",
    )

    writer.replace_acl_documents([])

    manager.create_role.assert_called_once_with(
        acl_lookup_index="permission-aware-search-acl-new",
    )
    actions = fake.indices.update_aliases.call_args.kwargs["body"]["actions"]
    assert actions[0] == {
        "remove_index": {"index": "permission-aware-search-acl"},
    }
    assert actions[1]["add"]["alias"] == "permission-aware-search-acl"


def test_replace_acl_snapshot_validation_failure_preserves_live_alias(monkeypatch):
    fake = MagicMock()
    fake.indices.exists_alias.return_value = True
    fake.indices.get_alias.return_value = {
        "permission-aware-search-acl-old": {
            "aliases": {"permission-aware-search-acl": {}},
        },
    }
    fake.indices.exists.return_value = True
    fake.count.return_value = {"count": 1}
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    monkeypatch.setattr(index_writer.helpers, "bulk", MagicMock())
    writer = index_writer.IndexWriter(_profile())
    monkeypatch.setattr(
        writer,
        "_new_acl_backing_name",
        lambda: "permission-aware-search-acl-candidate",
    )

    with pytest.raises(RuntimeError, match="expected 2 documents, found 1"):
        writer.replace_acl_documents([
            {"_id": "alice", "allowed_users": ["alice"]},
            {"_id": "bob", "allowed_users": ["bob"]},
        ])

    fake.indices.update_aliases.assert_not_called()
    fake.indices.delete.assert_called_once_with(
        index="permission-aware-search-acl-candidate",
    )


def test_replace_acl_snapshot_reports_candidate_cleanup_failure(monkeypatch):
    fake = MagicMock()
    fake.indices.exists.return_value = True
    fake.indices.delete.side_effect = RuntimeError("delete failed")
    fake.count.return_value = {"count": 0}
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    monkeypatch.setattr(index_writer.helpers, "bulk", MagicMock())
    writer = index_writer.IndexWriter(_profile())
    monkeypatch.setattr(
        writer,
        "_new_acl_backing_name",
        lambda: "permission-aware-search-acl-candidate",
    )

    with pytest.raises(RuntimeError, match=(
        "candidate 'permission-aware-search-acl-candidate' could not be deleted"
    )):
        writer.replace_acl_documents([
            {"_id": "alice", "allowed_users": ["alice"]},
        ])

    fake.indices.update_aliases.assert_not_called()


def test_replace_acl_snapshot_keeps_new_role_when_alias_cleanup_fails(
    monkeypatch,
):
    fake = MagicMock()
    fake.indices.exists_alias.return_value = True
    fake.indices.get_alias.return_value = {
        "permission-aware-search-acl-old": {
            "aliases": {"permission-aware-search-acl": {}},
        },
    }
    fake.indices.exists.return_value = True
    fake.indices.update_aliases.side_effect = RuntimeError("alias update failed")
    fake.count.return_value = {"count": 0}
    manager = MagicMock()
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    monkeypatch.setattr(index_writer, "DLSManager", lambda profile: manager)
    writer = index_writer.IndexWriter(_profile())
    monkeypatch.setattr(
        writer,
        "_new_acl_backing_name",
        lambda: "permission-aware-search-acl-candidate",
    )

    with pytest.raises(RuntimeError, match=(
        "authorization now targets 'permission-aware-search-acl-candidate'"
    )):
        writer.replace_acl_documents([])

    manager.create_role.assert_called_once_with(
        acl_lookup_index="permission-aware-search-acl-candidate",
    )
    fake.indices.delete.assert_not_called()


def test_replace_acl_snapshot_reports_unverifiable_alias_after_role_switch(
    monkeypatch,
):
    fake = MagicMock()
    fake.indices.exists_alias.side_effect = [True, RuntimeError("lookup failed")]
    fake.indices.get_alias.return_value = {
        "permission-aware-search-acl-old": {
            "aliases": {"permission-aware-search-acl": {}},
        },
    }
    fake.indices.update_aliases.side_effect = RuntimeError("alias update failed")
    fake.count.return_value = {"count": 0}
    manager = MagicMock()
    monkeypatch.setattr(index_writer, "build_admin_client", lambda profile: fake)
    monkeypatch.setattr(index_writer, "DLSManager", lambda profile: manager)
    writer = index_writer.IndexWriter(_profile())
    monkeypatch.setattr(
        writer,
        "_new_acl_backing_name",
        lambda: "permission-aware-search-acl-candidate",
    )

    with pytest.raises(RuntimeError, match=(
        "alias 'permission-aware-search-acl' could not be verified"
    )):
        writer.replace_acl_documents([])

    manager.create_role.assert_called_once_with(
        acl_lookup_index="permission-aware-search-acl-candidate",
    )
    fake.indices.delete.assert_not_called()
