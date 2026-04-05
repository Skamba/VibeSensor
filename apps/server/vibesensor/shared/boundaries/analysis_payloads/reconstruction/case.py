"""Decode persisted diagnostic summaries into domain DiagnosticCase models."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain.diagnostic_case import DiagnosticCase
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.boundaries.runs.projection import (
    car_from_run_metadata,
    symptom_from_run_metadata,
)
from vibesensor.shared.types.run_schema import RunMetadata

from . import _test_run_builder


def _require_authoritative_case_id(summary: Mapping[str, object]) -> str:
    case_id = summary.get("case_id")
    if isinstance(case_id, str):
        normalized_case_id = case_id.strip()
        if normalized_case_id:
            return normalized_case_id
    raise ValueError("Cannot decode DiagnosticCase from summary without authoritative case_id")


def diagnostic_case_from_summary(summary: Mapping[str, object]) -> DiagnosticCase:
    metadata = summary.get("metadata")
    typed_metadata = (
        run_metadata_from_mapping(metadata)
        if isinstance(metadata, Mapping)
        else RunMetadata.create(
            run_id="",
            start_time_utc="",
            sensor_model="unknown",
            raw_sample_rate_hz=None,
            feature_interval_s=None,
            fft_window_size_samples=None,
            accel_scale_g_per_lsb=None,
        )
    )
    car = car_from_run_metadata(typed_metadata)
    symptoms = (symptom_from_run_metadata(typed_metadata),)
    test_run = _test_run_builder.test_run_from_summary(summary)
    case = DiagnosticCase(
        case_id=_require_authoritative_case_id(summary),
        car=car,
        symptoms=symptoms,
        test_plan=test_run.test_plan,
    )
    return case.add_run(test_run)
