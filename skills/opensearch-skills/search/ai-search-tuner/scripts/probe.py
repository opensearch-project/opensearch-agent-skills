"""Capability detection for ai-search-tuner.

Probe an OpenSearch cluster to determine which modes (dense k-NN, sparse
rank_features, sparse ANN/SEISMIC, hybrid) are supported, and populate a
Capabilities dataclass that the harness uses to gate sweeps gracefully.

Graceful degradation: any probe sub-call that raises is treated as "feature
absent" and recorded in notes — the probe never crashes.
"""

from __future__ import annotations

import re
from typing import Any

# Import from harness/model.py and harness/client.py (flat style per instructions)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "harness"))

from model import Capabilities, Mode
from client import OSClient


def detect_capabilities(client: OSClient) -> Capabilities:
    """Probe the cluster and return what modes it actually supports.

    Detection logic:
    - version: parse from info() -> version.number
    - dense_knn: opensearch-knn plugin present
    - sparse_rank_features + hybrid: opensearch-neural-search plugin present
    - sparse_ann: neural-search present AND version >= 3.3 (SEISMIC introduced)
    - knn_engines: known defaults if knn present (lucene, faiss, nmslib)
    - quantization: conservative baseline (fp32 always; fp16 if version >= 2.13)
    - sparse_models: DEPLOYED model ids from ml-commons registry
    - notes: any detection uncertainties or probe failures

    Args:
        client: OSClient protocol instance (real or fake)

    Returns:
        Capabilities instance with detected features
    """
    version = "unknown"
    dense_knn = False
    sparse_rank_features = False
    sparse_ann = False
    hybrid = False
    knn_engines: tuple[str, ...] = ()
    quantization: tuple[str, ...] = ()
    sparse_models: tuple[str, ...] = ()
    notes: list[str] = []

    # 1. Probe version
    try:
        info = client.info()
        version = info.get("version", {}).get("number", "unknown")
    except Exception as e:
        notes.append(f"Failed to read version: {e}")

    # 2. Probe plugins
    plugins: set[str] = set()
    try:
        plugin_list = client.cat_plugins()
        for p in plugin_list:
            component = p.get("component", "")
            if component:
                plugins.add(component)
    except Exception as e:
        notes.append(f"Failed to read plugins: {e}")

    # Set capabilities based on plugins
    if "opensearch-knn" in plugins:
        dense_knn = True
        # Known default engines when knn is present
        knn_engines = ("lucene", "faiss", "nmslib")

    if "opensearch-neural-search" in plugins:
        sparse_rank_features = True
        hybrid = True
        # sparse_ann (SEISMIC) requires neural-search AND version >= 3.3
        if _version_gte(version, "3.3"):
            sparse_ann = True

    # 3. Quantization detection (conservative baseline)
    # fp32 is always available when knn is present
    if dense_knn:
        quant_list = ["fp32"]
        # fp16 is available from OpenSearch 2.13+
        # (this is a version assumption; actual availability is engine/version dependent)
        if _version_gte(version, "2.13"):
            quant_list.append("fp16")
            notes.append(
                "Quantization availability (fp16/PQ/scalar/binary) is engine and version "
                "dependent; detected baseline only (fp32, fp16 if >=2.13); re-verify at "
                "index-build time."
            )
        else:
            notes.append(
                "Quantization detection conservative: fp32 baseline only for version < 2.13; "
                "fp16/PQ/scalar/binary availability should be re-verified at index-build time."
            )
        quantization = tuple(quant_list)

    # 4. Probe DEPLOYED sparse-encoding models.
    #    Real ML Commons _search returns algorithm but NOT a reliable
    #    model_state (it's None in search hits) — so we filter to
    #    SPARSE_ENCODING candidates, then confirm DEPLOYED via a direct GET
    #    (get_model_state). The fake reports model_state inline, so we accept
    #    that too. Dedupe by id.
    try:
        models = client.ml_models()
        deployed: list[str] = []
        seen: set[str] = set()
        for m in models:
            algo = (m.get("algorithm") or m.get("function_name") or "").upper()
            if "SPARSE" not in algo:
                continue  # only sparse-encoding models; missing algo → not sparse
            model_id = m.get("model_id") or ""
            if not model_id or model_id in seen:
                continue
            # Trust an inline DEPLOYED state (fake); else confirm via direct GET.
            state = m.get("model_state")
            if state is None:
                getter = getattr(client, "get_model_state", None)
                state = getter(model_id) if callable(getter) else "DEPLOYED"
            if state == "DEPLOYED":
                seen.add(model_id)
                deployed.append(model_id)
        sparse_models = tuple(deployed)
    except Exception as e:
        notes.append(f"Failed to read ML models: {e}")

    # If no plugins detected but no error, warn
    if not plugins and not any("Failed to read plugins" in n for n in notes):
        notes.append("No plugins detected; cluster may not support k-NN or neural search.")

    return Capabilities(
        version=version,
        dense_knn=dense_knn,
        sparse_rank_features=sparse_rank_features,
        sparse_ann=sparse_ann,
        hybrid=hybrid,
        knn_engines=knn_engines,
        quantization=quantization,
        sparse_models=sparse_models,
        notes=tuple(notes),
    )


