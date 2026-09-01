#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["opensearch-py>=2.4"]
# ///
"""Compatibility launcher for the self-contained Relevance X-Ray skill."""

from pathlib import Path
import runpy


_SKILL_CLI = (
    Path(__file__).resolve().parents[1]
    / "search"
    / "relevance-x-ray"
    / "scripts"
    / "relevance_x_ray.py"
)


if __name__ == "__main__":
    runpy.run_path(str(_SKILL_CLI), run_name="__main__")
