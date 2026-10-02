"""Boundary summary shape produced by ``summarize_run_data``."""

from __future__ import annotations


def test_boundary_summarize_run_data_returns_expected_structure() -> None:
    """Boundary summarize_run_data produces a dict with the expected top-level keys."""
    from vibesensor.adapters.analysis_summary import summarize_run_data

    metadata = {
        "run_id": "test-arch",
        "start_time_utc": "2026-01-01T00:00:00Z",
        "end_time_utc": "2026-01-01T00:05:00Z",
    }
    samples = [
        {
            "ts": 0.0,
            "speed_kmh": 80.0,
            "vibration_strength_db": 45.0,
            "location": "Front Left",
        },
        {
            "ts": 1.0,
            "speed_kmh": 80.0,
            "vibration_strength_db": 48.0,
            "location": "Front Left",
        },
    ]
    summary = summarize_run_data(metadata, samples, lang="en", include_samples=False)

    required_keys = {
        "run_id",
        "duration_s",
        "findings",
        "top_causes",
        "speed_stats",
        "run_suitability",
        "data_quality",
    }
    missing = required_keys - set(summary.keys())
    assert not missing, f"summarize_run_data result missing keys: {missing}"
    assert isinstance(summary["findings"], list)
    assert isinstance(summary["top_causes"], list)
