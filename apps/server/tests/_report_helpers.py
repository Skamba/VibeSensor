"""Shared helpers for report test modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Canonical run-end record reused across report tests.
RUN_END = {"record_type": "run_end", "schema_version": "v2-jsonl", "run_id": "run-01"}


def write_jsonl(path: Path, records: list[dict]) -> None:
    """Write a list of dicts as newline-delimited JSON."""
    path.write_text(
        "\n".join(json.dumps(record, separators=(",", ":")) for record in records) + "\n",
        encoding="utf-8",
    )


def suitability_by_key(summary: dict) -> dict[str, dict]:
    """Index run_suitability items by their check_key."""
    return {
        str(item.get("check_key")): item
        for item in summary["run_suitability"]
        if isinstance(item, dict)
    }


def minimal_summary(**overrides: Any) -> dict:
    """Return a bare-minimum summary dict suitable for ``map_summary``.

    Callers can override or extend any key via keyword arguments.
    """
    base: dict = {
        "top_causes": [],
        "findings": [],
        "speed_stats": {},
        "test_plan": [],
        "run_suitability": [],
        "plots": {},
    }
    base.update(overrides)
    return base
