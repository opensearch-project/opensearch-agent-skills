"""
Tests for the cluster-operations skill commands.

Uses mock OpenSearch clients — no running cluster required.
Run with: uv run pytest tests/test_agent_skills_cluster_operations.py -v
"""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Make sure the scripts/ directory is importable
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "opensearch-skills" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import opensearch_ops_cluster as cluster_ops


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _args(**kwargs):
    """Build a simple namespace object to simulate argparse results."""
    ns = types.SimpleNamespace()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


def _capture_stdout(fn, *args, **kwargs):
    """Run fn(*args, **kwargs), capture stdout, parse JSON."""
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args, **kwargs)
    output = buf.getvalue().strip()
    return json.loads(output)


# ---------------------------------------------------------------------------
# Mock client factory
# ---------------------------------------------------------------------------

def _mock_client():
    client = MagicMock()
    client.cluster = MagicMock()
    client.nodes = MagicMock()
    client.indices = MagicMock()
    client.cat = MagicMock()
    client.transport = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClusterHealth(unittest.TestCase):

    def test_green_cluster(self):
        mock = _mock_client()
        mock.cluster.health.return_value = {
            "status": "green",
            "number_of_nodes": 3,
            "active_primary_shards": 10,
            "active_shards": 20,
            "relocating_shards": 0,
            "initializing_shards": 0,
            "unassigned_shards": 0,
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_cluster_health, _args(level="cluster"))
        self.assertEqual(result["status"], "green")
        self.assertEqual(result["unassigned_shards"], 0)

    def test_red_cluster(self):
        mock = _mock_client()
        mock.cluster.health.return_value = {
            "status": "red",
            "unassigned_shards": 3,
            "active_primary_shards": 7,
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_cluster_health, _args(level="cluster"))
        self.assertEqual(result["status"], "red")
        self.assertGreater(result["unassigned_shards"], 0)


class TestClusterStats(unittest.TestCase):

    def test_summary_fields_present(self):
        mock = _mock_client()
        mock.cluster.stats.return_value = {
            "status": "yellow",
            "nodes": {"count": {"total": 1, "data": 1}},
            "indices": {
                "count": 5,
                "shards": {"primaries": 10, "replication": 0.0},
                "store": {"size_in_bytes": 1024 * 1024 * 500},
                "docs": {"count": 50000},
            },
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_cluster_stats, _args())
        self.assertIn("status", result)
        self.assertIn("node_count", result)
        self.assertIn("index_count", result)
        self.assertEqual(result["node_count"], 1)
        self.assertEqual(result["index_count"], 5)


class TestAllocationExplain(unittest.TestCase):

    def test_unassigned_primary_node_left(self):
        mock = _mock_client()
        mock.cluster.allocation_explain.return_value = {
            "index": "my-index",
            "shard": 0,
            "primary": True,
            "current_state": "unassigned",
            "unassigned_info": {"reason": "NODE_LEFT", "details": "node_id: abc123"},
            "explanation": "The shard cannot be assigned because it was previously on a node that left.",
            "can_allocate": "no",
            "allocate_explanation": "No valid shard copy found.",
            "node_allocation_decisions": [],
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(
                cluster_ops.cmd_allocation_explain,
                _args(index="my-index", shard=0, primary=True),
            )
        self.assertEqual(result["index"], "my-index")
        self.assertEqual(result["unassigned_info"]["reason"], "NODE_LEFT")
        self.assertEqual(result["can_allocate"], "no")

    def test_no_body_when_no_index_provided(self):
        """When no index is given, the body should be empty (explain first unassigned shard)."""
        mock = _mock_client()
        mock.cluster.allocation_explain.return_value = {
            "index": "other-index",
            "shard": 0,
            "primary": True,
            "current_state": "unassigned",
            "unassigned_info": {"reason": "INDEX_CREATED"},
            "explanation": "No data nodes available.",
            "can_allocate": "no",
            "node_allocation_decisions": [],
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(
                cluster_ops.cmd_allocation_explain,
                _args(index=None, shard=0, primary=True),
            )
        # Should have called allocation_explain with body=None
        call_kwargs = mock.cluster.allocation_explain.call_args
        self.assertIsNone(call_kwargs[1].get("body"))
        self.assertEqual(result["unassigned_info"]["reason"], "INDEX_CREATED")


class TestListShards(unittest.TestCase):

    def test_filters_unassigned_only(self):
        mock = _mock_client()
        mock.cat.shards.return_value = [
            {"index": "idx-1", "shard": "0", "prirep": "p", "state": "UNASSIGNED", "node": None},
            {"index": "idx-2", "shard": "0", "prirep": "p", "state": "STARTED", "node": "node-1"},
            {"index": "idx-3", "shard": "1", "prirep": "r", "state": "UNASSIGNED", "node": None},
        ]
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_list_shards, _args(state="UNASSIGNED"))
        self.assertEqual(len(result), 2)
        self.assertTrue(all(s["state"] == "UNASSIGNED" for s in result))

    def test_returns_all_when_state_is_all(self):
        mock = _mock_client()
        mock.cat.shards.return_value = [
            {"index": "idx-1", "state": "UNASSIGNED"},
            {"index": "idx-2", "state": "STARTED"},
        ]
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_list_shards, _args(state="ALL"))
        self.assertEqual(len(result), 2)


