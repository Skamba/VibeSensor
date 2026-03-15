"""Analysis execution and top-cause extraction helpers for tests."""

from __future__ import annotations

from typing import Any

from vibesensor.use_cases.diagnostics import summarize_run_data

from .core import standard_metadata


def run_analysis(
    samples: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    **meta_overrides: Any,
) -> dict[str, Any]:
    """Run the full analysis pipeline on *samples* and return the summary."""
    meta = metadata or standard_metadata(**meta_overrides)
    return summarize_run_data(meta, samples, lang=meta.get("language", "en"))


def extract_top(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first top-cause dict from a summary, or None."""
    causes = summary.get("top_causes") or []
    return causes[0] if causes else None


def top_corner_label(summary: dict[str, Any]) -> str | None:
    """Return the human-readable location/corner from the top cause."""
    top = extract_top(summary)
    if not top:
        return None
    return (
        top.get("strongest_location") or top.get("location_hotspot") or top.get("suspected_source")
    )


def top_confidence(summary: dict[str, Any]) -> float:
    """Return the confidence (0–1) of the top cause, or 0.0 if none."""
    top = extract_top(summary)
    return float(top.get("confidence", 0.0)) if top else 0.0
