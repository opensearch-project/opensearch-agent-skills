"""Chunking, ACL resolution, and DLS role tests for permission-aware search."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Make the scripts/lib package importable
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from lib import dls_manager, group_resolver
from lib.chunker import chunk_text


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
# chunker
# ---------------------------------------------------------------------------
def test_chunk_empty_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_chunk_short_text_single_chunk():
    assert chunk_text("one two three", chunk_size=10) == ["one two three"]


def test_chunk_at_exact_size_single_chunk():
    text = " ".join(str(i) for i in range(10))
    assert chunk_text(text, chunk_size=10) == [text]


def test_chunk_splits_with_overlap():
    text = " ".join(str(i) for i in range(25))
    chunks = chunk_text(text, chunk_size=10, chunk_overlap=2)
    # step = size - overlap = 8 -> windows start at 0, 8, 16 (16..24 reaches the end)
    assert len(chunks) == 3
    assert chunks[0].split()[0] == "0"
    assert chunks[0].split()[-1] == "9"
    # overlap: chunk 1 starts 2 words before chunk 0 ended
    assert chunks[1].split()[0] == "8"
    assert chunks[-1].split()[-1] == "24"


# ---------------------------------------------------------------------------
# group_resolver.FileBackend + build_resolver
# ---------------------------------------------------------------------------
def test_file_backend_inverts_group_members(tmp_path):
    f = tmp_path / "groups.json"
    f.write_text(json.dumps({"GROUP_Finance": ["alice"], "GROUP_Everyone": ["alice", "bob"]}))
    result = group_resolver.FileBackend({"path": str(f)}).get_all_user_principals()
    assert result["alice"] == ["alice", "GROUP_Everyone", "GROUP_Finance"]
    assert result["bob"] == ["bob", "GROUP_Everyone"]


def test_file_backend_does_not_infer_format_from_first_entry(tmp_path):
    f = tmp_path / "groups.json"
    f.write_text(json.dumps({"alice": ["alice", "bob"]}))
    result = group_resolver.FileBackend({"path": str(f)}).get_all_user_principals()
    assert result == {"alice": ["alice"], "bob": ["bob", "alice"]}


@pytest.mark.parametrize(
    "data,error",
    [
        ([], "JSON object"),
        ({"": ["alice"]}, "Group names"),
        ({"GROUP_Finance": "alice"}, "GROUP_Finance"),
        ({"GROUP_Finance": ["alice"], "GROUP_HR": [""]}, "GROUP_HR"),
        ({"GROUP_Finance": ["alice"], "GROUP_HR": [1]}, "GROUP_HR"),
    ],
)
def test_file_backend_validates_every_group(tmp_path, data, error):
    f = tmp_path / "groups.json"
    f.write_text(json.dumps(data))

    with pytest.raises(ValueError, match=error):
        group_resolver.FileBackend({"path": str(f)}).get_all_user_principals()


def test_file_backend_empty(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("{}")
    assert group_resolver.FileBackend({"path": str(f)}).get_all_user_principals() == {}


def test_build_resolver_requires_directory():
    with pytest.raises(ValueError):
        group_resolver.build_resolver({})


@pytest.mark.parametrize("source", ["nope", "alfresco", "ldap"])
def test_build_resolver_unknown_source(source):
    with pytest.raises(ValueError, match="Use 'file'"):
        group_resolver.build_resolver({"directory": {"source": source}})


def test_build_resolver_dispatches_file(tmp_path):
    r = group_resolver.build_resolver({"directory": {"source": "file", "file": {"path": str(tmp_path / "x.json")}}})
    assert isinstance(r, group_resolver.FileBackend)


# ---------------------------------------------------------------------------
# dls_manager - name cascade + TLQ role body
# ---------------------------------------------------------------------------
def test_create_role_uses_derived_names_and_tlq(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(dls_manager, "build_admin_client", lambda profile: fake)
    prof = _profile()
    mgr = dls_manager.DLSManager(prof)
    assert mgr.acl_index == "permission-aware-search-acl"
    assert mgr.role_name == "permission-aware-search-reader"

    mgr.create_role(acl_lookup_index="permission-aware-search-acl-v1")
    args, kwargs = fake.transport.perform_request.call_args
    assert args[0] == "PUT"
    assert "roles/permission-aware-search-reader" in args[1]
    body = kwargs["body"]
    dls = json.loads(body["index_permissions"][0]["dls"])
    assert dls["terms"]["allowed_users"]["index"] == "permission-aware-search-acl-v1"
    assert dls["terms"]["allowed_users"]["id"] == "${user.name}"
    assert body["index_permissions"][0]["index_patterns"] == ["permission-aware-search"]
    assert "permission-aware-search-acl" not in body["index_permissions"][0]["index_patterns"]
    assert body["index_permissions"][0]["fls"] == ["~content_vector"]
    assert body["index_permissions"][0]["allowed_actions"] == ["read"]
    assert body["cluster_permissions"] == []


def test_create_role_grants_ml_permissions_only_for_local_embeddings(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(dls_manager, "build_admin_client", lambda profile: fake)
    profile = _profile(embedding={"mode": "local", "dimension": 384})

    dls_manager.DLSManager(profile).create_role()

    body = fake.transport.perform_request.call_args.kwargs["body"]
    assert body["cluster_permissions"] == [
        "cluster:admin/opensearch/ml/models/search",
        "cluster:admin/opensearch/ml/predict",
    ]


def test_map_user_updates_writable_fields_and_preserves_existing_mapping(monkeypatch):
    fake = MagicMock()
    mapping = {
        "and_backend_roles": ["all-required"],
        "backend_roles": ["finance", "ldap-readers"],
        "hosts": ["10.0.*.*"],
        "users": ["existing"],
        "reserved": False,
        "hidden": False,
    }

    def perform_request(method, path, body=None):
        if method == "GET":
            return {"permission-aware-search-reader": copy.deepcopy(mapping)}
        assert method == "PUT"
        assert body == {
            "and_backend_roles": ["all-required"],
            "backend_roles": ["finance", "ldap-readers"],
            "hosts": ["10.0.*.*"],
            "users": ["existing", "alice"],
        }
        mapping.update(body)
        return {"status": "OK"}

    fake.transport.perform_request.side_effect = perform_request
    monkeypatch.setattr(dls_manager, "build_admin_client", lambda profile: fake)
    manager = dls_manager.DLSManager(_profile())
    original_non_user_fields = {
        key: copy.deepcopy(value)
        for key, value in mapping.items()
        if key != "users"
    }

    manager.map_test_user_to_role("alice")
    manager.map_test_user_to_role("alice")
    update_calls = [
        call for call in fake.transport.perform_request.call_args_list
        if call.args[0] == "PUT"
    ]

    assert mapping["users"] == ["existing", "alice"]
    assert {
        key: value for key, value in mapping.items() if key != "users"
    } == original_non_user_fields
    assert len(update_calls) == 1


def test_ensure_role_mapping_leaves_existing_mapping_untouched(monkeypatch):
    fake = MagicMock()
    existing = {
        "backend_roles": ["finance"],
        "hosts": ["10.0.*.*"],
        "users": ["alice"],
    }
    fake.transport.perform_request.return_value = {
        "permission-aware-search-reader": existing,
    }
    monkeypatch.setattr(dls_manager, "build_admin_client", lambda profile: fake)

    result = dls_manager.DLSManager(_profile()).ensure_role_mapping()

    assert result == existing
    fake.transport.perform_request.assert_called_once_with(
        "GET",
        "/_plugins/_security/api/rolesmapping/permission-aware-search-reader",
    )