class TestNodeStats(unittest.TestCase):

    def test_jvm_summary_fields(self):
        mock = _mock_client()
        mock.nodes.stats.return_value = {
            "nodes": {
                "node-id-1": {
                    "name": "opensearch-node-1",
                    "jvm": {
                        "mem": {
                            "heap_used_percent": 62,
                            "heap_used_in_bytes": 650 * 1024 * 1024,
                            "heap_max_in_bytes": 1024 * 1024 * 1024,
                        }
                    },
                    "os": {"cpu": {"percent": 12, "load_average": {"1m": 0.45}}},
                    "breakers": {
                        "fielddata": {"tripped": 0},
                        "request": {"tripped": 1},
                    },
                    "indices": {},
                    "thread_pool": {},
                }
            }
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_node_stats, _args(node=None))
        node = result["opensearch-node-1"]
        self.assertEqual(node["heap_used_percent"], 62)
        self.assertEqual(node["cpu_percent"], 12)
        self.assertEqual(node["request_breaker_tripped"], 1)
        self.assertEqual(node["fielddata_breaker_tripped"], 0)


class TestRerouteRetry(unittest.TestCase):

    def test_acknowledged(self):
        mock = _mock_client()
        mock.cluster.reroute.return_value = {"acknowledged": True}
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_reroute_retry, _args())
        self.assertTrue(result["acknowledged"])

    def test_error_handled(self):
        mock = _mock_client()
        mock.cluster.reroute.side_effect = Exception("connection refused")
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_reroute_retry, _args())
        self.assertIn("error", result)


class TestSetReplicas(unittest.TestCase):

    def test_set_zero_replicas(self):
        mock = _mock_client()
        mock.indices.put_settings.return_value = {"acknowledged": True}
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_set_replicas, _args(index="my-index", replicas=0))
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["replicas"], 0)
        call_kwargs = mock.indices.put_settings.call_args
        self.assertEqual(call_kwargs[1]["body"]["number_of_replicas"], 0)


class TestClearCache(unittest.TestCase):

    def test_clear_fielddata(self):
        mock = _mock_client()
        mock.indices.clear_cache.return_value = {
            "_shards": {"total": 5, "successful": 5, "failed": 0}
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(
                cluster_ops.cmd_clear_cache,
                _args(index="my-index", type="fielddata"),
            )
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["cache_type"], "fielddata")

    def test_clear_all_caches(self):
        mock = _mock_client()
        mock.indices.clear_cache.return_value = {"_shards": {"total": 10, "successful": 10, "failed": 0}}
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(
                cluster_ops.cmd_clear_cache,
                _args(index=None, type="all"),
            )
        self.assertEqual(result["cache_type"], "all")


class TestDiskUsage(unittest.TestCase):

    def test_warning_flag_above_watermark(self):
        mock = _mock_client()
        mock.cat.allocation.return_value = [
            {"node": "node-1", "disk.percent": "91", "shards": "50"},
            {"node": "node-2", "disk.percent": "60", "shards": "48"},
        ]
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_disk_usage, _args())
        high_node = next(n for n in result if n["node"] == "node-1")
        low_node = next(n for n in result if n["node"] == "node-2")
        self.assertTrue(high_node["warning"])
        self.assertFalse(low_node["warning"])


