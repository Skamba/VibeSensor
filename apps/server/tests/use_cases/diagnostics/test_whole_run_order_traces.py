from __future__ import annotations

import numpy as np
from test_support.report_helpers import diagnostics_context, wheel_metadata
from test_support.sample_scenarios import make_analysis_sample

from vibesensor.domain import DrivingPhase
from vibesensor.shared.constants.units import KMH_TO_MPS, SECONDS_PER_MINUTE
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.shared.window_quality import WindowQuality, score_window_quality
from vibesensor.use_cases.diagnostics.orders.whole_run_scoring import (
    build_whole_run_order_trace_summary_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    build_whole_run_order_trace_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunWindowSpectralSummary,
    whole_run_window_spectral_summaries_to_jsonl_bytes,
)


def _metadata():
    return diagnostics_context(
        wheel_metadata(
            raw_sample_rate_hz=200.0,
            final_drive_ratio=2.0,
            current_gear_ratio=1.5,
        ),
        run_id="run-order-traces",
        feature_interval_s=0.5,
        fft_window_size_samples=256,
    )


def _window_policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=200,
        window_size_samples=256,
        stride_samples=100,
        overlap_samples=156,
        feature_interval_s=0.5,
    )


def _context_labels(
    *,
    speeds: tuple[float, float, float] = (40.0, 60.0, 80.0),
    rpm_values: tuple[float, float, float] = (1000.0, 1500.0, 2000.0),
) -> tuple[WholeRunContextWindowLabel, ...]:
    return tuple(
        WholeRunContextWindowLabel(
            window_index=index,
            segment_index=0,
            phase=DrivingPhase.CRUISE,
            context_coverage="full",
            speed_validity="measured",
            rpm_validity="measured",
            load_state="steady",
            speed_kmh=speed_kmh,
            speed_band="40-50",
            speed_source="gps",
            engine_rpm=engine_rpm,
            engine_rpm_source="obd2",
        )
        for index, (speed_kmh, engine_rpm) in enumerate(zip(speeds, rpm_values, strict=True))
    )


def _spectral_manifest() -> WholeRunArtifactManifest:
    return WholeRunArtifactManifest(
        run_id="run-order-traces",
        relative_dir="whole-run-artifacts/run-order-traces",
        window_policy=_window_policy(),
        total_window_count=3,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-front",
                relative_path="spectra/sensor-front/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-front",
            ),
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-rear",
                relative_path="spectra/sensor-rear/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-rear",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )


def _context_sample(window_index: int, *, speed_kmh: float, engine_rpm: float):
    return make_analysis_sample(
        t_s=float(window_index) * 0.5,
        speed_kmh=speed_kmh,
        engine_rpm=engine_rpm,
        client_name="context",
        client_id="context",
        location="",
        top_peaks=[],
    )


def _shock_window_quality() -> WindowQuality:
    samples_g = np.zeros((256, 3), dtype=np.float32)
    samples_g[128, 0] = 18.0
    return score_window_quality(
        expected_sample_count=256,
        returned_sample_count=256,
        coverage_state="full",
        samples_g=samples_g,
        peak_amp_g=0.2,
        noise_floor_amp_g=0.01,
    )


def _summary_rows(
    *,
    sensor_scale: float,
    context_labels: tuple[WholeRunContextWindowLabel, ...] | None = None,
    include_predicted_peaks: bool = True,
    fixed_peak_hz: float | None = None,
    window_quality_by_index: dict[int, WindowQuality] | None = None,
) -> tuple[WholeRunWindowSpectralSummary, ...]:
    metadata = _metadata()
    rows: list[WholeRunWindowSpectralSummary] = []
    for label in context_labels or _context_labels():
        context_sample = _context_sample(
            label.window_index,
            speed_kmh=float(label.speed_kmh or 0.0),
            engine_rpm=float(label.engine_rpm or 0.0),
        )
        wheel_hz = None
        driveshaft_hz = None
        order_reference_spec = metadata.order_reference_spec_for(context_sample)
        if order_reference_spec is not None and label.speed_kmh is not None:
            wheel_hz = order_reference_spec.wheel_hz_from_speed_kmh(float(label.speed_kmh))
            driveshaft_hz = order_reference_spec.driveshaft_hz_from_speed_kmh(
                float(label.speed_kmh)
            )
        elif (
            label.speed_kmh is not None
            and metadata.tire_circumference_m is not None
            and metadata.tire_circumference_m > 0
        ):
            wheel_hz = float(label.speed_kmh) * KMH_TO_MPS / float(metadata.tire_circumference_m)
            if metadata.final_drive_ratio is not None and metadata.final_drive_ratio > 0:
                driveshaft_hz = wheel_hz * float(metadata.final_drive_ratio)
        engine_hz = (
            float(label.engine_rpm) / SECONDS_PER_MINUTE
            if label.engine_rpm is not None and label.engine_rpm > 0
            else None
        )
        peaks = []
        predicted_frequencies = (
            wheel_hz,
            wheel_hz * 2.0 if wheel_hz is not None else None,
            driveshaft_hz,
            driveshaft_hz * 2.0 if driveshaft_hz is not None else None,
            engine_hz,
            engine_hz * 2.0 if engine_hz is not None else None,
        )
        if include_predicted_peaks:
            for index, predicted_hz in enumerate(predicted_frequencies, start=1):
                if predicted_hz is None or predicted_hz <= 0:
                    continue
                amplitude = sensor_scale / float(index)
                peaks.append(
                    {
                        "hz": float(predicted_hz),
                        "amp": amplitude,
                        "vibration_strength_db": 30.0 + amplitude * 50.0,
                        "strength_bucket": "l3",
                    }
                )
        if fixed_peak_hz is not None:
            peaks.append(
                {
                    "hz": fixed_peak_hz,
                    "amp": sensor_scale * 1.5,
                    "vibration_strength_db": 30.0 + sensor_scale * 75.0,
                    "strength_bucket": "l3",
                }
            )
        rows.append(
            WholeRunWindowSpectralSummary(
                window_index=label.window_index,
                coverage_state="full",
                returned_sample_start=label.window_index * 100,
                returned_sample_count=256,
                dominant_freq_hz=peaks[0]["hz"],
                vibration_strength_db=24.0 + sensor_scale * 10.0,
                strength_peak_amp_g=max(float(peak["amp"]) for peak in peaks),
                strength_floor_amp_g=0.01,
                strength_bucket="l3",
                top_peaks=tuple(peaks),
                window_quality=(
                    window_quality_by_index.get(label.window_index)
                    if window_quality_by_index is not None
                    else None
                )
                or WindowQuality(
                    score=1.0,
                    state="usable",
                    sample_completeness_score=1.0,
                    packet_integrity_score=1.0,
                    clipping_score=1.0,
                    transient_score=1.0,
                    context_score=1.0,
                    frequency_stability_score=1.0,
                ),
            )
        )
    return tuple(rows)


