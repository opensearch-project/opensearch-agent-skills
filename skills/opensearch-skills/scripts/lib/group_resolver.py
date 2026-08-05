"""Resolve group memberships from a directory source.

One backend is supported:
  - file - static JSON file mapping group -> [members]

The backend produces the output shape used to replace the ACL snapshot:
  { username: [username, GROUP_A, GROUP_B, ...] }

The caller writes this as a new ACL snapshot and switches the DLS role so Terms
Lookup stays current when group membership changes in the source.
"""

from __future__ import annotations
import json
from typing import Protocol


class DirectoryBackend(Protocol):
    def get_all_user_principals(self) -> dict[str, list[str]]:
        """Return {username: [username, group1, group2, ...]} for every known user."""
        ...


# -- File backend -------------------------------------------------------------

class FileBackend:
    """Read and invert a JSON object mapping group names to member usernames."""

    def __init__(self, cfg: dict):
        self.path = cfg["path"]

    def get_all_user_principals(self) -> dict[str, list[str]]:
        with open(self.path) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("Group membership file must contain a JSON object")
        for group_name, members in data.items():
            if not isinstance(group_name, str) or not group_name:
                raise ValueError("Group names must be non-empty strings")
            if (
                not isinstance(members, list)
                or any(not isinstance(member, str) or not member for member in members)
            ):
                raise ValueError(
                    f"Group {group_name!r} must contain a list of non-empty usernames"
                )

        user_groups: dict[str, set[str]] = {}
        for group_name, members in data.items():
            for username in members:
                user_groups.setdefault(username, set()).add(group_name)

        return {
            username: list(dict.fromkeys([username] + sorted(groups)))
            for username, groups in user_groups.items()
        }


# -- Factory -------------------------------------------------------------------

def build_resolver(config: dict) -> DirectoryBackend:
    """Build a directory backend from validated runtime configuration."""
    directory = config.get("directory")
    if not directory:
        raise ValueError(
            "No directory configured. Pass --file."
        )
    source = directory.get("source")
    if source == "file":
        return FileBackend(directory["file"])
    raise ValueError(f"Unknown directory source '{source}'. Use 'file'.")