class TestListIsmPolicies(unittest.TestCase):

    def test_returns_policy_summary(self):
        mock = _mock_client()
        mock.transport.perform_request.return_value = {
            "policies": [
                {
                    "_id": "log-retention-30d",
                    "policy": {
                        "description": "Rollover + delete after 30d",
                        "default_state": "hot",
                        "states": [{"name": "hot"}, {"name": "warm"}, {"name": "delete"}],
                        "ism_template": [{"index_patterns": ["logs-*"]}],
                    },
                }
            ]
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_list_ism_policies, _args())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "log-retention-30d")
        self.assertIn("hot", result[0]["states"])
        self.assertIn("delete", result[0]["states"])

    def test_ism_plugin_not_available(self):
        mock = _mock_client()
        mock.transport.perform_request.side_effect = Exception("404 Not Found")
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(cluster_ops.cmd_list_ism_policies, _args())
        self.assertIn("error", result)
        self.assertIn("hint", result)


class TestApplyIsmPolicy(unittest.TestCase):

    def test_attaches_policy(self):
        mock = _mock_client()
        mock.transport.perform_request.return_value = {
            "_id": "logs-000001",
            "policy_id": "log-retention-30d",
            "updated": True,
        }
        with patch.object(cluster_ops, "_get_client", return_value=mock):
            result = _capture_stdout(
                cluster_ops.cmd_apply_ism_policy,
                _args(index="logs-000001", policy_id="log-retention-30d"),
            )
        self.assertEqual(result["policy_id"], "log-retention-30d")


# ---------------------------------------------------------------------------
# Spec compliance — name matches folder, description is non-empty, ≤ 1024 chars
# ---------------------------------------------------------------------------

class TestSkillSpecCompliance(unittest.TestCase):

    SKILL_FILE = Path(__file__).resolve().parent.parent / "skills" / "opensearch-skills" / "management" / "cluster-operations" / "SKILL.md"

    def _parse_frontmatter(self):
        """Minimal YAML frontmatter parser — no external deps."""
        content = self.SKILL_FILE.read_text()
        if not content.startswith("---"):
            return {}
        end = content.index("---", 3)
        fm_text = content[3:end].strip()
        result = {}
        current_key = None
        current_multiline = []
        for line in fm_text.splitlines():
            if line.startswith("  ") and current_key:
                current_multiline.append(line.strip())
            elif ":" in line and not line.startswith(" "):
                if current_key and current_multiline:
                    result[current_key] = " ".join(current_multiline)
                    current_multiline = []
                key, _, val = line.partition(":")
                current_key = key.strip()
                val = val.strip().lstrip(">").strip()
                if val:
                    result[current_key] = val
                else:
                    current_multiline = []
        if current_key and current_multiline:
            result[current_key] = " ".join(current_multiline)
        return result

    def test_skill_file_exists(self):
        self.assertTrue(self.SKILL_FILE.exists(), f"SKILL.md not found at {self.SKILL_FILE}")

    def test_name_is_cluster_operations(self):
        fm = self._parse_frontmatter()
        self.assertEqual(fm.get("name"), "cluster-operations")

    def test_description_is_non_empty(self):
        fm = self._parse_frontmatter()
        desc = fm.get("description", "")
        self.assertGreater(len(desc), 50, "description too short")

    def test_description_under_1024_chars(self):
        fm = self._parse_frontmatter()
        desc = fm.get("description", "")
        self.assertLessEqual(len(desc), 1024, f"description is {len(desc)} chars, max is 1024")

    def test_skill_file_under_500_lines(self):
        lines = self.SKILL_FILE.read_text().splitlines()
        self.assertLessEqual(len(lines), 500, f"SKILL.md has {len(lines)} lines, max is 500")

    def test_reference_files_exist(self):
        skill_dir = self.SKILL_FILE.parent
        for ref_file in ["health_diagnosis_guide.md", "remediation_reference.md"]:
            self.assertTrue(
                (skill_dir / ref_file).exists(),
                f"Reference file {ref_file} not found",
            )


if __name__ == "__main__":
    unittest.main()