def _artifact_contents_for(
    *,
    context_labels: tuple[WholeRunContextWindowLabel, ...] | None = None,
    include_predicted_peaks: bool = True,
    fixed_peak_hz: float | None = None,
) -> dict[str, bytes]:
    return {
        "spectral-summary:sensor-front": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(
                sensor_scale=0.14,
                context_labels=context_labels,
                include_predicted_peaks=include_predicted_peaks,
                fixed_peak_hz=fixed_peak_hz,
            )
        ),
        "spectral-summary:sensor-rear": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(
                sensor_scale=0.08,
                context_labels=context_labels,
                include_predicted_peaks=include_predicted_peaks,
                fixed_peak_hz=fixed_peak_hz,
            )
        ),
    }


def _artifact_contents() -> dict[str, bytes]:
    return _artifact_contents_for()


def _trace_bundle_for(
    *,
    context_labels: tuple[WholeRunContextWindowLabel, ...] | None = None,
    include_predicted_peaks: bool = True,
    fixed_peak_hz: float | None = None,
):
    labels = context_labels or _context_labels()
    return build_whole_run_order_trace_artifact_bundle(
        run_id="run-order-traces",
        metadata=_metadata(),
        spectral_manifest=_spectral_manifest(),
        spectral_artifact_contents=_artifact_contents_for(
            context_labels=labels,
            include_predicted_peaks=include_predicted_peaks,
            fixed_peak_hz=fixed_peak_hz,
        ),
        context_labels=labels,
        samples=_samples(),
    )


def _summary_bundle_for(
    *,
    context_labels: tuple[WholeRunContextWindowLabel, ...] | None = None,
    include_predicted_peaks: bool = True,
    fixed_peak_hz: float | None = None,
):
    labels = context_labels or _context_labels()
    trace_bundle = _trace_bundle_for(
        context_labels=labels,
        include_predicted_peaks=include_predicted_peaks,
        fixed_peak_hz=fixed_peak_hz,
    )
    return build_whole_run_order_trace_summary_artifact_bundle(
        order_trace_bundle=trace_bundle,
        context_labels=labels,
    )


def _wheel_1x_summary(summary_bundle):
    return next(
        summary for summary in summary_bundle.summaries if summary.hypothesis_key == "wheel_1x"
    )


def _artifact_contents_with_shock_window(window_index: int) -> dict[str, bytes]:
    quality = _shock_window_quality()
    return {
        "spectral-summary:sensor-front": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(sensor_scale=0.14, window_quality_by_index={window_index: quality})
        ),
        "spectral-summary:sensor-rear": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(sensor_scale=0.08, window_quality_by_index={window_index: quality})
        ),
    }


def _samples():
    return (
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=36.0,
            client_name="front-left",
            client_id="sensor-front",
            location="front-left",
            top_peaks=[{"hz": 5.0, "amp": 0.14}],
        ),
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=36.0,
            client_name="rear-left",
            client_id="sensor-rear",
            location="rear-left",
            top_peaks=[{"hz": 5.0, "amp": 0.08}],
        ),
    )


