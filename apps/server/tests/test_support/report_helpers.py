"""Shared helpers for report test modules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from test_support.findings import NO_FAULT_DIAGNOSIS
from test_support.report_record_builders import (
    RUN_END as RUN_END,
)
from test_support.report_record_builders import (
    analysis_metadata as analysis_metadata,
)
from test_support.report_record_builders import (
    analysis_sample as analysis_sample,
)
from test_support.report_record_builders import (
    analysis_sample_with_peaks as analysis_sample_with_peaks,
)
from test_support.report_record_builders import (
    diagnostics_context as diagnostics_context,
)
from test_support.report_record_builders import (
    make_order_finding_samples as make_order_finding_samples,
)
from test_support.report_record_builders import (
    report_run_metadata as report_run_metadata,
)
from test_support.report_record_builders import (
    report_sample as report_sample,
)


def suitability_by_key(summary: dict) -> dict[str, dict]:
    """Index run_suitability items by their check_key."""
    return {
        str(item.get("check_key")): item
        for item in summary["run_suitability"]
        if isinstance(item, dict)
    }


def minimal_summary(**overrides: Any) -> dict:
    """Return a bare-minimum analysis summary that the report view model accepts.

    Callers can override or extend any key via keyword arguments.
    """
    base: dict = {
        "run_id": "run-01",
        "lang": "en",
        "metadata": {},
        "report_date": "",
        "record_length": "",
        "duration_s": 0.0,
        "raw_sample_rate_hz": None,
        "start_time_utc": "",
        "end_time_utc": "",
        "warnings": [],
        "sensor_locations": [],
        "sensor_locations_connected_throughout": [],
        "sensor_intensity_by_location": [],
        "sensor_count_used": 0,
        "most_likely_origin": {},
        "diagnosis": deepcopy(NO_FAULT_DIAGNOSIS),
        "top_causes": [],
        "findings": [],
        "speed_stats": {"min_kmh": None, "max_kmh": None},
        "phase_info": {"phase_pcts": {}},
        "run_suitability": [],
        "plots": {},
    }
    base.update(overrides)
    raw_metadata = base.get("metadata")
    raw_run_id = str(base.get("run_id") or "").strip()
    if isinstance(raw_metadata, dict) and raw_metadata and raw_run_id:
        metadata = dict(raw_metadata)
        metadata.setdefault("run_id", raw_run_id)
        base["metadata"] = metadata
    return base


# ---------------------------------------------------------------------------
# Order-analysis integration helpers (merged from report_analysis_integration.py)
# ---------------------------------------------------------------------------
