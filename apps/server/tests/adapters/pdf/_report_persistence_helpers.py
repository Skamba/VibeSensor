"""Shared helpers for persistence-oriented PDF analysis tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from test_support.report_helpers import analysis_metadata as make_metadata
from test_support.report_helpers import analysis_sample_with_peaks as sample

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.shared.boundaries.sensor_frame_decoder import (
    sensor_frame_from_mapping,
    sensor_frames_from_mappings,
)
from vibesensor.shared.boundaries.sensor_frame_encoder import sensor_frame_to_json_object
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.diagnostics.findings import _build_persistent_peak_findings
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase


def uniform_samples(
    n: int,
    freq: float,
    amp: float,
    *,
    speed: float = 80.0,
    dt: float = 0.5,
    **kwargs: object,
) -> list[SensorFrame]:
    return sensor_frames_from_mappings(
        [sample(float(i) * dt, speed, [{"hz": freq, "amp": amp}], **kwargs) for i in range(n)],
    )


def build_findings(
    samples: Sequence[JsonObject | SensorFrame],
    *,
    order_finding_freqs: set[float] | None = None,
    per_sample_phases: list[DrivingPhase] | None = None,
) -> list[dict[str, object]]:
    return _build_persistent_peak_findings(
        samples=_typed_samples(samples),
        order_finding_freqs=order_finding_freqs or set(),
        lang="en",
        per_sample_phases=per_sample_phases,
    )


def findings_at_freq(findings: Sequence[object], *freq_strs: str) -> list[object]:
    from vibesensor.domain import Finding

    def _matches(finding: object) -> bool:
        if isinstance(finding, Finding):
            sources = [finding.order or ""]
            if finding.frequency_hz is not None:
                sources.append(str(finding.frequency_hz))
            return any(fs in s for s in sources for fs in freq_strs)
        return any(fs in str(finding.get("frequency_hz_or_order", "")) for fs in freq_strs)

    return [f for f in findings if _matches(f)]


def summarize(
    samples: Sequence[JsonObject | SensorFrame],
    **meta_overrides: object,
) -> dict[str, object]:
    return summarize_run_data(
        make_metadata(**meta_overrides),
        _raw_samples(samples),
        lang="en",
    )


def _typed_samples(samples: Sequence[JsonObject | SensorFrame]) -> list[SensorFrame]:
    return [
        sample if isinstance(sample, SensorFrame) else sensor_frame_from_mapping(sample)
        for sample in samples
    ]


def _raw_samples(samples: Sequence[JsonObject | SensorFrame]) -> list[JsonObject]:
    return [
        sensor_frame_to_json_object(sample)
        if isinstance(sample, SensorFrame)
        else cast(JsonObject, sample)
        for sample in samples
    ]