def test_build_whole_run_order_trace_artifact_bundle_emits_supported_candidate_traces() -> None:
    bundle = build_whole_run_order_trace_artifact_bundle(
        run_id="run-order-traces",
        metadata=_metadata(),
        spectral_manifest=_spectral_manifest(),
        spectral_artifact_contents=_artifact_contents(),
        context_labels=_context_labels(),
        samples=_samples(),
    )

    assert bundle.manifest.artifact(WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY) is not None
    assert bundle.artifact_contents[WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY].count(b"\n") == len(
        bundle.points
    )
    assert {point.order_family for point in bundle.points} == {"wheel", "driveshaft", "engine"}
    wheel_1x = [
        point
        for point in bundle.points
        if point.hypothesis_key == "wheel_1x" and point.harmonic == 1
    ]
    assert len(wheel_1x) == 3
    assert [point.window_index for point in wheel_1x] == [0, 1, 2]
    assert all(point.eligible for point in wheel_1x)
    assert all(point.matched for point in wheel_1x)
    assert all(point.strongest_location == "front-left" for point in wheel_1x)


def test_build_whole_run_order_trace_artifact_bundle_suppresses_shock_windows() -> None:
    bundle = build_whole_run_order_trace_artifact_bundle(
        run_id="run-order-traces",
        metadata=_metadata(),
        spectral_manifest=_spectral_manifest(),
        spectral_artifact_contents=_artifact_contents_with_shock_window(1),
        context_labels=_context_labels(),
        samples=_samples(),
    )

    wheel_1x_by_window = {
        point.window_index: point
        for point in bundle.points
        if point.hypothesis_key == "wheel_1x" and point.harmonic == 1
    }

    shock_point = wheel_1x_by_window[1]
    assert shock_point.eligible
    assert not shock_point.matched
    assert shock_point.window_quality_state == "excluded"
    assert "shock_transient" in shock_point.window_quality_reasons
    assert wheel_1x_by_window[0].matched
    assert wheel_1x_by_window[2].matched


def test_build_whole_run_order_trace_artifact_bundle_is_deterministic() -> None:
    kwargs = {
        "run_id": "run-order-traces",
        "metadata": _metadata(),
        "spectral_manifest": _spectral_manifest(),
        "spectral_artifact_contents": _artifact_contents(),
        "context_labels": tuple(reversed(_context_labels())),
        "samples": tuple(reversed(_samples())),
    }

    first = build_whole_run_order_trace_artifact_bundle(**kwargs)
    second = build_whole_run_order_trace_artifact_bundle(**kwargs)

    assert first.manifest == second.manifest
    assert first.artifact_contents == second.artifact_contents
    assert first.points == second.points


def test_whole_run_order_summary_tracks_constant_speed_order_lock() -> None:
    labels = _context_labels(speeds=(60.0, 60.0, 60.0), rpm_values=(1500.0, 1500.0, 1500.0))
    summary = _wheel_1x_summary(_summary_bundle_for(context_labels=labels))

    assert summary.support_ratio == 1.0
    assert summary.lock_score > 0.95
    assert summary.stable_frequency_min_hz == summary.stable_frequency_max_hz
    assert summary.exemplar_interval_index == 0
    assert [
        (interval.start_window_index, interval.end_window_index)
        for interval in summary.support_intervals
    ] == [(0, 2)]
    assert summary.phase_support[0].phase == DrivingPhase.CRUISE.value
    assert summary.phase_support[0].support_ratio == 1.0


def test_whole_run_order_summary_tracks_acceleration_sweep_order_lock() -> None:
    summary = _wheel_1x_summary(_summary_bundle_for())

    assert summary.support_ratio == 1.0
    assert summary.lock_score > 0.95
    assert summary.stable_frequency_min_hz is not None
    assert summary.stable_frequency_max_hz is not None
    assert summary.stable_frequency_min_hz < summary.stable_frequency_max_hz
    assert summary.support_intervals[0].matched_window_count == 3


def test_whole_run_order_summary_does_not_lock_fixed_resonance_to_speed_sweep() -> None:
    fixed_resonance_hz = 8.185985592665357
    summary = _wheel_1x_summary(
        _summary_bundle_for(include_predicted_peaks=False, fixed_peak_hz=fixed_resonance_hz)
    )

    assert summary.matched_window_count == 1
    assert summary.support_ratio < 0.5
    assert summary.lock_score < 0.5
    assert [
        (interval.start_window_index, interval.end_window_index)
        for interval in summary.support_intervals
    ] == [(1, 1)]


def test_whole_run_order_trace_prefers_synchronous_peak_over_fixed_resonance() -> None:
    fixed_resonance_hz = 8.185985592665357
    trace_bundle = _trace_bundle_for(fixed_peak_hz=fixed_resonance_hz)
    summary = _wheel_1x_summary(_summary_bundle_for(fixed_peak_hz=fixed_resonance_hz))
    wheel_1x = [
        point
        for point in trace_bundle.points
        if point.hypothesis_key == "wheel_1x" and point.harmonic == 1
    ]

    assert all(point.matched for point in wheel_1x)
    assert wheel_1x[0].matched_hz != fixed_resonance_hz
    assert wheel_1x[2].matched_hz != fixed_resonance_hz
    assert summary.support_ratio == 1.0
    assert summary.lock_score > 0.95
