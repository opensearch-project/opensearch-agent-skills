import logging
from typing import Dict, Any, List
from opensearchpy import OpenSearch

logger = logging.getLogger(__name__)

class SchemaDiscovery:
    def __init__(self, client: OpenSearch):
        self.client = client

    def discover_indexes(self, pattern: str = "*") -> List[str]:
        """Discover available indexes matching a pattern, excluding hidden/system indexes."""
        try:
            indexes = self.client.cat.indices(index=pattern, format="json")
            return [idx['index'] for idx in indexes if not idx['index'].startswith('.')]
        except Exception as e:
            # Degrading to "no indexes found" is the right behavior for the caller
            # (DISCOVER_SCHEMA should proceed and let downstream steps report missing
            # telemetry), but a connectivity/auth failure looks identical to a
            # genuinely empty cluster unless it's logged somewhere.
            logger.warning("discover_indexes(pattern=%r) failed: %s", pattern, e)
            return []

    def get_mappings(self, index_name: str) -> Dict[str, Any]:
        """Fetch the mappings (schema) for a given index."""
        try:
            mapping = self.client.indices.get_mapping(index=index_name)
            return mapping
        except Exception as e:
            logger.warning("get_mappings(index_name=%r) failed: %s", index_name, e)
            return {}

    def get_available_signals(self) -> Dict[str, bool]:
        """Determine which telemetry signals exist in the cluster."""
        indexes = self.discover_indexes()

        signals = {"logs": False, "traces": False, "metrics": False, "deployments": False}
        # Single pass over indexes rather than four separate any(...) scans --
        # each of which would re-walk the full list from scratch.
        for idx in indexes:
            if "log" in idx:
                signals["logs"] = True
            if "trace" in idx or "otel" in idx:
                signals["traces"] = True
            if "metric" in idx:
                signals["metrics"] = True
            if "deploy" in idx or "event" in idx:
                signals["deployments"] = True
        return signals