def _version_gte(version: str, target: str) -> bool:
    """Semver compare: is version >= target?

    Component-wise numeric comparison (3.10 > 3.3, not string compare).
    Returns False if version cannot be parsed.

    Args:
        version: e.g. "3.3.0", "2.17.1"
        target: e.g. "3.3", "2.13"

    Returns:
        True if version >= target (component-wise)

    Examples:
        >>> _version_gte("3.3.0", "3.3")
        True
        >>> _version_gte("2.19.1", "3.3")
        False
        >>> _version_gte("3.10.0", "3.3")
        True
        >>> _version_gte("2.13.0", "2.13")
        True
    """
    try:
        # Parse version into numeric components
        v_parts = [int(x) for x in re.split(r"[.-]", version) if x.isdigit()]
        t_parts = [int(x) for x in re.split(r"[.-]", target) if x.isdigit()]

        # Pad shorter with zeros
        max_len = max(len(v_parts), len(t_parts))
        v_parts.extend([0] * (max_len - len(v_parts)))
        t_parts.extend([0] * (max_len - len(t_parts)))

        # Component-wise comparison
        for v, t in zip(v_parts, t_parts):
            if v > t:
                return True
            if v < t:
                return False
        return True  # equal
    except (ValueError, AttributeError):
        # Parse failure -> assume not >= target
        return False


def capability_summary(cap: Capabilities) -> str:
    """Generate a short human-readable summary of detected capabilities.

    Args:
        cap: Capabilities instance from detect_capabilities

    Returns:
        Multi-line string suitable for CLI display
    """
    lines = [
        f"OpenSearch {cap.version}",
        "",
        "Supported modes:",
    ]

    if cap.dense_knn:
        engines = ", ".join(cap.knn_engines) if cap.knn_engines else "detected"
        quant = ", ".join(cap.quantization) if cap.quantization else "fp32"
        lines.append(f"  ✓ Dense k-NN (engines: {engines}; quantization: {quant})")
    else:
        lines.append("  ✗ Dense k-NN (opensearch-knn plugin not found)")

    if cap.sparse_rank_features:
        model_str = f"{len(cap.sparse_models)} model(s)" if cap.sparse_models else "no models"
        lines.append(f"  ✓ Sparse (rank_features, exact) ({model_str})")
    else:
        lines.append("  ✗ Sparse (rank_features) (opensearch-neural-search plugin not found)")

    if cap.sparse_ann:
        lines.append("  ✓ Sparse ANN (sparse_vector/SEISMIC, approximate)")
    else:
        reason = "requires neural-search + version >= 3.3"
        lines.append(f"  ✗ Sparse ANN (SEISMIC) ({reason})")

    if cap.hybrid:
        lines.append("  ✓ Hybrid (normalization + combination)")
    else:
        lines.append("  ✗ Hybrid (requires opensearch-neural-search)")

    if cap.sparse_models:
        lines.append("")
        lines.append("Deployed sparse models:")
        for m in cap.sparse_models:
            lines.append(f"  - {m}")

    if cap.notes:
        lines.append("")
        lines.append("Notes:")
        for note in cap.notes:
            # Wrap long notes
            if len(note) > 76:
                words = note.split()
                current = "  • "
                for word in words:
                    if len(current) + len(word) + 1 > 78:
                        lines.append(current.rstrip())
                        current = "    "
                    current += word + " "
                lines.append(current.rstrip())
            else:
                lines.append(f"  • {note}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Simple CLI for manual testing
    import os

    # Try to connect to cluster
    try:
        from client import RealOSClient
        client = RealOSClient.from_env()
        cap = detect_capabilities(client)
        print(capability_summary(cap))
    except Exception as e:
        print(f"Error: {e}")
        print("\nSet OPENSEARCH_URL and credentials in environment variables.")
