"""Manage the OpenSearch DLS reader role and demo-user role mappings."""

import json

from opensearchpy.exceptions import NotFoundError
from .os_client import build_admin_client


class DLSManager:
    def __init__(self, config: dict):
        self.client = build_admin_client(config)
        cfg = config["opensearch"]
        self.index = cfg["index"]
        self.acl_index = f"{self.index}-acl"
        self.role_name = f"{self.index}-reader"
        self.embedding_mode = config.get("embedding", {}).get("mode", "none")

    def create_role(self, acl_lookup_index: str | None = None):
        lookup_index = acl_lookup_index or self.acl_index
        dls_query = json.dumps({
            "terms": {
                "allowed_users": {
                    "index": lookup_index,
                    "id": "${user.name}",
                    "path": "allowed_users",
                }
            }
        })
        cluster_permissions = []
        if self.embedding_mode == "local":
            cluster_permissions = [
                "cluster:admin/opensearch/ml/models/search",
                "cluster:admin/opensearch/ml/predict",
            ]
        body = {
            "cluster_permissions": cluster_permissions,
            "index_permissions": [
                {
                    # The TLQ lookup is evaluated by the Security plugin. Query users
                    # only need access to the protected content index; granting the
                    # prefix would also expose ACL backing and unrelated indexes.
                    "index_patterns": [self.index],
                    "dls": dls_query,
                    "fls": ["~content_vector"],
                    "allowed_actions": ["read"],
                }
            ]
        }
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/roles/{self.role_name}",
            body=body,
        )

    def create_test_user(self, username: str, password: str):
        """Create a named test user for eval-dls and integration tests."""
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/internalusers/{username}",
            body={"password": password},
        )

    def map_test_user_to_role(self, username: str):
        """Add one demo user without replacing external role-mapping fields."""
        if not username:
            raise ValueError("A non-empty username is required")

        mapping = self.ensure_role_mapping()
        if username in mapping.get("users", []):
            return
        updated = {
            "and_backend_roles": mapping.get("and_backend_roles", []),
            "backend_roles": mapping.get("backend_roles", []),
            "hosts": mapping.get("hosts", []),
            "users": [*mapping.get("users", []), username],
        }
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/rolesmapping/{self.role_name}",
            body=updated,
        )

    def ensure_role_mapping(self) -> dict:
        """Create the role's empty mapping once; leave existing fields untouched."""
        try:
            return self._get_role_mapping()
        except NotFoundError:
            mapping = {"backend_roles": [], "hosts": [], "users": []}
            self.client.transport.perform_request(
                "PUT",
                f"/_plugins/_security/api/rolesmapping/{self.role_name}",
                body=mapping,
            )
            return mapping

    def _get_role_mapping(self) -> dict:
        response = self.client.transport.perform_request(
            "GET",
            f"/_plugins/_security/api/rolesmapping/{self.role_name}",
        )
        return response.get(self.role_name, {})
